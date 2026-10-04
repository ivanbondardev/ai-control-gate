"""Request contracts for the protected invocation API.

Identity is transport-derived, never request-derived: a caller cannot select a role by adding a
field to the body. Unknown fields are rejected instead of ignored so that a silent typo cannot
change the meaning of a call.

Every parser takes a :class:`~action_gate.snapshot.ConfigSnapshot` rather than reading a file, so
one request is validated against exactly the release it will execute.
"""
from dataclasses import dataclass, field
import re

MAX_BODY_BYTES = 65536
MAX_IDEMPOTENCY_KEY = 200
MAX_CASES = 50
MAX_DRAFT_BYTES = 1_000_000
IDENTITY_FIELDS = ('principal', 'principalId', 'principal_id', 'role', 'roles', 'token',
                   'grants', 'isOperator', 'operator')
DOCUMENT_ID = re.compile(r'^[a-z0-9][a-z0-9._-]{0,63}$')
CASE_ID = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$')
FAMILY = re.compile(r'^[a-z0-9][a-z0-9._-]{0,47}$')
REVISION = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$')
HASH = re.compile(r'^[0-9a-f]{8,64}$')
DIRECTIONS = ('input', 'output')
DECISIONS = ('allow', 'redact', 'block')
DISCLOSURES = ('full', 'redacted', 'withheld')
EDITABLE_DOCUMENTS = ('contentPolicy', 'signatureFeed', 'services', 'budgets')
CANDIDATE_MODES = ('full', 'budget-only')
# Fields a caller may never inject through a configuration payload: they carry credentials or
# redirect where a call goes, and neither is an operator-editable policy decision.
FORBIDDEN_CONFIG_FIELDS = frozenset({
    'baseUrl', 'base_url', 'baseUrlEnv', 'apiKey', 'api_key', 'apiKeyEnv', 'token', 'tokenEnv',
    'credentials', 'password', 'secret', 'endpoint', 'url', 'filePath', 'path', 'principalToken',
})


class ContractError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class InvocationRequest:
    idempotency_key: str
    service: str
    action: str
    document_id: str | None
    text: str | None
    model: str
    detector_profile: str | None
    budget_scope: str | None
    dry_run: bool
    timeout_ms: int | None
    raw: dict = field(default_factory=dict)

    def as_public_dict(self) -> dict:
        return {
            'idempotencyKey': self.idempotency_key,
            'service': self.service,
            'action': self.action,
            'documentId': self.document_id,
            'model': self.model,
            'detectorProfile': self.detector_profile,
            'budgetScope': self.budget_scope,
            'dryRun': self.dry_run,
            'textBytes': len(self.text.encode('utf-8')) if self.text is not None else 0,
        }


def _reject_identity(body: dict) -> None:
    for key in body:
        if key in IDENTITY_FIELDS:
            raise ContractError('identity_in_body',
                                f'identity field {key!r} is not accepted; identity comes from the transport',
                                422)


def _required_text(body: dict, key: str, limit=MAX_IDEMPOTENCY_KEY) -> str:
    value = body.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContractError('schema_invalid', f'{key} must be a non-empty string')
    value = value.strip()
    if len(value) > limit:
        raise ContractError('schema_invalid', f'{key} exceeds {limit} characters')
    return value


def _optional_text(body: dict, key: str, limit: int, pattern=None):
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContractError('schema_invalid', f'{key} must be a non-empty string')
    value = value.strip()
    if len(value) > limit or (pattern is not None and not pattern.match(value)):
        raise ContractError('schema_invalid', f'{key} has an unsupported format')
    return value


def _document_id(body_input: dict, required: bool) -> str | None:
    value = body_input.get('documentId')
    if value is None:
        if required:
            raise ContractError('schema_invalid', 'input.documentId is required for this action')
        return None
    if not isinstance(value, str) or not DOCUMENT_ID.match(value):
        raise ContractError('schema_invalid', 'input.documentId has an unsupported format')
    return value


def parse_invocation(body, snapshot) -> InvocationRequest:
    if not isinstance(body, dict):
        raise ContractError('schema_invalid', 'request body must be a JSON object')
    _reject_identity(body)
    allowed = {'idempotencyKey', 'service', 'action', 'input', 'model', 'detectorProfile',
               'budgetScope', 'dryRun', 'timeoutMs'}
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise ContractError('schema_invalid', f'unknown request fields: {", ".join(unknown)}')

    idempotency_key = _required_text(body, 'idempotencyKey')
    service_id = _required_text(body, 'service', 64)
    action_id = _required_text(body, 'action', 64)
    action = snapshot.action(service_id, action_id)
    if action is None:
        if service_id not in snapshot.services:
            raise ContractError('unknown_service', f'unknown service {service_id!r}', 404)
        raise ContractError('unknown_action', f'unknown action {action_id!r}', 404)

    raw_input = body.get('input', {})
    if not isinstance(raw_input, dict):
        raise ContractError('schema_invalid', 'input must be a JSON object')
    unknown_input = sorted(set(raw_input) - {'documentId', 'text'})
    if unknown_input:
        raise ContractError('schema_invalid', f'unknown input fields: {", ".join(unknown_input)}')
    text = raw_input.get('text')
    if text is not None and not isinstance(text, str):
        raise ContractError('schema_invalid', 'input.text must be a string')
    document_id = _document_id(raw_input, required=True)
    if action_id == 'documents.comment' and not (text or '').strip():
        raise ContractError('schema_invalid', 'input.text is required for this action')

    model = body.get('model', 'demo-local')
    if not isinstance(model, str) or not model.strip():
        raise ContractError('schema_invalid', 'model must be a non-empty string')
    model = model.strip()

    detector_profile = body.get('detectorProfile')
    if detector_profile is not None:
        if not isinstance(detector_profile, str) or snapshot.detector_profile(detector_profile) is None:
            raise ContractError('schema_invalid', 'unknown detectorProfile')
    budget_scope = body.get('budgetScope')
    if budget_scope is not None:
        if not isinstance(budget_scope, str) or snapshot.budget_scope(budget_scope) is None:
            raise ContractError('schema_invalid', 'unknown budgetScope')

    dry_run = body.get('dryRun', False)
    if not isinstance(dry_run, bool):
        raise ContractError('schema_invalid', 'dryRun must be a boolean')
    timeout_ms = body.get('timeoutMs')
    if timeout_ms is not None:
        if type(timeout_ms) is not int or not 50 <= timeout_ms <= 60000:
            raise ContractError('schema_invalid', 'timeoutMs must be an integer between 50 and 60000')

    return InvocationRequest(idempotency_key, service_id, action_id, document_id, text, model,
                             detector_profile, budget_scope, dry_run, timeout_ms,
                             {'service': service_id, 'action': action_id, 'documentId': document_id,
                              'text': text, 'model': model})


def parse_evaluation(body):
    """Parse a compare request. The runner binds it to the pinned active snapshot."""
    from .evaluation import EvaluationCase, EvaluationRequest

    if not isinstance(body, dict):
        raise ContractError('schema_invalid', 'request body must be a JSON object')
    allowed = {'cases', 'detectorProfile', 'candidate', 'actorRole', 'expectedRevision',
               'expectedActiveGeneration'}
    unknown = sorted(set(body) - allowed)
    if unknown:
        raise ContractError('schema_invalid', f'unknown request fields: {", ".join(unknown)}')
    actor_role = body.get('actorRole', 'operator')
    if actor_role not in ('agent', 'operator'):
        raise ContractError('schema_invalid', 'actorRole must be agent or operator')

    raw_cases = body.get('cases')
    if not isinstance(raw_cases, list) or not 1 <= len(raw_cases) <= MAX_CASES:
        raise ContractError('schema_invalid', f'cases must contain between 1 and {MAX_CASES} entries')
    cases, seen = [], set()
    for entry in raw_cases:
        if not isinstance(entry, dict):
            raise ContractError('schema_invalid', 'each case must be a JSON object')
        unknown_case = sorted(set(entry) - {'id', 'direction', 'text', 'service', 'action', 'model',
                                            'family', 'label', 'expected', 'requireBlock'})
        if unknown_case:
            raise ContractError('schema_invalid', f'unknown case fields: {", ".join(unknown_case)}')
        case_id = _optional_text(entry, 'id', 64, CASE_ID)
        if case_id is None or case_id in seen:
            raise ContractError('schema_invalid', 'each case needs a unique id of letters, digits, . _ : -')
        seen.add(case_id)
        direction = entry.get('direction', 'input')
        if direction not in DIRECTIONS:
            raise ContractError('schema_invalid', 'case direction must be input or output')
        text = entry.get('text')
        if not isinstance(text, str):
            raise ContractError('schema_invalid', 'case text must be a string')
        service = entry.get('service')
        action = entry.get('action')
        for value in (service, action):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise ContractError('schema_invalid', 'case service and action must be strings')
        model = entry.get('model', 'demo-local')
        if not isinstance(model, str) or not model.strip():
            raise ContractError('schema_invalid', 'case model must be a non-empty string')
        require_block = entry.get('requireBlock', False)
        if not isinstance(require_block, bool):
            raise ContractError('schema_invalid', 'requireBlock must be a boolean')
        expected = entry.get('expected', {})
        if not isinstance(expected, dict):
            raise ContractError('schema_invalid', 'case expected must be a JSON object')
        unknown_expected = sorted(set(expected) - {'decision', 'disclosure', 'dispatch'})
        if unknown_expected:
            raise ContractError('schema_invalid',
                                f'unknown expected fields: {", ".join(unknown_expected)}')
        decision = expected.get('decision')
        if decision is not None and decision not in DECISIONS:
            raise ContractError('schema_invalid', 'expected.decision must be allow, redact or block')
        disclosure = expected.get('disclosure')
        if disclosure is not None and disclosure not in DISCLOSURES:
            raise ContractError('schema_invalid',
                                'expected.disclosure must be full, redacted or withheld')
        dispatch = expected.get('dispatch')
        if dispatch is not None and not isinstance(dispatch, bool):
            raise ContractError('schema_invalid', 'expected.dispatch must be a boolean')
        cases.append(EvaluationCase(
            case_id=case_id, direction=direction, text=text, service=service, action=action,
            model=model.strip(), family=_optional_text(entry, 'family', 48, FAMILY),
            label=_optional_text(entry, 'label', 120), expected_decision=decision,
            expected_disclosure=disclosure, expect_dispatch=dispatch, require_block=require_block))

    detector_profile = body.get('detectorProfile')
    if detector_profile is not None and not isinstance(detector_profile, str):
        raise ContractError('schema_invalid', 'detectorProfile must be a string')

    candidate = body.get('candidate', {})
    if not isinstance(candidate, dict):
        raise ContractError('schema_invalid', 'candidate must be a JSON object')
    unknown_candidate = sorted(set(candidate) - {'documents', 'contentPolicy', 'hash', 'revision',
                                                 'datasetHash', 'mode'})
    if unknown_candidate:
        raise ContractError('schema_invalid',
                            f'unsupported candidate fields: {", ".join(unknown_candidate)}')
    documents = candidate.get('documents', {})
    if not isinstance(documents, dict):
        raise ContractError('schema_invalid', 'candidate.documents must be a JSON object')
    unknown_documents = sorted(set(documents) - set(EDITABLE_DOCUMENTS))
    if unknown_documents:
        raise ContractError('schema_invalid',
                            f'unsupported candidate documents: {", ".join(unknown_documents)}')
    content_policy = candidate.get('contentPolicy')
    if content_policy is not None:
        # Legacy content-only preview shape: folded into the documents map.
        if not isinstance(content_policy, dict):
            raise ContractError('schema_invalid', 'candidate.contentPolicy must be an object')
        documents = dict(documents, contentPolicy=content_policy)
    _reject_forbidden(documents)
    mode = candidate.get('mode', 'full')
    if mode not in CANDIDATE_MODES:
        raise ContractError('schema_invalid', 'candidate.mode must be full or budget-only')
    expected_revision = body.get('expectedRevision')
    if expected_revision is not None:
        expected_revision = parse_expected_revision(body)
    parsed_candidate = {
        'documents': documents,
        'hash': _optional_text(candidate, 'hash', 64, HASH),
        'revision': expected_revision,
        'rawRevision': _optional_text(candidate, 'revision', 64, REVISION),
        'datasetHash': _optional_text(candidate, 'datasetHash', 64, HASH),
        'mode': mode,
    }
    return EvaluationRequest(tuple(cases), detector_profile, parsed_candidate)


def _reject_forbidden(documents: dict) -> None:
    """Refuse credentials, endpoints and file paths anywhere inside a configuration payload."""
    def walk(value, trail):
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in {name.lower() for name in FORBIDDEN_CONFIG_FIELDS}:
                    raise ContractError('credential_field_rejected',
                                        f'configuration payload may not set {trail}{key!r}', 422)
                walk(item, f'{trail}{key}.')
        elif isinstance(value, list):
            for index, item in enumerate(value):
                walk(item, f'{trail}{index}.')

    walk(documents, '')


def parse_documents(body, *, require_all: bool = True) -> dict:
    """Parse an editable document bundle (draft save, import, or a raw candidate)."""
    if not isinstance(body, dict):
        raise ContractError('schema_invalid', 'documents must be a JSON object')
    unknown = sorted(set(body) - set(EDITABLE_DOCUMENTS))
    if unknown:
        raise ContractError('schema_invalid', f'unsupported documents: {", ".join(unknown)}')
    if require_all:
        missing = sorted(set(EDITABLE_DOCUMENTS) - set(body))
        if missing:
            raise ContractError('schema_invalid', f'missing documents: {", ".join(missing)}')
    for name, document in body.items():
        if not isinstance(document, dict):
            raise ContractError('schema_invalid', f'{name} must be a JSON object')
    _reject_forbidden(body)
    return {name: document for name, document in body.items()}


def parse_bundle(body) -> dict:
    """Parse an exported configuration bundle: schema version plus the editable documents."""
    if not isinstance(body, dict):
        raise ContractError('schema_invalid', 'bundle must be a JSON object')
    unknown = sorted(set(body) - {'schemaVersion', 'bundleId', 'documents', 'note', 'release',
                                  'fileHash'})
    if unknown:
        raise ContractError('schema_invalid', f'unsupported bundle fields: {", ".join(unknown)}')
    documents = body.get('documents')
    if not isinstance(documents, dict):
        raise ContractError('schema_invalid', 'bundle.documents must be a JSON object')
    # A bundle carries the documents it knows about; the importer merges them over the active
    # release, so a partially edited bundle is a valid import.
    return parse_documents(documents, require_all=False)


def parse_expected_revision(body, field_name: str = 'expectedRevision'):
    value = body.get(field_name)
    if type(value) is not int or value < 0:
        raise ContractError('schema_invalid', f'{field_name} must be a non-negative integer')
    return value


def parse_reason(body, limit: int = 200) -> str:
    value = body.get('reason')
    if not isinstance(value, str) or not value.strip():
        raise ContractError('schema_invalid', 'reason must be a non-empty string')
    value = value.strip()
    if len(value) > limit:
        raise ContractError('schema_invalid', f'reason exceeds {limit} characters')
    return value
