"""Configuration bundle: one manifest that pins every control input of a release.

A judge can edit these files on the host while the stack is running. The bundle is
therefore re-read per invocation and the resulting release hash is pinned to that
request. Invalid configuration never silently degrades: it raises ConfigurationError
and the caller must fail closed.
"""
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path

from .content import ConfigurationError

MAX_COMPONENT_BYTES = 1_000_000
REQUIRED_COMPONENTS = (
    'contentPolicy',
    'signatureFeed',
    'services',
    'budgets',
    'detectors',
    'principals',
)
EFFECTS = ('read', 'write', 'destructive')
ROLES = ('agent', 'operator')


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def hash_bytes(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate key')
        result[key] = value
    return result


def _read_json(path: Path):
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigurationError(f'component unreadable: {path.name}') from exc
    if len(raw) > MAX_COMPONENT_BYTES:
        raise ConfigurationError(f'component too large: {path.name}')
    try:
        return json.loads(raw, object_pairs_hook=_reject_duplicates), raw
    except (ValueError, RecursionError) as exc:
        raise ConfigurationError(f'component not valid JSON: {path.name}') from exc


def _text(value, field_name, limit=2000):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ConfigurationError(f'invalid {field_name}')
    return value


def _count(value, field_name, upper=10**12):
    if type(value) is not int or not 0 <= value <= upper:
        raise ConfigurationError(f'invalid {field_name}')
    return value


@dataclass(frozen=True)
class ActionSpec:
    id: str
    effect: str
    grants: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class ServiceSpec:
    id: str
    description: str
    actions: dict[str, ActionSpec]


@dataclass(frozen=True)
class PrincipalSpec:
    id: str
    role: str
    token: str
    description: str = ''


@dataclass(frozen=True)
class ConfigBundle:
    bundle_id: str
    release_hash: str
    components: dict[str, dict]
    content_policy: dict
    signature_feed: dict
    services: dict[str, ServiceSpec]
    budgets: dict
    detectors: dict
    principals: dict[str, PrincipalSpec]
    redacted_principals: dict[str, PrincipalSpec] = field(default_factory=dict)

    def action(self, service_id: str, action_id: str) -> ActionSpec | None:
        service = self.services.get(service_id)
        return service.actions.get(action_id) if service else None

    def detector_profile(self, profile_id: str | None = None) -> dict | None:
        wanted = profile_id or self.detectors['default']
        for profile in self.detectors['profiles']:
            if profile['id'] == wanted:
                return profile
        return None

    def budget_scope(self, scope_id: str | None = None) -> dict | None:
        wanted = scope_id or self.budgets['defaultScope']
        for scope in self.budgets['scopes']:
            if scope['id'] == wanted:
                return scope
        return None

    def as_public_dict(self) -> dict:
        return {
            'bundleId': self.bundle_id,
            'release': self.release_hash,
            'components': self.components,
            'services': sorted(self.services),
            'detectorDefault': self.detectors['default'],
            'budgetScope': self.budgets['defaultScope'],
        }


def _validate_content_policy(policy: dict, component: str):
    """Validate the subset this gateway relies on; content.py revalidates in depth."""
    if not isinstance(policy, dict) or 'allowed_models' not in policy or 'controls' not in policy:
        raise ConfigurationError(f'invalid {component}')


def _parse_services(doc: dict) -> dict[str, ServiceSpec]:
    if not isinstance(doc, dict) or doc.get('version') != 1 or not isinstance(doc.get('services'), list):
        raise ConfigurationError('invalid services manifest')
    if not 1 <= len(doc['services']) <= 50:
        raise ConfigurationError('invalid services manifest')
    services: dict[str, ServiceSpec] = {}
    for service in doc['services']:
        if not isinstance(service, dict) or set(service) != {'id', 'description', 'actions'}:
            raise ConfigurationError('invalid service entry')
        service_id = _text(service['id'], 'service id', 64)
        if service_id in services or not service_id.replace('-', '').isalnum():
            raise ConfigurationError('invalid service id')
        actions: dict[str, ActionSpec] = {}
        raw_actions = service['actions']
        if not isinstance(raw_actions, list) or not 1 <= len(raw_actions) <= 50:
            raise ConfigurationError('invalid action list')
        for action in raw_actions:
            if not isinstance(action, dict) or set(action) != {'id', 'effect', 'grants', 'description'}:
                raise ConfigurationError('invalid action entry')
            action_id = _text(action['id'], 'action id', 64)
            if action['effect'] not in EFFECTS:
                raise ConfigurationError('invalid action effect')
            grants = action['grants']
            if (not isinstance(grants, list) or not grants
                    or any(role not in ROLES for role in grants)):
                raise ConfigurationError('invalid action grants')
            if action_id in actions:
                raise ConfigurationError('duplicate action id')
            actions[action_id] = ActionSpec(action_id, action['effect'], tuple(sorted(set(grants))),
                                            _text(action['description'], 'action description'))
        services[service_id] = ServiceSpec(service_id, _text(service['description'], 'service description'), actions)
    return services


def _parse_budgets(doc: dict) -> dict:
    if not isinstance(doc, dict) or set(doc) != {'version', 'defaultScope', 'scopes', 'reserve', 'estimation'}:
        raise ConfigurationError('invalid budgets manifest')
    if doc['version'] != 1 or not isinstance(doc['scopes'], list) or not 1 <= len(doc['scopes']) <= 20:
        raise ConfigurationError('invalid budgets manifest')
    scope_ids = []
    for scope in doc['scopes']:
        if not isinstance(scope, dict) or set(scope) != {'id', 'period', 'limits', 'description'}:
            raise ConfigurationError('invalid budget scope')
        scope_ids.append(_text(scope['id'], 'budget scope id', 64))
        if scope['period'] != 'utc_day':
            raise ConfigurationError('unsupported budget period')
        limits = scope['limits']
        if not isinstance(limits, dict) or set(limits) != {'tokens', 'costMicro', 'wallClockMs'}:
            raise ConfigurationError('invalid budget limits')
        _count(limits['tokens'], 'limit tokens')
        _count(limits['costMicro'], 'limit cost')
        _count(limits['wallClockMs'], 'limit wall clock')
        _text(scope['description'], 'budget description')
    if len(set(scope_ids)) != len(scope_ids) or doc['defaultScope'] not in scope_ids:
        raise ConfigurationError('invalid default budget scope')
    reserve = doc['reserve']
    expected_reserve = {'semanticTokens', 'outputTokens', 'outputCostMicro', 'targetTokens', 'targetCostMicro',
                        'targetTimeMs', 'outputTimeMs', 'globalDeadlineMs', 'minTargetWindowMs'}
    if not isinstance(reserve, dict) or set(reserve) != expected_reserve:
        raise ConfigurationError('invalid reserve policy')
    for key in expected_reserve:
        _count(reserve[key], f'reserve {key}')
    if reserve['globalDeadlineMs'] <= reserve['outputTimeMs'] or reserve['minTargetWindowMs'] <= 0:
        raise ConfigurationError('invalid reserve policy')
    estimation = doc['estimation']
    if (not isinstance(estimation, dict)
            or set(estimation) != {'bytesPerToken', 'unknownUsageReportedAsZero', 'costMicroPerToken'}
            or type(estimation['bytesPerToken']) is not int or not 1 <= estimation['bytesPerToken'] <= 64):
        raise ConfigurationError('invalid estimation policy')
    if estimation['unknownUsageReportedAsZero'] is not False:
        raise ConfigurationError('unknown usage may never be reported as zero')
    pricing = estimation['costMicroPerToken']
    if (not isinstance(pricing, dict) or len(pricing) > 50
            or any(not isinstance(name, str) or not name.strip() for name in pricing)
            or any(type(rate) is not int or not 0 <= rate <= 10**6 for rate in pricing.values())):
        raise ConfigurationError('invalid cost policy')
    return doc


def _parse_detectors(doc: dict) -> dict:
    if not isinstance(doc, dict) or set(doc) != {'version', 'default', 'profiles'}:
        raise ConfigurationError('invalid detectors manifest')
    if doc['version'] != 1 or not isinstance(doc['profiles'], list) or not 1 <= len(doc['profiles']) <= 20:
        raise ConfigurationError('invalid detectors manifest')
    profile_ids = []
    for profile in doc['profiles']:
        if not isinstance(profile, dict) or profile.get('mode') not in ('baseline', 'provider'):
            raise ConfigurationError('invalid detector profile')
        profile_ids.append(_text(profile['id'], 'detector id', 64))
        _text(profile['detector'], 'detector name', 64)
        _count(profile['instructionVersion'], 'instruction version', 10**6)
        _text(profile['description'], 'detector description')
        if profile['instructionVersion'] < 1:
            raise ConfigurationError('invalid instruction version')
        if profile['mode'] == 'provider':
            expected = {'id', 'mode', 'detector', 'provider', 'model', 'baseUrlEnv', 'apiKeyEnv',
                        'modelEnv', 'timeoutEnv', 'instructionVersion', 'maxResponseBytes', 'description'}
            if set(profile) != expected:
                raise ConfigurationError('invalid provider profile')
            if profile['provider'] != 'openai-compatible':
                raise ConfigurationError('unsupported provider')
            for key in ('model', 'baseUrlEnv', 'apiKeyEnv', 'modelEnv', 'timeoutEnv'):
                _text(profile[key], f'provider {key}', 200)
            _count(profile['maxResponseBytes'], 'max response bytes', 10**7)
        elif set(profile) != {'id', 'mode', 'detector', 'instructionVersion', 'description'}:
            raise ConfigurationError('invalid baseline profile')
    if len(set(profile_ids)) != len(profile_ids) or doc['default'] not in profile_ids:
        raise ConfigurationError('invalid default detector profile')
    return doc


def _parse_principals(doc: dict) -> dict[str, PrincipalSpec]:
    if not isinstance(doc, dict) or set(doc) != {'version', 'principals'} or doc['version'] != 1:
        raise ConfigurationError('invalid principals manifest')
    if not isinstance(doc['principals'], list) or not 1 <= len(doc['principals']) <= 50:
        raise ConfigurationError('invalid principals manifest')
    principals: dict[str, PrincipalSpec] = {}
    tokens = set()
    for entry in doc['principals']:
        if not isinstance(entry, dict) or set(entry) != {'id', 'role', 'token', 'description'}:
            raise ConfigurationError('invalid principal entry')
        principal_id = _text(entry['id'], 'principal id', 64)
        token = _text(entry['token'], 'principal token', 200)
        if entry['role'] not in ROLES or principal_id in principals or token in tokens:
            raise ConfigurationError('invalid principal entry')
        _text(entry['description'], 'principal description')
        principals[principal_id] = PrincipalSpec(principal_id, entry['role'], token,
                                                 entry['description'])
        tokens.add(token)
    return principals


def load_bundle(policy_dir) -> ConfigBundle:
    policy_dir = Path(policy_dir)
    manifest, manifest_raw = _read_json(policy_dir / 'bundle.json')
    if (not isinstance(manifest, dict) or set(manifest) != {'version', 'bundleId', 'components'}
            or manifest['version'] != 1):
        raise ConfigurationError('invalid bundle manifest')
    bundle_id = _text(manifest['bundleId'], 'bundle id', 64)
    components = manifest['components']
    if not isinstance(components, dict) or set(components) != set(REQUIRED_COMPONENTS):
        raise ConfigurationError('invalid bundle components')

    docs, hashes = {}, {}
    for name in REQUIRED_COMPONENTS:
        relative = components[name]
        if not isinstance(relative, str) or Path(relative).name != relative or not relative.endswith('.json'):
            raise ConfigurationError('invalid component reference')
        docs[name], raw = _read_json(policy_dir / relative)
        hashes[name] = {'file': relative, 'sha256': hash_bytes(raw)}

    _validate_content_policy(docs['contentPolicy'], 'content policy')
    feed = docs['signatureFeed']
    if not isinstance(feed, dict) or feed.get('version') != 1 or not isinstance(feed.get('signatures'), list):
        raise ConfigurationError('invalid signature feed')

    services = _parse_services(docs['services'])
    budgets = _parse_budgets(docs['budgets'])
    detectors = _parse_detectors(docs['detectors'])
    principals = _parse_principals(docs['principals'])

    release_hash = hash_bytes(canonical({
        'manifest': hash_bytes(manifest_raw),
        'bundleId': bundle_id,
        'components': hashes,
    }))
    return ConfigBundle(bundle_id, release_hash, hashes, docs['contentPolicy'], feed, services,
                        budgets, detectors, principals)
