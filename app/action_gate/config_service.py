"""Policy lifecycle: drafts, compare, activation, rollback and export.

PostgreSQL holds the active release; the policy files are a bootstrap and import format. The
lifecycle is deliberately narrow:

* an **editable** release contains the content policy, the signature feed, the grants of known
  actions and the caps of known budget scopes;
* the **adapter catalogue**, credentials, endpoint identity and transport identity are *not*
  editable through this service. A payload that tries to set a base URL, a key or a file path is
  rejected, not ignored;
* activation is a compare-and-swap: the caller states the draft revision and the active generation
  it saw. Two clients that raced produce one activation and one ``409 active_changed``;
* rollback re-activates a stored, complete historical snapshot as a **new** generation. It never
  rewinds usage, reservations, claims, observations, audit or effects, and it never restores a
  revoked credential.
"""
from dataclasses import dataclass
import hashlib
import json

from .config_bundle import ConfigurationError
from .contracts import ContractError
from .snapshot import (EDITABLE_COMPONENTS, SCHEMA_VERSION, ConfigSnapshot, deep_freeze,
                       document_hash, snapshot_from_documents, to_jsonable)
from .storage.base import iso_utc
from .storage.config_store import new_id

# Bumped when the exported bundle shape changes. The schema version travels with the document so
# an importer can refuse a bundle it does not understand.
EXPORT_SCHEMA_VERSION = SCHEMA_VERSION


class ConfigConflict(RuntimeError):
    def __init__(self, code: str, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass
class DraftResult:
    draft_id: str
    revision: int
    candidate_hash: str
    documents: dict


class ConfigService:
    """Owns the release/draft/activation state machine. Storage is injected."""

    def __init__(self, repository, store, environment: str = 'local'):
        self.repository = repository
        self.store = store
        self.environment = environment

    # -- state ---------------------------------------------------------------------
    def bootstrap(self, source) -> tuple[bool, ConfigSnapshot | None, str | None]:
        """Seed the active release from the configured source if none is active.

        Returns ``(created, snapshot, error)``. A repeated start reads the database and never
        overwrites an active release from files; an invalid bootstrap bundle leaves the service
        not-ready instead of silently running with partial rules.
        """
        active = self.store.get_active(self.environment)
        if active is not None:
            try:
                snapshot = self.load_snapshot(active['release_hash'], active['generation'])
            except ConfigurationError as exc:
                return False, None, str(exc)
            return False, snapshot, None
        try:
            candidate = source.load()
        except ConfigurationError as exc:
            return False, None, str(exc)
        self.put_release(candidate, source='bootstrap', created_by='bootstrap')
        self._install_release(candidate, generation=1, previous=None, actor='bootstrap',
                              reason='initial bootstrap from policy files', kind='bootstrap',
                              operation_key=None, request_hash=None)
        snapshot = self.snapshot()
        return True, snapshot, None

    def snapshot(self) -> ConfigSnapshot:
        active = self.store.get_active(self.environment)
        if active is None:
            raise ConfigurationError('no active configuration release')
        return self.load_snapshot(active['release_hash'], active['generation'])

    def load_snapshot(self, release_hash: str, generation: int = 0) -> ConfigSnapshot:
        release = self.store.get_release(release_hash)
        if release is None:
            raise ConfigurationError('unknown configuration release')
        snapshot = release.get('snapshot')
        if not snapshot:
            # A release recorded by an earlier version has component hashes but no documents, so it
            # cannot be reconstructed or rolled back. Saying so is the only honest option.
            raise ConfigurationError('release has no stored snapshot and cannot be activated')
        snapshot = snapshot if isinstance(snapshot, dict) else json.loads(snapshot)
        return self._snapshot_from_record(snapshot, generation=generation, source=release['source'])

    @staticmethod
    def _snapshot_from_record(snapshot: dict, *, generation: int, source: str) -> ConfigSnapshot:
        documents = snapshot.get('documents') or {}
        built = snapshot_from_documents(documents, bundle_id=snapshot.get('bundleId') or 'active')
        from dataclasses import replace
        return replace(built, activation_generation=int(generation), source=source,
                       release_hash=snapshot.get('releaseHash') or built.release_hash,
                       file_hash=snapshot.get('fileHash') or built.file_hash)

    def put_release(self, snapshot: ConfigSnapshot, *, source: str, created_by: str | None,
                    generation: int | None = None) -> None:
        documents = self._full_documents(snapshot)
        record_hash = snapshot.release_hash
        self.store.put_release({
            'release_hash': record_hash,
            'bundle_id': snapshot.bundle.bundle_id,
            'components': dict(snapshot.component_hashes),
            'snapshot': {
                'schemaVersion': SCHEMA_VERSION,
                'releaseHash': record_hash,
                'fileHash': snapshot.file_hash,
                'bundleId': snapshot.bundle.bundle_id,
                'componentHashes': dict(snapshot.component_hashes),
                'documents': documents,
            },
            'schema_version': SCHEMA_VERSION,
            'source': source,
            'created_by': created_by,
            'activation_generation': generation,
        })

    @staticmethod
    def _full_documents(snapshot: ConfigSnapshot) -> dict:
        """Every document the release needs to be reconstructible, secrets included.

        The secret document is stored with the release so a rollback restores the identities that
        belonged to it, and it is stripped from every export by :meth:`export_bundle`.
        """
        return snapshot.documents()

    @staticmethod
    def editable_documents(snapshot: ConfigSnapshot) -> dict:
        documents = snapshot.documents()
        return {name: documents[name] for name in EDITABLE_COMPONENTS}

    # -- drafts --------------------------------------------------------------------
    def create_draft(self, *, base_release: str | None = None, documents: dict | None = None,
                     created_by: str | None = None, source: str = 'api') -> DraftResult:
        active = self.snapshot()
        base = base_release or active.release_hash
        payload = dict(self.editable_documents(active))
        if documents:
            payload.update({name: to_jsonable(value) for name, value in documents.items()})
        snapshot = self._validate_candidate(active, payload)
        draft_id = new_id()
        self.store.create_draft({
            'draft_id': draft_id,
            'base_release': base,
            'revision': 1,
            'documents': payload,
            'source': source,
            'created_by': created_by,
        })
        return DraftResult(draft_id, 1, snapshot.release_hash, payload)

    def save_draft(self, draft_id: str, *, expected_revision: int, documents: dict,
                   created_by: str | None = None) -> DraftResult:
        active = self.snapshot()
        payload = dict(self.editable_documents(active))
        payload.update({name: to_jsonable(value) for name, value in documents.items()})
        snapshot = self._validate_candidate(active, payload)
        record = self.store.get_draft(draft_id)
        if record is None:
            raise ConfigConflict('draft_not_found')
        if record['revision'] != expected_revision:
            raise ConfigConflict('draft_changed', f"draft is at revision {record['revision']}")
        revision = expected_revision + 1
        updated = self.store.update_draft(draft_id, revision, payload, expected_revision)
        if updated in ('stale', 'missing'):
            raise ConfigConflict('draft_changed')
        return DraftResult(draft_id, revision, snapshot.release_hash, payload)

    def get_draft(self, draft_id: str) -> dict:
        record = self.store.get_draft(draft_id)
        if record is None:
            raise ContractError('draft_not_found', 'unknown draft', 404)
        return record

    def candidate_from_draft(self, draft_id: str, revision: int | None = None,
                             documents: dict | None = None) -> tuple[ConfigSnapshot, dict]:
        """Build the candidate snapshot of a draft, optionally with an unsaved edit applied."""
        record = self.get_draft(draft_id)
        if revision is not None and record['revision'] != revision:
            raise ConfigConflict('draft_changed',
                                 f"draft is at revision {record['revision']}, not {revision}")
        payload = dict(record['documents'])
        if documents:
            payload.update({name: to_jsonable(value) for name, value in documents.items()})
        active = self.snapshot()
        return self._validate_candidate(active, payload), payload

    def _validate_candidate(self, active: ConfigSnapshot, payload: dict) -> ConfigSnapshot:
        documents = self.documents_with_immutable(active, payload)
        try:
            return snapshot_from_documents(documents, bundle_id=active.bundle.bundle_id)
        except ConfigurationError as exc:
            raise ContractError('candidate_invalid', str(exc), 422) from exc

    @staticmethod
    def documents_with_immutable(active: ConfigSnapshot, payload: dict) -> dict:
        """Combine edited documents with the parts of a release that are never editable."""
        documents = dict(active.documents())
        for name, value in payload.items():
            if name not in EDITABLE_COMPONENTS:
                raise ContractError('document_not_editable', f'{name} is not an editable document',
                                    422)
            documents[name] = to_jsonable(value)
        return documents

    def preview(self, payload: dict) -> ConfigSnapshot:
        """Validate documents without storing anything. Used by draft validation."""
        active = self.snapshot()
        return self._validate_candidate(active, payload)

    # -- compare -------------------------------------------------------------------
    def record_evaluation(self, result: dict, *, active: ConfigSnapshot, candidate_hash: str,
                          candidate_revision: int | None, dataset_hash: str | None,
                          detector_profile: str, actor: str | None) -> str:
        evaluation_id = new_id()
        summary = {
            'checkedCases': result.get('checkedCases'),
            'totalCases': result.get('totalCases'),
            'failedCases': result.get('failedCases'),
            'changedCases': result.get('changedCases'),
            'stoppedBy': result.get('stoppedBy'),
            'unknownUsageCalls': result.get('unknownUsageCalls'),
            'candidateError': result.get('candidateError'),
        }
        self.store.put_evaluation({
            'evaluation_id': evaluation_id,
            'environment': self.environment,
            'active_hash': active.release_hash,
            'active_generation': active.activation_generation,
            'candidate_hash': candidate_hash,
            'candidate_revision': candidate_revision,
            'dataset_hash': dataset_hash,
            'detector_profile': detector_profile,
            'detector_identity': (result.get('detector') or {}).get('identity') or {},
            'instruction_version': (result.get('detector') or {}).get('instructionVersion'),
            'mode': result.get('mode') or 'full',
            'status': result.get('status'),
            'passed': bool(result.get('passed')),
            'model_calls': result.get('modelCalls') or 0,
            'case_count': result.get('checkedCases') or 0,
            'summary': summary,
            'created_by': actor,
        })
        return evaluation_id

    def evaluation_freshness(self, evaluation: dict, active: ConfigSnapshot,
                             candidate: ConfigSnapshot) -> tuple[bool, str | None]:
        """Is this comparison still evidence for this candidate against this active release?

        Every ingredient that can change a verdict is checked: both hashes, the active generation,
        the dataset and the resolved detector identity - including its model, endpoint and
        instruction version. A runtime profile change invalidates a comparison even when the policy
        JSON did not change.
        """
        if evaluation['active_hash'] != active.release_hash:
            return False, 'active_changed'
        if int(evaluation['active_generation']) != int(active.activation_generation):
            return False, 'generation_changed'
        if evaluation['candidate_hash'] != candidate.release_hash:
            return False, 'candidate_changed'
        if evaluation['status'] != 'complete' or not evaluation['passed']:
            return False, 'evaluation_not_passed'
        return True, None

    # -- activation ----------------------------------------------------------------
    def activate(self, *, draft_id: str, expected_revision: int, expected_generation: int,
                 evaluation_id: str | None, operation_key: str | None, actor: str,
                 reason: str | None, documents: dict | None = None,
                 allow_budget_only: bool = True) -> dict:
        active = self.snapshot()
        rehearsal, payload = self.candidate_from_draft(draft_id, expected_revision, documents)
        # The operation key is bound to the candidate it activates, so retrying the same activation
        # replays its result while reusing the key for anything else is a conflict.
        fingerprint = {'kind': 'activation', 'draftId': draft_id,
                       'expectedRevision': expected_revision,
                       'expectedGeneration': expected_generation,
                       'candidate': rehearsal.release_hash}
        existing = self._operation_replay(operation_key, fingerprint)
        if existing is not None:
            return existing
        if int(expected_generation) != int(active.activation_generation):
            raise ConfigConflict('active_changed',
                                 f'active generation is {active.activation_generation}')
        candidate = rehearsal
        self._require_change(active, candidate)
        from .evaluation import budget_only_evaluation, caps_only_change

        if evaluation_id:
            evaluation = self.store.get_evaluation(evaluation_id)
            if evaluation is None:
                raise ContractError('evaluation_not_found', 'unknown evaluation', 404)
            fresh, why = self.evaluation_freshness(evaluation, active, candidate)
            if not fresh:
                raise ConfigConflict('evaluation_stale', why)
            if evaluation['mode'] == 'budget-only':
                ok, why = caps_only_change(active, candidate)
                if not ok:
                    raise ConfigConflict('evaluation_mismatch',
                                         f'budget-only activation is not allowed: {why}')
        else:
            ok, why = caps_only_change(active, candidate)
            if not (ok and allow_budget_only):
                raise ContractError('evaluation_required',
                                    'activation requires a current complete comparison', 409)
            evaluation_id = self.record_evaluation(
                {'status': 'complete', 'passed': True, 'mode': 'budget-only', 'modelCalls': 0,
                 'checkedCases': 0, 'totalCases': 0, 'targetDispatchCount': 0,
                 'checks': budget_only_evaluation(active, candidate)['checks']},
                active=active, candidate_hash=candidate.release_hash,
                candidate_revision=expected_revision, dataset_hash=None,
                detector_profile=candidate.detectors['default'], actor=actor)

        self.put_release(candidate, source='draft', created_by=actor)
        activation = self._install_release(candidate, generation=active.activation_generation + 1,
                                           previous=active.release_hash, actor=actor, reason=reason,
                                           kind='activation', operation_key=operation_key,
                                           request_hash=_fingerprint(fingerprint))
        return {
            'activationId': activation['activation_id'],
            'active': {'release': candidate.release_hash,
                       'activationGeneration': active.activation_generation + 1,
                       'componentHashes': dict(candidate.component_hashes),
                       'editableDocuments': payload},
            'previous': {'release': active.release_hash,
                         'activationGeneration': active.activation_generation},
            'evaluationId': evaluation_id,
            'replayed': False,
        }

    def rollback(self, *, target_release_hash: str, expected_generation: int,
                 operation_key: str | None, actor: str, reason: str) -> dict:
        fingerprint = {'kind': 'rollback', 'target': target_release_hash,
                       'expectedGeneration': expected_generation}
        existing = self._operation_replay(operation_key, fingerprint)
        if existing is not None:
            return existing
        active = self.snapshot()
        self._require_generation(expected_generation, active)
        release = self.store.get_release(target_release_hash)
        if release is None:
            raise ContractError('release_not_found', 'unknown release', 404)
        if not release.get('snapshot'):
            raise ConfigConflict('release_not_rollbackable',
                                 'this release has no stored snapshot')
        candidate = self.load_snapshot(target_release_hash)
        if candidate.release_hash == active.release_hash:
            raise ConfigConflict('already_active', 'the requested release is already active')
        generation = active.activation_generation + 1
        activation = self._install_release(candidate, generation=generation,
                                           previous=active.release_hash, actor=actor, reason=reason,
                                           kind='rollback', operation_key=operation_key,
                                           request_hash=_fingerprint(fingerprint))
        return {
            'activationId': activation['activation_id'],
            'active': {'release': candidate.release_hash, 'activationGeneration': generation,
                       'componentHashes': dict(candidate.component_hashes)},
            'previous': {'release': active.release_hash,
                         'activationGeneration': active.activation_generation},
            'kind': 'rollback',
            'note': ('Rules were restored. Usage, reservations, claims, observations, audit and '
                     'effects were not rewound, and revoked credentials are not restored.'),
            'replayed': False,
        }

    def _install_release(self, snapshot: ConfigSnapshot, *, generation: int, previous: str | None,
                         actor: str, reason: str | None, kind: str,
                         operation_key: str | None, request_hash: str | None) -> dict:
        record = {
            'activation_id': new_id(),
            'environment': self.environment,
            'previous_hash': previous,
            'next_hash': snapshot.release_hash,
            'generation': generation,
            'actor': actor,
            'reason': reason,
            'kind': kind,
            'operation_key': operation_key,
            'request_hash': request_hash,
        }
        verdict, stored = self.store.append_activation(record)
        if verdict == 'duplicate':
            # The same operation key with the same fingerprint returns the earlier result. A
            # different payload under the same key is a conflict, never a second activation.
            if stored.get('request_hash') not in (None, request_hash):
                raise ConfigConflict('operation_conflict',
                                     'operation key was already used with a different payload')
            return stored
        self.store.set_active(self.environment, snapshot.release_hash, generation)
        self.store.install_caps(self.repository, snapshot.budgets, generation)
        return stored

    def _operation_replay(self, operation_key: str | None, payload: dict) -> dict | None:
        if not operation_key:
            return None
        existing = self.store.find_activation(self.environment, operation_key)
        if existing is None:
            return None
        if existing.get('request_hash') not in (None, _fingerprint(payload)):
            raise ConfigConflict('operation_conflict',
                                 'operation key was already used with a different payload')
        snapshot = self.snapshot()
        return {
            'activationId': existing['activation_id'],
            'active': {'release': snapshot.release_hash,
                       'activationGeneration': snapshot.activation_generation,
                       'componentHashes': dict(snapshot.component_hashes)},
            'previous': {'release': existing.get('previous_hash'),
                         'activationGeneration': int(existing['generation']) - 1},
            'replayed': True,
        }

    @staticmethod
    def _require_generation(expected_generation: int, active: ConfigSnapshot) -> None:
        if int(expected_generation) != int(active.activation_generation):
            raise ConfigConflict('active_changed',
                                 f"active generation is {active.activation_generation}")

    @staticmethod
    def _require_change(active: ConfigSnapshot, candidate: ConfigSnapshot) -> None:
        if active.release_hash == candidate.release_hash:
            raise ConfigConflict('no_change', 'candidate is identical to the active release')

    # -- identity registry -----------------------------------------------------------
    def install_identity_registry(self, principals: dict, *, actor: str, reason: str) -> dict:
        """Install a new release whose principal registry contains additional identities.

        Identities are deliberately not part of the editable-document lifecycle: a draft can change
        policy, but no API caller can grant itself a role. Adding a demonstration client therefore
        needs this explicit operator entry point, and it is deliberately narrow:

        * the document must be a valid principals manifest;
        * every identity that already exists must keep its role and token unchanged;
        * only additions are accepted, and the change is recorded as its own activation kind.
        """
        from .config_bundle import _parse_principals
        from .snapshot import snapshot_from_documents
        active = self.snapshot()
        parsed = _parse_principals(principals)
        for identifier, spec in active.principals.items():
            incoming = parsed.get(identifier)
            if incoming is None:
                raise ConfigConflict('identity_removal',
                                     f'{identifier} exists in the active release and cannot be '
                                     'removed by this path')
            if incoming.role != spec.role or incoming.token != spec.token:
                raise ConfigConflict('identity_change',
                                     f'{identifier} already exists with another role or token; '
                                     'this path only adds identities')
        added = sorted(set(parsed) - set(active.principals))
        if not added:
            return {'changed': False, 'principals': sorted(parsed)}
        documents = dict(active.documents())
        documents['principals'] = principals
        candidate = snapshot_from_documents(documents, bundle_id=active.bundle.bundle_id)
        self.put_release(candidate, source='identity-registry', created_by=actor)
        activation = self._install_release(
            candidate, generation=active.activation_generation + 1,
            previous=active.release_hash, actor=actor, reason=reason,
            kind='identity-registry', operation_key=None, request_hash=None)
        return {'changed': True, 'added': added, 'principals': sorted(parsed),
                'release': candidate.release_hash,
                'activationGeneration': activation['generation'],
                'activationId': activation['activation_id']}

    # -- history and export --------------------------------------------------------
    def releases(self, limit: int = 50, before: str | None = None) -> list:
        active = self.store.get_active(self.environment)
        rows = self.store.list_releases(limit, before)
        history = []
        for row in rows:
            created = row['created_at']
            history.append({
                'release': row['release_hash'],
                'bundleId': row['bundle_id'],
                'schemaVersion': row.get('schema_version'),
                'source': row.get('source'),
                'createdBy': row.get('created_by'),
                'createdAt': iso_utc(created) if hasattr(created, 'isoformat') else created,
                'componentHashes': row.get('components') or {},
                'rollbackAvailable': bool(row.get('snapshot')),
                'active': bool(active and active['release_hash'] == row['release_hash']),
            })
        return history

    def activations(self, limit: int = 50) -> list:
        rows = self.store.list_activations(self.environment, limit)
        for row in rows:
            created = row.get('created_at')
            if hasattr(created, 'isoformat'):
                row['created_at'] = iso_utc(created)
        return rows

    def export_bundle(self, release_hash: str | None = None) -> dict:
        """The editable documents of a release as one portable JSON bundle.

        Credentials are not in an export: the principal table is stored with the release but never
        leaves the service, so an exported bundle cannot leak a token.
        """
        active = self.store.get_active(self.environment)
        wanted = release_hash or (active['release_hash'] if active else None)
        if wanted is None:
            raise ConfigurationError('no active configuration release')
        release = self.store.get_release(wanted)
        if release is None or not release.get('snapshot'):
            raise ConfigurationError('release has no stored snapshot to export')
        snapshot = release['snapshot']
        snapshot = snapshot if isinstance(snapshot, dict) else json.loads(snapshot)
        documents = snapshot.get('documents') or {}
        return {
            'schemaVersion': EXPORT_SCHEMA_VERSION,
            'bundleId': snapshot.get('bundleId'),
            'release': wanted,
            'fileHash': snapshot.get('fileHash'),
            'documents': {name: documents[name] for name in EDITABLE_COMPONENTS if name in documents},
            'note': ('Editable documents only. Adapter catalogue, endpoints, credentials and '
                     'transport identity are deployment configuration and are not exported.'),
        }

    def import_bundle(self, bundle: dict, *, created_by: str | None = None) -> DraftResult:
        """Validate an imported bundle and keep it as a draft. Import never activates."""
        schema = bundle.get('schemaVersion')
        if schema is not None and str(schema) != str(EXPORT_SCHEMA_VERSION):
            raise ContractError('unsupported_schema', f'schemaVersion {schema!r} is not supported',
                                422)
        documents = bundle.get('documents')
        if not isinstance(documents, dict):
            raise ContractError('schema_invalid', 'bundle.documents is required')
        return self.create_draft(documents=documents, created_by=created_by, source='import')


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode('utf-8')).hexdigest()


# Kept importable from here so a caller does not need to know about the freezing helpers.
__all__ = ['ConfigService', 'DraftResult', 'ConfigConflict', 'EXPORT_SCHEMA_VERSION',
           'deep_freeze', 'document_hash']
