"""Content controls. No network calls, secrets, or external integrations.

The semantic detector is a dependency supplied by the host. Missing or invalid
signals fail closed by default. A test double is never a production detector.
"""
from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re
import unicodedata
from typing import Callable


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class Signal:
    risk: float
    detector: str


@dataclass(frozen=True)
class Result:
    decision: str
    text: str | None
    reasons: tuple[str, ...]
    findings: tuple[str, ...]
    policy_hash: str
    feed_hash: str
    semantic_status: str
    semantic_risk: float | None

    def as_dict(self):
        return asdict(self)


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def load_json(path: Path):
    try:
        raw = path.read_bytes()
        if len(raw) > 1_000_000:
            raise ValueError('Configuration exceeds size limit')
        def reject_duplicates(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ValueError('Duplicate configuration key')
                result[key] = value
            return result
        value = json.loads(raw, object_pairs_hook=reject_duplicates)
        return value, digest(raw)
    except (OSError, ValueError, RecursionError) as exc:
        raise ConfigurationError('Configuration cannot be read or parsed') from exc


def bounded_number(value, lower, upper):
    return type(value) in (int, float) and math.isfinite(value) and lower <= value <= upper


def validate_documents(policy, feed):
    """Validate the two content documents that a snapshot carries. Pure: no file access.

    The file loader and the configuration importer both call this, so an imported document is
    checked by the same code as a document read from disk. Returns the signature literals; a
    disabled ``signatures`` control does not require a feed at all.
    """
    expected = {'version', 'controls', 'block_sensitivity', 'semantic_threshold',
                'semantic_unavailable', 'allowed_models', 'max_text_bytes'}
    if not isinstance(policy, dict) or set(policy) != expected:
        raise ConfigurationError('Unexpected policy fields')
    controls = policy['controls']
    if (type(policy['version']) is not int or policy['version'] != 1
            or not isinstance(controls, dict)
            or set(controls) != {'pii', 'secrets', 'signatures', 'semantic'}
            or any(type(v) is not bool for v in controls.values())
            or not bounded_number(policy['block_sensitivity'], 0, 1)
            or not bounded_number(policy['semantic_threshold'], 0, 1)
            or policy['semantic_unavailable'] not in ('block', 'allow_degraded')
            or not isinstance(policy['allowed_models'], list)
            or not policy['allowed_models']
            or any(not isinstance(m, str) or not m.strip() for m in policy['allowed_models'])
            or type(policy['max_text_bytes']) is not int
            or not 1 <= policy['max_text_bytes'] <= 1_000_000):
        raise ConfigurationError('Invalid policy value')
    if not controls['signatures']:
        return ()
    if (not isinstance(feed, dict) or set(feed) != {'version', 'signatures'}
            or type(feed['version']) is not int or feed['version'] != 1
            or not isinstance(feed['signatures'], list) or len(feed['signatures']) > 1000):
        raise ConfigurationError('Invalid signature feed')
    identifiers = set()
    for item in feed['signatures']:
        if (not isinstance(item, dict) or set(item) != {'id', 'literal', 'description'}
                or any(not isinstance(v, str) or not v.strip() for v in item.values())
                or len(item['literal']) > 1000 or item['id'] in identifiers):
            raise ConfigurationError('Invalid signature entry')
        identifiers.add(item['id'])
    return tuple(feed['signatures'])


def load_configuration(policy_path: Path, feed_path: Path):
    """File wrapper kept for callers that still own files. The gate itself uses a snapshot."""
    policy, policy_hash = load_json(policy_path)
    if (isinstance(policy, dict) and isinstance(policy.get('controls'), dict)
            and policy['controls'].get('signatures') is False):
        # A disabled control never requires the feed document to exist.
        validate_documents(policy, None)
        return policy, (), policy_hash, 'disabled'
    feed, feed_hash = load_json(feed_path)
    signatures = validate_documents(policy, feed)
    return policy, signatures, policy_hash, feed_hash


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text)
                   if unicodedata.category(c) != 'Cf')


def luhn(text):
    digits = [int(c) for c in text if c.isascii() and c.isdigit()]
    if not 13 <= len(digits) <= 19 or len(set(digits)) == 1:
        return False
    total = 0
    for i, n in enumerate(reversed(digits)):
        if i % 2:
            n *= 2
            n -= 9 if n > 9 else 0
        total += n
    return total % 10 == 0


# Patterns are intentionally bounded; user-editable feeds use literals, not regex.
PATTERNS = (
    ('secret', 'secrets', 1.0, re.compile(r'(?i)\b(?:sk-[a-z0-9_-]{12,200}|(?:api[_-]?key|password|token)\s*[:=]\s*["\x27]?[^\s"\x27,;]{6,200})'), None),
    ('email', 'pii', 0.4, re.compile(r'(?i)\b[a-z0-9.!#$%&\x27*+/=?^_`{|}~-]{1,64}@[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})+\b'), None),
    ('card', 'pii', 0.8, re.compile(r'(?<!\d)(?:[0-9][ -]?){12,18}[0-9](?!\d)'), luhn),
    ('iban', 'pii', 0.8, re.compile(r'(?i)\b[A-Z]{2}[0-9]{2}(?:[ ]?[A-Z0-9]){11,30}\b'), None),
    ('phone', 'pii', 0.4, re.compile(r'(?<!\w)\+[0-9](?:[ .()-]?[0-9]){8,14}(?!\d)'), None),
)


class ContentGate:
    """Content controls bound to one already-validated pair of documents.

    The gate never reads a file. A snapshot supplies the policy, its hash, the signature literals
    and the feed hash, so an invocation cannot observe a policy change between its input and its
    output check.
    """

    def __init__(self, policy: dict, signatures=(), policy_hash: str = '', feed_hash: str = '',
                 detector: Callable[[str], Signal] | None = None):
        self.policy = policy
        self.signatures = tuple(signatures)
        self.policy_hash = policy_hash
        self.feed_hash = feed_hash
        self.detector = detector

    @classmethod
    def from_paths(cls, policy_path, feed_path, detector=None) -> 'ContentGate':
        """Build a gate from files. Used by tooling and tests; the gateway uses a snapshot."""
        policy, signatures, policy_hash, feed_hash = load_configuration(Path(policy_path),
                                                                       Path(feed_path))
        return cls(policy, signatures, policy_hash, feed_hash, detector)

    def inspect(self, text, model='demo-local', direction='input'):
        if not isinstance(text, str) or direction not in ('input', 'output') or not isinstance(model, str):
            raise ValueError('Invalid interaction')
        policy = self.policy
        signatures = self.signatures
        policy_hash, feed_hash = self.policy_hash, self.feed_hash
        def result(decision, output, reasons=(), findings=(), status='not_run', risk=None):
            return Result(decision, output, tuple(reasons), tuple(findings), policy_hash, feed_hash, status, risk)
        if model not in policy['allowed_models']:
            return result('block', None, ('model_not_allowed',))
        try:
            size = len(text.encode('utf-8'))
        except UnicodeEncodeError:
            return result('block', None, ('invalid_unicode',))
        if size > policy['max_text_bytes']:
            return result('block', None, ('text_size_limit',))
        text = normalized(text)
        hits = [item['id'] for item in signatures if normalized(item['literal']).casefold() in text.casefold()]
        if hits:
            return result('block', None, ('exploit_signature',), hits)
        spans = []
        findings = set()
        max_sensitivity = 0.0
        for label, control, sensitivity, pattern, validate in PATTERNS:
            if not policy['controls'][control]:
                continue
            for match in pattern.finditer(text):
                if validate and not validate(match.group()):
                    continue
                spans.append((match.start(), match.end()))
                findings.add(label)
                max_sensitivity = max(max_sensitivity, sensitivity)
        if spans and max_sensitivity >= policy['block_sensitivity']:
            return result('block', None, ('sensitivity_threshold',), sorted(findings))
        # Merge overlapping spans so nested patterns cannot expose any suffix.
        merged = []
        for start, end in sorted(spans):
            if merged and start <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
            else:
                merged.append((start, end))
        sanitized = text
        for start, end in reversed(merged):
            sanitized = sanitized[:start] + '[REDACTED]' + sanitized[end:]
        status, risk = 'disabled', None
        if policy['controls']['semantic']:
            try:
                if self.detector is None:
                    raise RuntimeError('No semantic detector configured')
                signal = self.detector(sanitized)
                if (not isinstance(signal, Signal) or not bounded_number(signal.risk, 0, 1)
                        or not isinstance(signal.detector, str) or not signal.detector.strip()):
                    raise ValueError('Invalid semantic signal')
                status, risk = 'available', signal.risk
            except Exception:
                status = 'unavailable'
                if policy['semantic_unavailable'] == 'block':
                    return result('block', None, ('semantic_unavailable',), sorted(findings), status)
            if risk is not None and risk >= policy['semantic_threshold']:
                return result('block', None, ('semantic_threshold',), sorted(findings), status, risk)
        reasons = ['sensitive_data_redacted'] if merged else []
        if status == 'unavailable':
            reasons.append('semantic_unavailable_allowed_by_policy')
        return result('redact' if merged else 'allow', sanitized, reasons, sorted(findings), status, risk)
