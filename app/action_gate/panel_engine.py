"""Validated execution of the original visual panel's policy format.

This evaluator makes no network calls, performs no dispatch and never invents model
usage or cache hits. ``context`` is a trusted server argument, not request metadata;
only the test/compare caller may provide synthetic counters or classifier faults.
The semantic adapter is an explicitly labelled deterministic baseline. Its input
always receives mandatory secret/PII sanitization, regardless of pipeline ordering.

Custom regex intentionally supports a bounded subset: literals, character classes,
anchors, escapes and bounded quantifiers. Groups, alternatives, lookarounds,
backreferences, unbounded quantifiers and multiple variable repeats are rejected.
This avoids running user-authored backtracking programs with an unbounded cost.
"""
from copy import deepcopy
from functools import lru_cache
import json
import math
import re
import time
from urllib.parse import urlsplit


class PanelValidationError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


MAX_TEXT_BYTES = 65_536
MAX_POLICY_BYTES = 1_000_000
MAX_REGEX_PATTERNS = 64
MAX_EVALUATION_MS = 1000
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
LABEL = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,47}\Z')
OPS = frozenset(('eq', 'neq', 'contains', 'not_contains', 'starts_with', 'lte', 'gte',
                 'email_domain_eq'))
# Content checks can be limited to named tool-call fields. Without ``fields`` a check keeps its
# previous meaning and inspects the whole rendered request, including routing fields.
FIELD_SCOPED_CHECKS = ('secrets_detection', 'pii_detection', 'regex_pattern')
MAX_FIELDS = 16
APPLIES_TO = ('any', 'tool_call', 'input', 'output')
# Reserved target marking content produced by a service rather than by a model. Model-specific
# checks are not applicable to it, and the marker is explicit instead of pretending a model ran.
TOOL_RESULT_TARGET = 'tool-result'
DOMAIN = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?'
                    r'(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+\Z')
EMAIL_LOCAL = re.compile(r'[A-Za-z0-9](?:[A-Za-z0-9._%+-]{0,62}[A-Za-z0-9])?\Z')
RANK = {'allow': 0, 'monitor': 1, 'redact': 2, 'throttle': 3, 'block': 4}
PII_ORDER = ('iban', 'card', 'pesel', 'email', 'phone')

# Defaults preserve the fields written by the original visual/YAML editor.
NODE_TYPES = {
    'secrets_detection': ('Secrets detection', 'rule', ('block', 'redact', 'monitor', 'off'), {'mode': 'redact'}),
    'pii_detection': ('Personal data detection', 'rule', ('block', 'redact', 'monitor', 'off'), {'mode': 'redact', 'entities': ['email', 'phone', 'pesel', 'iban']}),
    'regex_pattern': ('Custom pattern', 'rule', ('block', 'redact', 'monitor', 'off'), {'mode': 'block', 'patterns': ['(?i)internal use only']}),
    'allowed_models': ('Allowed models', 'access', ('block', 'monitor', 'off'), {'mode': 'block', 'models': ['llama3.1:8b', 'qwen2.5:7b']}),
    'denied_paths': ('Denied paths', 'access', ('block', 'monitor', 'off'), {'mode': 'block', 'deny_paths': ['.aws/credentials', '/etc/shadow', '.env']}),
    'service_access': ('Service access rules', 'stage', ('enforce', 'monitor', 'off'), {'mode': 'enforce'}),
    'signature_feed': ('Known exploit signatures', 'signature', ('block', 'monitor', 'off'), {'mode': 'block', 'feed': 'signatures.internal/ai-exploits', 'refresh_minutes': 60}),
    'rate_limit': ('Rate limit', 'budget', ('throttle', 'block', 'monitor', 'off'), {'mode': 'throttle', 'max_per_minute': 30, 'delay_ms': 2000}),
    'token_budget': ('Token budget', 'budget', ('throttle', 'block', 'monitor', 'off'), {'mode': 'throttle', 'daily_tokens': 1_000_000}),
    'loop_detector': ('Runaway loop detector', 'budget', ('block', 'throttle', 'monitor', 'off'), {'mode': 'block', 'max_similar_per_minute': 30}),
    'semantic': ('AI classification', 'ai', ('enforce', 'monitor', 'off'), {
        'mode': 'enforce', 'classifier': 'custom', 'applies_to': 'input', 'model': 'llama3.1:8b',
        'instruction_version': 1, 'instruction': 'Classify the message. Answer with exactly one word: safe or unsafe.',
        'labels': [{'label': 'safe', 'reaction': 'allow'}, {'label': 'unsafe', 'reaction': 'block'}],
        'on_unknown': 'block', 'on_timeout': 'block', 'timeout_ms': 800,
    }),
}
LIMITS = {'max_per_minute': 1_000_000, 'delay_ms': 60_000, 'daily_tokens': 1_000_000_000_000,
          'max_similar_per_minute': 1_000_000, 'refresh_minutes': 525_600,
          'timeout_ms': 30_000, 'instruction_version': 1_000_000_000}

# Bounded built-in patterns. Sanitization is conservative rather than a measured PII classifier.
SECRETS = (
    (re.compile(r'\b(?:AKIA|ASIA)[0-9A-Z]{16}\b'), 'AWS_KEY'),
    (re.compile(r'\bsk-[A-Za-z0-9_-]{12,65536}'), 'API_KEY'),
    (re.compile(r'\bgh[pousr]_[A-Za-z0-9_]{20,65536}'), 'GITHUB_TOKEN'),
    # Withhold the remainder after a PEM header, including incomplete keys. Looking
    # for an absent END after every repeated header would add quadratic work.
    (re.compile(r'-----BEGIN [A-Z ]{0,30}PRIVATE KEY-----[\s\S]{0,65536}'), 'PRIVATE_KEY'),
    (re.compile(r'(?i)\b(?:api[_-]?key|password|secret|access[_-]?token|bearer)\s{0,20}[:= ]\s{0,20}["\x27]?[^\s"\x27,;]{6,65536}'), 'SECRET'),
)
# Frozen prefix set from SWIFT IBAN Registry release 101 (December 2025).
# https://www.swift.com/sites/default/files/files/iban-registry-v101.pdf
# Keep detection conservative for these prefixes; this is not account validation.
IBAN_PREFIXES = (
    'AD AE AL AT AZ BA BE BG BH BI BR BY CH CR CY CZ DE DJ DK DO EE EG ES FI FK FO FR '
    'GB GE GI GL GR GT HN HR HU IE IL IQ IS IT JO KW KZ LB LC LI LT LU LV LY MC MD ME '
    'MK MN MR MT MU NI NL NO OM PK PL PS PT QA RO RS RU SA SC SD SE SI SK SM SO ST SV '
    'TL TN TR UA VA VG XK YE'
).split()
PII = {
    'iban': (re.compile(r'(?i)\b(?:' + '|'.join(IBAN_PREFIXES) + r')\d{2}(?: ?[A-Z0-9]){11,30}\b'), 'IBAN'),
    'card': (re.compile(r'(?<!\w)(?:\d[ -]?){12,18}\d(?!\w)'), 'CARD'),
    'pesel': (re.compile(r'\b\d{11}\b'), 'PESEL'),
    'email': (re.compile(r'(?i)[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,10}'), 'EMAIL'),
    'phone': (re.compile(r'(?<!\w)\+\d(?:[ .()-]?\d){8,14}(?!\d)'), 'PHONE'),
}
SIGNATURES = (
    (re.compile(r'\.pkl\b|\bpickle\.loads?\b|torch\.load', re.I), 'SIG-2024-PICKLE-RCE'),
    (re.compile(r'__reduce__|os\.system\(|subprocess\.Popen', re.I), 'SIG-2023-RCE-PAYLOAD'),
    (re.compile(r'-(?:uncensored|backdoor)\b', re.I), 'SIG-2025-POISONED-REPO'),
)
CREDENTIAL_FIELD = re.compile(r'(?i)(?:password|secret|credential|authorization|api[_-]?key|access[_-]?token|private[_-]?key)')


def _fail(code, message):
    raise PanelValidationError(code, message)


def _mapping(value, allowed, where, required=()):
    if type(value) is not dict:
        _fail('invalid_type', f'{where} must be an object.')
    if any(type(k) is not str for k in value):
        _fail('invalid_field', f'{where} field names must be strings.')
    unknown = set(value) - set(allowed)
    if unknown:
        if any(CREDENTIAL_FIELD.search(k) for k in unknown):
            _fail('credentials_not_allowed', f'{where} cannot contain credentials.')
        _fail('unknown_field', f'{where} contains unsupported fields: {", ".join(sorted(unknown))}.')
    missing = set(required) - set(value)
    if missing:
        _fail('missing_field', f'{where} requires: {", ".join(sorted(missing))}.')


def _text(value, where, limit=256, *, empty=False):
    if type(value) is not str or len(value) > limit or (not empty and not value.strip()):
        _fail('invalid_string', f'{where} must be a {"possibly empty " if empty else "nonempty "}string of at most {limit} characters.')
    if any(ord(c) < 32 and c not in '\n\r\t' for c in value):
        _fail('invalid_string', f'{where} contains control characters.')
    return value


def _identifier(value, where, *, wildcard=False):
    if wildcard and value == '*':
        return value
    if type(value) is not str or not IDENTIFIER.fullmatch(value):
        _fail('invalid_identifier', f'{where} must use letters, digits, dots, hyphens, underscores or colons (1–128 characters).')
    return value


def _enum(value, choices, where):
    if type(value) is not str or value not in choices:
        _fail('invalid_enum', f'{where} must be one of: {", ".join(choices)}.')


def _integer(value, where, maximum, minimum=1):
    if type(value) is not int or not minimum <= value <= maximum:
        _fail('invalid_limit', f'{where} must be an integer from {minimum} to {maximum}.')


def _list(value, where, maximum, minimum=0):
    if type(value) is not list or not minimum <= len(value) <= maximum:
        _fail('invalid_list', f'{where} must contain {minimum}–{maximum} items.')


def _json_size(value, where, limit):
    try:
        encoded = json.dumps(value, allow_nan=False, ensure_ascii=False).encode('utf-8')
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        _fail('invalid_json', f'{where} must be finite, valid JSON.')
    if len(encoded) > limit:
        _fail('size_limit', f'{where} exceeds {limit} bytes.')


@lru_cache(maxsize=256)
def _safe_regex(pattern):
    """Compile only a bounded, non-branching regular expression subset."""
    _text(pattern, 'Pattern', 256)
    source = pattern[4:] if pattern.startswith('(?i)') else pattern
    flags = re.I if pattern.startswith('(?i)') else 0
    # Parsing uses the same parser as re.compile, so escaped operators cannot be confused
    # with executable syntax. No other regex engines or subprocesses are involved.
    try:
        parsed = re._parser.parse(source, flags)
    except (re.error, OverflowError) as exc:
        _fail('invalid_pattern', f'Invalid regular expression: {getattr(exc, "msg", "repetition count exceeds the supported limit")}.')
    constants = re._constants
    allowed_atoms = {constants.LITERAL, constants.NOT_LITERAL, constants.ANY, constants.CATEGORY}
    allowed_classes = {constants.LITERAL, constants.RANGE, constants.NEGATE, constants.CATEGORY}
    expansion, variable = 0, 0
    for opcode, argument in parsed:
        if opcode in allowed_atoms or opcode == constants.AT:
            expansion += 1
        elif opcode == constants.IN and all(op in allowed_classes for op, _ in argument):
            expansion += 1
        elif opcode == constants.MAX_REPEAT:
            low, high, repeated = argument
            if high == constants.MAXREPEAT or high > 128:
                _fail('unsafe_pattern', 'Unbounded regex quantifiers are not supported; use an explicit bound such as {1,128}.')
            if len(repeated) != 1 or (repeated[0][0] not in allowed_atoms and repeated[0][0] != constants.IN):
                _fail('unsafe_pattern', 'Repeated groups, nested repeats and alternatives are not supported.')
            if repeated[0][0] == constants.IN and not all(op in allowed_classes for op, _ in repeated[0][1]):
                _fail('unsafe_pattern', 'Unsupported character class in regular expression.')
            expansion += high
            variable += low != high
        else:
            _fail('unsafe_pattern', 'Regex groups, alternatives, lookarounds and backreferences are not supported; use separate bounded patterns.')
    if variable > 1 or expansion > 256:
        _fail('unsafe_pattern', 'A pattern may have at most one variable repeat and at most 256 expanded characters.')
    compiled = re.compile(source, flags)
    if compiled.match(''):
        _fail('unsafe_pattern', 'A pattern must not match an empty string.')
    return compiled


def _catalog(services):
    if services is None:
        return None
    _list(services, 'Services', 256)
    result = {}
    for service in services:
        if type(service) is not dict:
            _fail('invalid_service', 'Every catalog service must be an object.')
        sid = _identifier(service.get('id'), 'Service id')
        if sid in result:
            _fail('duplicate_id', 'Service ids must be unique.')
        actions = service.get('actions')
        _list(actions, f'{sid}.actions', 256)
        result[sid] = {}
        for action in actions:
            if type(action) is not dict:
                _fail('invalid_service', 'Every catalog action must be an object.')
            name = _identifier(action.get('name'), 'Action name')
            if name in result[sid]:
                _fail('duplicate_id', 'Action names must be unique within a service.')
            params = action.get('params', [])
            _list(params, f'{sid}.{name}.params', 64)
            result[sid][name] = set()
            for param in params:
                if type(param) is not dict:
                    _fail('invalid_service', 'Every action parameter must be an object.')
                result[sid][name].add(_identifier(param.get('name'), 'Parameter name'))
    return result


def validate_policy(policy, services):
    """Validate and normalize a policy against the original panel service catalog.

    All executable fields are known and type checked, including disabled checks.
    Defaults may be omitted in YAML; explicit invalid values never get coerced.
    The returned document shares no mutable objects with either input argument.
    """
    return _validate_policy(policy, _catalog(services))


def _validate_policy(policy, catalog):
    _json_size(policy, 'Policy', MAX_POLICY_BYTES)
    _mapping(policy, ('version', 'default_reaction', 'checks', 'rules'), 'Policy', ('version', 'default_reaction', 'checks', 'rules'))
    _integer(policy['version'], 'Policy version', 1_000_000_000)
    _enum(policy['default_reaction'], ('allow', 'block'), 'Default reaction')
    _list(policy['checks'], 'Checks', 64)
    _list(policy['rules'], 'Rules', 512)
    normalized = deepcopy(policy)
    ids = set()
    access_count = 0
    regex_count = 0
    for index, raw in enumerate(policy['checks']):
        where = f'Check {index + 1}'
        if type(raw) is not dict:
            _fail('invalid_type', f'{where} must be an object.')
        kind = raw.get('type')
        if type(kind) is not str or kind not in NODE_TYPES:
            _fail('unknown_check', f'{where} has an unsupported check type.')
        name, _, modes, defaults = NODE_TYPES[kind]
        fields = {'id', 'type', 'name', *defaults}
        if kind != 'service_access':
            fields.add('exceptions')
        if kind in FIELD_SCOPED_CHECKS:
            fields.add('fields')
            fields.add('applies_to')
        _mapping(raw, fields, where, ('id', 'type'))
        identifier = _identifier(raw['id'], f'{where} id')
        if identifier in ids:
            _fail('duplicate_id', 'Check and rule ids must be unique.')
        ids.add(identifier)
        node = {'name': name, **deepcopy(defaults), **deepcopy(raw)}
        normalized['checks'][index] = node
        _text(node['name'], f'{where} name', 160)
        _enum(node['mode'], modes, f'{where} mode')
        if kind == 'service_access':
            access_count += 1
        if kind == 'regex_pattern':
            # Bound aggregate work as well as the complexity of an individual regex.
            regex_count += len(node['patterns']) if type(node['patterns']) is list else 0
            if regex_count > MAX_REGEX_PATTERNS:
                _fail('pattern_limit', f'At most {MAX_REGEX_PATTERNS} custom patterns are permitted across the pipeline.')
        for key, maximum in LIMITS.items():
            if key in node:
                _integer(node[key], f'{where} {key}', maximum)
        if 'fields' in node:
            values = node['fields']
            _list(values, f'{where} fields', MAX_FIELDS, 1)
            for value in values:
                _identifier(value, f'{where} field scope')
            if len(set(values)) != len(values):
                _fail('duplicate_value', f'{where} fields must not contain duplicates.')
        if 'applies_to' in node and kind in FIELD_SCOPED_CHECKS:
            # Content checks keep their previous meaning unless a direction is stated explicitly.
            _enum(node['applies_to'], APPLIES_TO, f'{where} applies_to')
        for key in ('entities', 'patterns', 'models', 'deny_paths'):
            if key not in node:
                continue
            values = node[key]
            _list(values, f'{where} {key}', 32, 1 if key in ('patterns', 'models') else 0)
            for value in values:
                _text(value, f'{where} {key}', 256)
                if key == 'entities':
                    _enum(value, PII_ORDER, f'{where} entity')
                elif key == 'patterns':
                    _safe_regex(value)
            if len(set(values)) != len(values):
                _fail('duplicate_value', f'{where} {key} must not contain duplicates.')
        if kind == 'signature_feed':
            feed = _text(node['feed'], f'{where} feed', 512)
            try:
                parsed_feed = urlsplit(feed)
            except ValueError:
                _fail('invalid_feed', 'Feed reference is not a valid identifier or URL.')
            if any(c.isspace() for c in feed) or '@' in feed or parsed_feed.query or parsed_feed.fragment:
                _fail('credentials_not_allowed', 'Feed references cannot contain credentials, query parameters or fragments.')
        if kind == 'semantic':
            _enum(node['classifier'], ('injection', 'sensitive_output', 'custom'), f'{where} classifier')
            _enum(node['applies_to'], ('input', 'output'), f'{where} direction')
            _text(node['model'], f'{where} configured model', 160)
            if any(c.isspace() for c in node['model']) or any(c in node['model'] for c in ('@', '?', '#')):
                _fail('invalid_model', 'Model must be a credential-free model identifier; it is not downloaded or contacted.')
            _text(node['instruction'], f'{where} instruction', 8192)
            _enum(node['on_unknown'], ('block', 'allow'), f'{where} unknown-label reaction')
            _enum(node['on_timeout'], ('block', 'allow'), f'{where} timeout reaction')
            _list(node['labels'], f'{where} labels', 32, 2)
            labels = set()
            for item in node['labels']:
                _mapping(item, ('label', 'reaction'), f'{where} label', ('label', 'reaction'))
                if type(item['label']) is not str or not LABEL.fullmatch(item['label']):
                    _fail('invalid_label', 'Labels must be single ASCII words, at most 48 characters.')
                if item['label'] in labels:
                    _fail('duplicate_label', 'Classifier labels must be unique.')
                labels.add(item['label'])
                _enum(item['reaction'], ('allow', 'redact', 'block'), f'{where} label reaction')
        if 'exceptions' in node:
            _list(node['exceptions'], f'{where} exceptions', 64)
            for exception in node['exceptions']:
                _mapping(exception, ('agent', 'match'), f'{where} exception', ('match',))
                _text(exception['match'], f'{where} exception match', 512)
                if 'agent' in exception and exception['agent'] != '':
                    _identifier(exception['agent'], f'{where} exception agent')
    if access_count > 1:
        _fail('duplicate_access_stage', 'Only one service access stage is permitted.')
    for index, rule in enumerate(normalized['rules']):
        where = f'Rule {index + 1}'
        _mapping(rule, ('id', 'subject', 'service', 'action', 'conditions', 'reaction', 'note'), where,
                 ('id', 'subject', 'service', 'action', 'reaction'))
        for key in ('id', 'subject', 'service', 'action'):
            _identifier(rule[key], f'{where} {key}', wildcard=key in ('subject', 'action'))
        if rule['id'] in ids:
            _fail('duplicate_id', 'Check and rule ids must be unique.')
        ids.add(rule['id'])
        _enum(rule['reaction'], ('allow', 'block'), f'{where} reaction')
        if 'note' in rule:
            _text(rule['note'], f'{where} note', 2048, empty=True)
        params = None
        if catalog is not None:
            service = catalog.get(rule['service'])
            if service is None:
                _fail('unknown_service', f'{where} refers to a service absent from the catalog.')
            if rule['action'] != '*' and rule['action'] not in service:
                _fail('unknown_action', f'{where} refers to an action absent from its service.')
            params = set().union(*service.values()) if rule['action'] == '*' else service[rule['action']]
        _list(rule.get('conditions', []), f'{where} conditions', 20)
        for condition in rule.get('conditions', []):
            _mapping(condition, ('param', 'op', 'value'), f'{where} condition', ('param', 'op', 'value'))
            _identifier(condition['param'], f'{where} condition parameter')
            _enum(condition['op'], tuple(sorted(OPS)), f'{where} condition operator')
            _text(condition['value'], f'{where} condition value', 512)
            if params is not None and condition['param'] not in params:
                _fail('unknown_parameter', f'{where} condition refers to an unknown action parameter.')
            if condition['op'] in ('lte', 'gte') and _number(condition['value']) is None:
                _fail('invalid_number', f'{where} numeric condition must contain a finite number.')
            if condition['op'] == 'email_domain_eq' and not valid_domain(condition['value']):
                _fail('invalid_domain', f'{where} email_domain_eq needs a bare domain value, '
                                        'for example acme.example.')
    return normalized


def _number(value):
    if type(value) not in (str, int, float) or (type(value) is str and not value.strip()):
        return None
    try:
        result = float(value)
    except (ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def email_domain(value):
    """Normalized domain of exactly one plain address, or ``None``.

    This is the evaluator's own bounded parser: it must stay pure and dependency-free so the same
    rule can be validated in the panel, replayed in a comparison and executed by the runtime. A
    policy author never supplies ``to_domain``; the operator supplies a domain and the runtime
    parses the argument itself.
    """
    if type(value) is not str or len(value) > 254:
        return None
    if value.count('@') != 1:
        return None
    local, domain = value.split('@')
    if not EMAIL_LOCAL.fullmatch(local) or not DOMAIN.fullmatch(domain):
        return None
    return domain.lower()


def valid_domain(value):
    return type(value) is str and 1 < len(value) <= 253 and DOMAIN.fullmatch(value) is not None


def _scalar(value):
    if type(value) is bool:
        return 'true' if value else 'false'
    if type(value) is float and value.is_integer():
        return str(int(value))
    if type(value) in (str, int, float):
        return str(value)
    return None


def _rule_matches(rule, request):
    if rule['service'] != request.get('service') or rule['subject'] not in ('*', request['agent']) or rule['action'] not in ('*', request.get('action')):
        return False
    for condition in rule.get('conditions', []):
        value = request['params'].get(condition['param'])
        actual, expected = _scalar(value), condition['value']
        if actual is None:
            return False
        op = condition['op']
        if op == 'email_domain_eq':
            # The value is parsed here, never taken from the caller's own claim about its domain.
            domain = email_domain(value)
            matched = domain is not None and domain == expected.strip().lower()
        elif op in ('lte', 'gte'):
            a, b = _number(value), _number(expected)
            matched = a is not None and b is not None and (a <= b if op == 'lte' else a >= b)
        else:
            matched = {'eq': lambda: actual == expected, 'neq': lambda: actual != expected,
                       'contains': lambda: expected in actual, 'not_contains': lambda: expected not in actual,
                       'starts_with': lambda: actual.startswith(expected)}[op]()
        if not matched:
            return False
    return True


def _match_rules(policy, request):
    candidates = [rule for rule in policy['rules'] if _rule_matches(rule, request)]
    if not candidates:
        return policy['default_reaction'], None, f'No matching service rule. Default: {policy["default_reaction"]}.'
    score = lambda rule: (2 if rule['subject'] != '*' else 0) + (1 if rule['action'] != '*' else 0)
    highest = max(map(score, candidates))
    best = [rule for rule in candidates if score(rule) == highest]
    winner = next((rule for rule in best if rule['reaction'] == 'block'), best[0])
    return winner['reaction'], winner['id'], f'Rule {winner["id"]}: {winner["reaction"]}. Specificity {highest}; block wins on a tie.'


def _spans(text, patterns):
    return [(match.start(), match.end(), label) for pattern, label in patterns for match in pattern.finditer(text)]


def _redact(text, spans):
    # Merge overlaps; an overlapping phone/card/IBAN must never expose a suffix.
    merged = []
    for start, end, label in sorted(spans, key=lambda item: (item[0], -item[1])):
        if merged and start < merged[-1][1]:
            old_start, old_end, old_label = merged[-1]
            merged[-1] = (old_start, max(old_end, end), old_label)
        else:
            merged.append((start, end, label))
    for start, end, label in reversed(merged):
        text = text[:start] + '[' + label + ']' + text[end:]
    return text


def sanitize_text(text):
    """Conservatively scrub secrets and all configured PII categories for telemetry/model input."""
    if type(text) is not str:
        return text
    text = _redact(text, _spans(text, SECRETS))
    for entity in PII_ORDER:
        text = _redact(text, _spans(text, (PII[entity],)))
    return text


def sanitize_value(value):
    """Scrub nested JSON telemetry without altering numeric values or trusted counters."""
    if type(value) is str:
        return sanitize_text(value)
    if type(value) is list:
        return [sanitize_value(item) for item in value]
    if type(value) is dict:
        return {key: '[SECRET]' if CREDENTIAL_FIELD.search(str(key)) else sanitize_value(item)
                for key, item in value.items()}
    return value


def _request(request):
    _json_size(request, 'Request', MAX_TEXT_BYTES * 2)
    _mapping(request, ('agent', 'dir', 'target', 'service', 'action', 'params', 'text', 'meta'), 'Request', ('agent', 'dir', 'text'))
    _identifier(request['agent'], 'Request agent')
    _enum(request['dir'], ('input', 'output', 'tool_call'), 'Request direction')
    _text(request['text'], 'Request text', MAX_TEXT_BYTES, empty=True)
    if len(request['text'].encode('utf-8')) > MAX_TEXT_BYTES:
        _fail('size_limit', 'Request text exceeds 65536 bytes.')
    params = request.get('params', {})
    if type(params) is not dict or len(params) > 64:
        _fail('invalid_params', 'Request parameters must be an object with at most 64 entries.')
    for name in params:
        _identifier(name, 'Request parameter name')
    if request['dir'] == 'tool_call':
        _identifier(request.get('service'), 'Request service')
        _identifier(request.get('action'), 'Request action')
    else:
        _text(request.get('target'), 'Request target model', 160)
    if 'meta' in request and type(request['meta']) is not dict:
        _fail('invalid_meta', 'Request metadata must be an object; counters here never influence execution.')
    result = {**request, 'params': params}
    if request['dir'] == 'tool_call':
        # The checked text must describe the arguments that will actually execute.
        # Client-supplied prose cannot hide a signature/secret in an action parameter.
        result['text'], _ = _render_tool_call(result, params)
        if len(result['text'].encode('utf-8')) > MAX_TEXT_BYTES:
            _fail('size_limit', 'Rendered tool call exceeds 65536 bytes.')
    return result


def _render_tool_call(request, params):
    text = request['service'] + '.' + request['action'] + '('
    ranges = []
    for index, (name, value) in enumerate(params.items()):
        text += (', ' if index else '') + name + '='
        encoded = json.dumps(value, ensure_ascii=False)
        ranges.append((len(text), len(text) + len(encoded), name))
        text += encoded
    return text + ')', ranges


def _field_ranges(request, fields):
    """Character ranges of the named arguments inside the rendered tool call.

    Field scoping reuses the same rendering the checks already inspect, so a span maps back to the
    exact argument that produced it and no separate index space is invented.
    """
    _, ranges = _render_tool_call(request, request['params'])
    wanted = set(fields)
    return [(left, right) for left, right, name in ranges if name in wanted]


def _redact_parameters(request, params, spans):
    """Map already-found spans onto canonical arguments without rerunning checks.

    A partly matched string is withheld in full. Redacting a number/bool/object or
    the call's structure cannot preserve the action schema, so admission is refused.
    No source text or raw span is returned as telemetry.
    """
    _, ranges = _render_tool_call(request, params)
    replacements = {}
    for start, end, label in spans:
        affected = [name for left, right, name in ranges if start < right and end > left]
        if not affected or any(type(params[name]) is not str for name in affected):
            return None
        for name in affected:
            replacements[name] = '[REDACTED: ' + label + ']'
    return {**params, **replacements}


def _context(context):
    if context is None:
        return {}
    _mapping(context, ('rpm', 'similar', 'tokens_used', 'tokens_requested', 'tokens_over', 'faults'), 'Execution context')
    for key in ('rpm', 'similar', 'tokens_used', 'tokens_requested'):
        if key in context:
            _integer(context[key], f'Execution context {key}', 10**15, minimum=0)
    if 'tokens_over' in context and type(context['tokens_over']) is not bool:
        _fail('invalid_context', 'tokens_over must be a boolean.')
    faults = context.get('faults', {})
    if type(faults) is not dict or len(faults) > 64:
        _fail('invalid_context', 'Faults must be a bounded mapping of check ids to failure modes.')
    for key, fault in faults.items():
        _identifier(key, 'Fault check id')
        _enum(fault, ('none', 'timeout', 'unknown'), 'Fault mode')
    return context


def _classify(node, text, fault):
    if fault == 'timeout':
        return None, True
    if fault == 'unknown':
        return '__unknown_baseline_label__', False
    if node['classifier'] == 'injection':
        if re.search(r'developer mode|jailbreak|\bDAN\b', text, re.I):
            return 'jailbreak', False
        if re.search(r'ignore (?:all )?(?:previous|prior) instructions|system prompt|<!--\s{0,20}assistant:|prompt injection', text, re.I):
            return 'injection', False
        return 'benign', False
    if node['classifier'] == 'sensitive_output':
        if re.search(r'confidential|reorganisation|layoffs?|salar(?:y|ies)', text, re.I):
            return 'confidential', False
        return ('internal' if re.search(r'\binternal\b', text, re.I) else 'public'), False
    labels = [item['label'] for item in node['labels']]
    return next((label for label in labels[1:] if label.casefold() in text.casefold()), labels[0]), False


def evaluate(policy, request, *, context=None):
    """Evaluate in declared order. ``context`` must come from the trusted caller.

    This pure execution entry point repeats structural validation to fail closed if
    called outside the normal catalog-validation path. Runtime callers validate a
    policy against their service catalog before publishing it. Actual dispatch and
    atomic counters remain the calling service's responsibilities.
    """
    policy = _validate_policy(policy, None)
    request, context = _request(request), _context(context)
    evaluation_started = time.perf_counter()
    text = request['text']
    processed_params = deepcopy(request['params'])
    checks, marks = [], []
    decision, trigger, stopped, throttle = 'allow', None, False, 0
    for node in policy['checks']:
        check_type = node['type']
        base = {'id': node['id'], 'name': node['name'], 'kind': NODE_TYPES[check_type][1], 'type': check_type}
        if stopped or node['mode'] == 'off':
            checks.append({**base, 'result': 'skipped' if stopped else 'off', 'lat': 0})
            continue
        started = time.perf_counter()
        reaction, detail, extra, spans, na = None, '', {}, [], False
        if check_type in ('secrets_detection', 'pii_detection', 'regex_pattern'):
            if check_type == 'secrets_detection':
                patterns = SECRETS
            elif check_type == 'pii_detection':
                patterns = tuple(PII[key] for key in PII_ORDER if key in node['entities'])
            else:
                patterns = tuple((_safe_regex(pattern), 'PATTERN') for pattern in node['patterns'])
            scope = node.get('fields') or []
            direction = node.get('applies_to', 'any')
            if direction != 'any' and direction != request['dir']:
                na = True
            elif scope and request['dir'] == 'tool_call':
                # Field scope selects which arguments a content check may rewrite. It exists so that
                # a routing field such as ``to`` is never replaced by a redaction marker. Outside a
                # tool call there are no named arguments, so the check keeps its previous meaning and
                # inspects the whole text.
                ranges = _field_ranges(request, scope)
                spans = [span for span in _spans(text, patterns)
                         if any(span[0] < right and span[1] > left for left, right in ranges)]
                extra['fieldScope'] = list(scope)
            else:
                spans = _spans(text, patterns)
            if na:
                pass
            elif spans:
                reaction = node['mode']
                detail = 'Found ' + ', '.join(sorted({label for _, _, label in spans}))
            else:
                detail = ('No matching sensitive data or pattern found in ' +
                          (', '.join(scope) if scope else 'the request') + '.')
        elif check_type == 'allowed_models':
            na = request['dir'] == 'tool_call' or request['target'] == TOOL_RESULT_TARGET
            if not na:
                reaction = node['mode'] if request['target'] not in node['models'] else None
                detail = 'Model is not on the allowed list.' if reaction else 'Model is allowed.'
        elif check_type == 'denied_paths':
            na = request['dir'] != 'tool_call'
            if not na:
                values = json.dumps(request['params'], ensure_ascii=False)
                hit = next((path for path in node['deny_paths'] if path in values), None)
                reaction = node['mode'] if hit else None
                detail = 'An argument contains a denied path.' if hit else 'No denied paths in arguments.'
        elif check_type == 'service_access':
            na = request['dir'] != 'tool_call'
            if not na:
                matched, rule_id, detail = _match_rules(policy, {**request, 'params': processed_params})
                extra['rule'] = rule_id
                if matched != 'allow':
                    reaction = 'monitor' if node['mode'] == 'monitor' else matched
        elif check_type == 'signature_feed':
            hit = next((signature for pattern, signature in SIGNATURES if pattern.search(text)), None)
            reaction = node['mode'] if hit else None
            detail = f'Matched {hit}.' if hit else 'No bundled signature matched.'
            extra.update(feed_source='bundled-static-signatures', configured_feed=node['feed'], refreshed=False)
        elif check_type in ('rate_limit', 'loop_detector', 'token_budget'):
            if check_type == 'rate_limit':
                count, maximum = context.get('rpm', 0), node['max_per_minute']
                exceeded = count > maximum
                detail = f'{count} requests in the current minute; limit {maximum}.'
            elif check_type == 'loop_detector':
                count, maximum = context.get('similar', 0), node['max_similar_per_minute']
                exceeded = count > maximum
                detail = f'{count} similar calls in the current minute; limit {maximum}.'
            else:
                count, maximum = context.get('tokens_used', 0), node['daily_tokens']
                requested = context.get('tokens_requested', 0)
                exceeded = bool(context.get('tokens_over')) or count >= maximum or count + requested > maximum
                detail = f'{count} recorded/estimated tokens today plus {requested} reserved; limit {maximum}.'
            reaction = node['mode'] if exceeded else None
            extra['counter_source'] = 'server-context' if context else 'empty-server-context'
        elif check_type == 'semantic':
            na = request['dir'] != node['applies_to']
            if not na:
                sanitized = sanitize_text(text)
                label, timeout = _classify(node, sanitized, context.get('faults', {}).get(node['id']))
                extra.update(label=label, timeout=timeout, input=sanitized, model='deterministic-baseline',
                             configured_model=node['model'], instruction_version=node['instruction_version'],
                             cache='not_applicable', tokens_in=0, tokens_out=0, usage_status='not_applicable',
                             detector='deterministic-baseline-v1', baseline=True,
                             instruction_executed=False, sanitization='mandatory-secrets-and-pii')
                if timeout:
                    reaction = node['on_timeout']
                    detail = f'Explicit test fault: timeout. Configured reaction: {reaction}.'
                else:
                    match = next((item for item in node['labels'] if item['label'] == label), None)
                    reaction = match['reaction'] if match else node['on_unknown']
                    detail = (f'Deterministic baseline label: {label}. Instruction is stored, not executed.' if match else
                              f'Unknown baseline label. Configured reaction: {reaction}.')
                if reaction == 'allow':
                    reaction = None
                elif node['mode'] == 'monitor':
                    reaction = 'monitor'
        if na:
            checks.append({**base, 'result': 'na', 'lat': 0, 'detail': 'Not applicable to this request.'})
            continue
        result = 'pass'
        if reaction:
            exception = next((item for item in node.get('exceptions', [])
                              if (not item.get('agent') or item['agent'] == request['agent'])
                              and item['match'].casefold() == request['text'].casefold()), None)
            if exception:
                result = 'exception'
                detail += ' Passed by a configured exception.'
            else:
                redacted_text = None
                if reaction == 'redact':
                    if request['dir'] == 'tool_call':
                        updated_params = _redact_parameters(request, processed_params, spans)
                        if updated_params is None:
                            reaction = 'block'
                            detail += ' Redaction cannot preserve the action parameter schema; dispatch is refused.'
                        else:
                            processed_params = updated_params
                            redacted_text, _ = _render_tool_call(request, processed_params)
                    else:
                        redacted_text = _redact(text, spans) if spans else f'[REDACTED: {extra.get("label") or "content"}]'
                result = reaction
                if RANK[reaction] > RANK[decision]:
                    decision, trigger = reaction, node['id']
                marks.extend('[' + label + ']' for _, _, label in spans)
                if reaction == 'redact':
                    text = redacted_text
                if reaction == 'throttle':
                    throttle += node.get('delay_ms', 1500)
                if reaction == 'block':
                    stopped = True
        checks.append({**base, 'result': result, 'lat': round((time.perf_counter() - started) * 1000, 3),
                       'detail': detail, **extra})
        if (time.perf_counter() - evaluation_started) * 1000 > MAX_EVALUATION_MS:
            # Each bounded stage can finish, but no later stage or action can run
            # after the local time budget expires. Exceptions cannot override this.
            checks[-1].update(result='block', error='evaluation_time_budget',
                              detail='Local evaluation time budget exceeded; dispatch is refused.')
            decision, trigger, stopped = 'block', node['id'], True
    if request['dir'] == 'tool_call' and not stopped and processed_params != request['params']:
        # A rule checked before a later redaction may authorize a different target.
        # Recheck access against the exact final dispatch arguments before admission.
        access = next((node for node in policy['checks'] if node['type'] == 'service_access'
                       and node['mode'] != 'off'), None)
        if access is not None:
            started = time.perf_counter()
            matched, rule_id, detail = _match_rules(policy, {**request, 'params': processed_params})
            trace = next(check for check in checks if check['id'] == access['id'])
            trace['detail'] += ' Final redacted arguments rechecked: ' + detail
            trace['rule'] = rule_id
            trace['lat'] = round(trace['lat'] + (time.perf_counter() - started) * 1000, 3)
            if matched == 'block':
                reaction = 'monitor' if access['mode'] == 'monitor' else 'block'
                trace['result'] = reaction
                if RANK[reaction] > RANK[decision]:
                    decision, trigger = reaction, access['id']
    triggered = next((check for check in checks if check['id'] == trigger), {})
    result = {'decision': decision, 'trigger': trigger, 'triggerName': triggered.get('name'),
            'triggerType': triggered.get('type'), 'triggerDetail': triggered.get('detail'),
            'triggerRule': triggered.get('rule'), 'checks': checks,
            'overhead': round(sum(check['lat'] for check in checks), 3), 'throttle': throttle,
            'processed': None if decision == 'block' else text, 'marks': list(dict.fromkeys(marks)),
            'version': policy['version']}
    if request['dir'] == 'tool_call':
        result['processedParams'] = None if decision == 'block' else processed_params
    return result
