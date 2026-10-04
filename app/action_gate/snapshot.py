"""Immutable configuration snapshot.

One invocation pins exactly one snapshot and passes it explicitly to the parser, the grant check,
the content controls and the output controls. Nothing on the hot path re-reads a policy or a
signature feed, so a configuration change cannot split a single call into two different rule sets.

Two hashes are reported and they mean different things:

* ``release_hash`` — the canonical hash of the *validated documents this release executes*.
  It is the identity used for activation, rollback and the rules written to an invocation row.
* ``file_hash`` — the hash of the raw bundle files this snapshot was imported from. It is kept for
  migration and for spotting edits on disk, and it is **not** used to decide what is active,
  because an arbitrary byte edit (whitespace, key order) never changes the executed rules.
  Hashes recorded by earlier releases are never rewritten.

Documents are frozen recursively: a nested dictionary or list cannot be mutated through the
snapshot, which is what ``frozen=True`` on a dataclass alone would not prevent.
"""
from dataclasses import dataclass, field, replace
from hashlib import sha256
import copy
import json
from pathlib import Path
from types import MappingProxyType

from .config_bundle import (ConfigBundle, ConfigurationError, REQUIRED_COMPONENTS,
                            _parse_budgets, _parse_detectors, _parse_principals, _parse_services,
                            _read_json, canonical, load_bundle)
from .content import validate_documents

SCHEMA_VERSION = '2'
BUNDLE_VERSION = '0.2.0'
# Components an operator may change through the policy editor. Adapters, credentials, transport
# identity and arbitrary environment references are deliberately not in this list.
EDITABLE_COMPONENTS = ('contentPolicy', 'signatureFeed', 'services', 'budgets')
COMPONENT_FILES = {
    'contentPolicy': 'policy.json',
    'signatureFeed': 'signatures.json',
    'services': 'services.json',
    'budgets': 'budgets.json',
    'detectors': 'detectors.json',
}


def deep_freeze(value):
    """Recursively freeze a JSON value: mappings become read-only, lists become tuples."""
    if isinstance(value, dict):
        return MappingProxyType({key: deep_freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(deep_freeze(item) for item in value)
    return value


def to_jsonable(value):
    """Return a plain JSON-compatible copy of a frozen value."""
    if isinstance(value, MappingProxyType) or isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_jsonable(item) for item in value]
    return value


def document_hash(document) -> str:
    return sha256(canonical(to_jsonable(document))).hexdigest()


def rules_hash(documents: dict) -> str:
    """Canonical hash of the documents that are actually executed.

    The schema version is part of the hash domain, so a future schema cannot collide with a hash
    recorded by this one.
    """
    return sha256(canonical({
        'schemaVersion': SCHEMA_VERSION,
        'documents': {name: to_jsonable(documents[name]) for name in sorted(documents)},
    })).hexdigest()


@dataclass(frozen=True)
class ConfigSnapshot:
    """A parsed, validated and frozen configuration release."""

    bundle: ConfigBundle
    content_policy: object
    signature_feed: object
    signatures: tuple
    services: object
    budgets: object
    detectors: object
    principals: object
    secrets: dict
    release_hash: str
    file_hash: str
    schema_version: str
    activation_generation: int = 0
    source: str = 'files'
    component_hashes: dict = field(default_factory=dict)

    # -- lookups -------------------------------------------------------------------
    def action(self, service_id: str, action_id: str):
        service = self.services.get(service_id)
        return service.actions.get(action_id) if service else None

    def detector_profile(self, profile_id: str | None = None) -> dict | None:
        wanted = profile_id or self.detectors['default']
        for profile in self.detectors['profiles']:
            if profile['id'] == wanted:
                return dict(profile)
        return None

    def budget_scope(self, scope_id: str | None = None) -> dict | None:
        wanted = scope_id or self.budgets['defaultScope']
        for scope in self.budgets['scopes']:
            if scope['id'] == wanted:
                return to_jsonable(scope)
        return None

    def principal(self, principal_id: str):
        return self.principals.get(principal_id)

    def documents(self) -> dict:
        """Every configured document, as plain JSON.

        The principal document is part of a release: it is required to rebuild the snapshot, and
        every export and API answer strips it before a bundle leaves the service.
        """
        return {
            'contentPolicy': to_jsonable(self.content_policy),
            'signatureFeed': to_jsonable(self.signature_feed),
            'services': to_jsonable(self.services_document()),
            'budgets': to_jsonable(self.budgets),
            'detectors': to_jsonable(self.detectors),
            'principals': {
                'version': 1,
                'principals': [
                    {'id': principal.id, 'role': principal.role, 'token': principal.token,
                     'description': principal.description}
                    for principal in self.principals.values()
                ],
            },
        }

    def services_document(self) -> dict:
        """The services manifest in manifest shape, rebuilt from the parsed specs."""
        return {
            'version': 1,
            'services': [
                {
                    'id': service.id,
                    'description': service.description,
                    'actions': [
                        {'id': action.id, 'effect': action.effect,
                         'grants': list(action.grants), 'description': action.description}
                        for action in service.actions.values()
                    ],
                }
                for service in self.services.values()
            ],
        }

    def public_dict(self) -> dict:
        info = self.bundle.as_public_dict()
        info['release'] = self.release_hash
        info['fileHash'] = self.file_hash
        info['schemaVersion'] = self.schema_version
        info['activationGeneration'] = self.activation_generation
        info['componentHashes'] = dict(self.component_hashes)
        return info

    def content_gate(self, detector=None):
        from .content import ContentGate
        return ContentGate(to_jsonable(self.content_policy), self.signatures,
                           self.component_hashes.get('contentPolicy', ''),
                           self.component_hashes.get('signatureFeed', ''),
                           detector)


def _bundle_from_documents(documents: dict, *, bundle_id: str, file_hash: str = '',
                           secrets: dict | None = None) -> ConfigSnapshot:
    """Validate parsed documents once and freeze the result.

    Every path into the gate - file bootstrap, JSON import, database read - goes through here, so
    an imported release is checked by exactly the same code as a file on disk.
    """
    missing = [name for name in REQUIRED_COMPONENTS if name not in documents]
    if missing:
        raise ConfigurationError('missing component: ' + ', '.join(sorted(missing)))
    unknown = [name for name in documents if name not in REQUIRED_COMPONENTS]
    if unknown:
        raise ConfigurationError('unknown component: ' + ', '.join(sorted(unknown)))
    for name in REQUIRED_COMPONENTS:
        if not isinstance(documents[name], (dict, MappingProxyType)):
            raise ConfigurationError(f'invalid {name}')

    policy = to_jsonable(documents['contentPolicy'])
    feed = to_jsonable(documents['signatureFeed'])
    signatures = validate_documents(policy, feed)
    services = _parse_services(to_jsonable(documents['services']))
    budgets = _parse_budgets(to_jsonable(documents['budgets']))
    detectors = _parse_detectors(to_jsonable(documents['detectors']))
    principals = _parse_principals(to_jsonable(documents['principals']))

    frozen_documents = {name: deep_freeze(to_jsonable(documents[name]))
                        for name in REQUIRED_COMPONENTS}
    component_hashes = {name: document_hash(frozen_documents[name]) for name in REQUIRED_COMPONENTS}
    release = rules_hash(frozen_documents)
    bundle = ConfigBundle(
        bundle_id=bundle_id, release_hash=release, components=dict(component_hashes),
        content_policy=frozen_documents['contentPolicy'],
        signature_feed=frozen_documents['signatureFeed'], services=services, budgets=budgets,
        detectors=detectors, principals=principals)
    return ConfigSnapshot(
        bundle=bundle,
        content_policy=frozen_documents['contentPolicy'],
        signature_feed=frozen_documents['signatureFeed'],
        signatures=signatures,
        services=services,
        budgets=budgets,
        detectors=detectors,
        principals=principals,
        secrets=dict(secrets or {}),
        release_hash=release,
        file_hash=file_hash or release,
        schema_version=SCHEMA_VERSION,
        component_hashes=component_hashes,
    )


def snapshot_from_documents(documents: dict, *, bundle_id: str = 'imported', file_hash: str = '',
                            secrets: dict | None = None) -> ConfigSnapshot:
    """Build a snapshot from already-parsed documents (import path and tests)."""
    return _bundle_from_documents(copy.deepcopy(documents), bundle_id=bundle_id,
                                  file_hash=file_hash, secrets=secrets)


def snapshot_from_bundle(bundle: ConfigBundle, *, source: str = 'files',
                         activation_generation: int = 0, secrets: dict | None = None,
                         documents: dict | None = None) -> ConfigSnapshot:
    """Re-validate a bundle that was loaded from files and pin the canonical hashes."""
    documents = documents or {
        'contentPolicy': to_jsonable(bundle.content_policy),
        'signatureFeed': to_jsonable(bundle.signature_feed),
        'services': _services_to_document(bundle),
        'budgets': to_jsonable(bundle.budgets),
        'detectors': to_jsonable(bundle.detectors),
        'principals': to_jsonable(bundle._principals_document()),
    }
    snapshot = _bundle_from_documents(documents, bundle_id=bundle.bundle_id,
                                      file_hash=bundle.release_hash, secrets=secrets)
    return replace(snapshot, source=source, activation_generation=activation_generation)


def _services_to_document(bundle: ConfigBundle) -> dict:
    return {
        'version': 1,
        'services': [
            {
                'id': service.id,
                'description': service.description,
                'actions': [
                    {'id': action.id, 'effect': action.effect, 'grants': list(action.grants),
                     'description': action.description}
                    for action in service.actions.values()
                ],
            }
            for service in bundle.services.values()
        ],
    }


class FileConfigSource:
    """Reads the frozen policy directory once and pins the result.

    Files are a bootstrap and import format, never a second live configuration: after the first
    start the active release lives in the database and this source is only consulted to seed it.
    """

    name = 'files'

    def __init__(self, policy_dir):
        self.policy_dir = Path(policy_dir)
        self._snapshot: ConfigSnapshot | None = None

    def load(self, *, force: bool = False) -> ConfigSnapshot:
        if self._snapshot is not None and not force:
            return self._snapshot
        bundle = load_bundle(self.policy_dir)
        documents = {
            'contentPolicy': _read_component(self.policy_dir, bundle, 'contentPolicy'),
            'signatureFeed': _read_component(self.policy_dir, bundle, 'signatureFeed'),
            'services': _read_component(self.policy_dir, bundle, 'services'),
            'budgets': _read_component(self.policy_dir, bundle, 'budgets'),
            'detectors': _read_component(self.policy_dir, bundle, 'detectors'),
            'principals': _read_component(self.policy_dir, bundle, 'principals'),
        }
        secrets = {principal.id: principal.token for principal in bundle.principals.values()}
        snapshot = _bundle_from_documents(documents, bundle_id=bundle.bundle_id,
                                          file_hash=bundle.release_hash, secrets=secrets)
        self._snapshot = replace(snapshot, source=self.name)
        return self._snapshot

    def documents(self) -> dict:
        return self.load().documents()


def _read_component(policy_dir: Path, bundle: ConfigBundle, name: str) -> dict:
    path = Path(policy_dir) / bundle.components[name]['file']
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ConfigurationError(f'component unreadable: {path.name}') from exc
    document, _ = _read_json(path)
    return document


def detector_identity(detector) -> dict:
    """Resolved identity of a detector instance, for observation-cache keys and traces."""
    if hasattr(detector, 'cache_identity'):
        return dict(detector.cache_identity())
    return {'model_id': '{}:{}'.format(type(detector).__name__,
                                       getattr(detector, 'detector', '?')),
            'endpoint_hash': 'unreported', 'detector_version': 0}


def resolved_profile(snapshot: ConfigSnapshot, profile_id: str, environ) -> dict:
    """Resolve a detector profile once, before any work starts.

    The resolved identity - endpoint, model and instruction version - is what a cache key and a
    compare-freshness check use, not the static profile fields.
    """
    from .detectors import build_detector
    profile = snapshot.detector_profile(profile_id)
    if profile is None:
        raise ConfigurationError('unknown detector profile')
    detector = build_detector(profile, snapshot.budgets['estimation']['bytesPerToken'], environ)
    return {'profile': profile, 'detector': detector, 'identity': detector_identity(detector)}


def cache_model_id(identity: dict) -> str:
    return '{}@{}#v{}'.format(identity['model_id'], identity['endpoint_hash'],
                              identity['detector_version'])
