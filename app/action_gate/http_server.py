"""HTTP layer for the Action Gate.

The standard-library server implements the protected call: content controls, semantic evaluation,
budget reservation, one controlled dispatch, output controls and durable audit. On top of it sits
the policy lifecycle (draft, compare, activate, rollback, import/export) and the reporting read
model.

Two independent identity checks exist and they are not the same thing:

* **transport identity** - the principal and token headers. A caller cannot choose a role in a body.
* **role capability** - the ability to change configuration. An ``agent`` principal can be a valid
  caller and still have no configuration capability at all. Hiding a button in a browser is not a
  control; the check happens here, on the server.

Status mapping is part of the contract:

* ``200`` - the invocation was evaluated and, unless it was a dry run, dispatched
* ``401`` - the caller identity header is missing or unknown
* ``403`` - insufficient role, or a policy refusal (signature, sensitivity, grant, semantic)
* ``404`` - unknown service, action or path; also another principal's invocation
* ``409`` - stale revision, stale evaluation, operation conflict, admission conflict
* ``413`` - request body above the configured limit
* ``422`` - schema violation, including any attempt to carry identity or credentials in the body
* ``429`` - budget refused the call before any paid work
* ``503`` - a mandatory dependency could not be verified (model, configuration, storage)
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from . import __version__
from .audit import hash_salt
from .config_bundle import ConfigurationError
from .config_service import ConfigConflict, ConfigService
from .contracts import (MAX_BODY_BYTES, ContractError, parse_bundle, parse_documents,
                        parse_evaluation, parse_expected_revision, parse_invocation, parse_reason)
from .gateway import Gateway
from .snapshot import FileConfigSource, snapshot_from_documents
from .storage import RepositoryError, build_repository, build_runtime
from .storage.base import iso_utc
from .storage.config_store import build_config_store
from .identity import PRINCIPAL_HEADER, TOKEN_HEADER, resolve
from .panel_service import PanelService
from .operator_reporting import OperatorReporting
from .panel_engine import PanelValidationError
from .model_proxy import ModelProxy, ProxyError, error_body, sse, validate_request

MAX_EXPORT_LIMIT = 1000
DEFAULT_EXPORT_LIMIT = 200
MAX_LIST_LIMIT = 200
DEFAULT_LIST_LIMIT = 50
DEFAULT_WINDOW_MINUTES = 1440
MAX_WINDOW_MINUTES = 43200
STATIC_ASSETS = {
    '/app.css': ('app.css', 'text/css'),
    '/app.js': ('app.js', 'application/javascript'),
    '/control': ('control/index.html', 'text/html'),
    '/control/': ('control/index.html', 'text/html'),
    '/control/console.css': ('control/console.css', 'text/css'),
    '/control/console.js': ('control/console.js', 'application/javascript'),
    '/control/policy.js': ('control/policy.js', 'application/javascript'),
    '/control/panel.js': ('control/panel.js', 'application/javascript'),
    '/control/vendor/js-yaml.min.js': ('control/vendor/js-yaml.min.js', 'application/javascript'),
}
CONFIG_WRITE_CAPABILITY = 'config:write'
# Reporting routes and their scopes: an operator sees the whole bench, an agent only its own rows.
OPERATOR_ONLY_PREFIXES = ('/v1/config', '/v1/audit')


class DatabaseConfigSource:
    """The active release, read from the durable store.

    After the first start the database is the source of truth: files are imported once and are not
    consulted again, so editing a file on the host cannot silently change live behaviour.
    """

    name = 'database'

    def __init__(self, service: ConfigService):
        self.service = service
        self._cache: dict[tuple, object] = {}

    def load(self, *, force: bool = False):
        snapshot = self.service.snapshot()
        key = (snapshot.release_hash, snapshot.activation_generation)
        if force or key not in self._cache:
            self._cache = {key: snapshot}
        return self._cache[key]


class GateApplication:
    """Owns the long-lived objects so handlers stay thin and testable."""

    def __init__(self, environ=None):
        self.environ = dict(os.environ if environ is None else environ)
        self.policy_dir = self.environ.get('APP_POLICY_DIR') or str(
            Path(__file__).resolve().parents[1] / 'policy')
        self.static_dir = Path(self.environ.get('APP_STATIC_DIR')
                               or (Path(__file__).resolve().parents[1] / 'static'))
        self.startup_error = None
        self.bootstrap = {'created': False, 'source': 'files', 'error': None,
                          'release': None, 'generation': None}
        try:
            self.repository = build_repository(self.environ)
        except RepositoryError as exc:
            self.repository = None
            self.startup_error = exc.code
        self.runtime = build_runtime(self.environ)
        self.salt, self.development_salt = hash_salt(self.environ)
        self.config_service = None
        self.config_source = None
        if self.repository is not None:
            self.config_service = ConfigService(self.repository, build_config_store(self.repository),
                                                self.environ.get('APP_ENV', 'local'))
            file_source = FileConfigSource(self.policy_dir)
            try:
                created, snapshot, error = self._bootstrap_with_retry(file_source)
                self.bootstrap.update({'created': created, 'error': error,
                                       'release': getattr(snapshot, 'release_hash', None),
                                       'generation': getattr(snapshot, 'activation_generation', None),
                                       'source': 'files'})
                if snapshot is not None:
                    self.config_source = DatabaseConfigSource(self.config_service)
                else:
                    self.startup_error = 'configuration_invalid'
            except Exception as exc:  # storage reachable but not migrated, for example
                # The class name alone is not actionable for an operator, so the message is
                # recorded and the detail is printed once at startup. It carries no request data.
                self.startup_error = '{}: {}'.format(type(exc).__name__, exc)
                self.bootstrap['error'] = self.startup_error
                import traceback
                traceback.print_exc()
            if self.config_source is None and self.startup_error is None:
                self.config_source = file_source
        self.gateway = Gateway(self.policy_dir, self.repository, self.runtime, self.environ,
                               config_source=self.config_source) \
            if self.repository is not None else None
        self.panel_service = PanelService(self.repository) if self.repository is not None else None
        self.operator_reporting = OperatorReporting(self.repository, self.panel_service) if self.panel_service else None
        self.model_proxy = ModelProxy(self.gateway, self.panel_service, self.environ) if self.gateway else None

    def _bootstrap_with_retry(self, file_source, attempts: int = 3):
        """Seed the active release, tolerating a database that is not ready yet.

        PostgreSQL is healthy before the API starts, but a connection pool can still lose the first
        race. A retry is bounded and only covers a *transient* failure: an invalid bundle or a
        missing migration is reported immediately rather than retried into a timeout.
        """
        import time
        last = None
        for attempt in range(attempts):
            try:
                return self.config_service.bootstrap(file_source)
            except Exception as exc:  # noqa: BLE001 - reported to the operator below
                last = exc
                if not _looks_transient(exc) or attempt == attempts - 1:
                    raise
                time.sleep(0.5 * (attempt + 1))
        raise last

    # -- identity ------------------------------------------------------------------
    def principal(self, headers):
        # One resolver shared with the MCP ingress: same registry, same comparison, same failures.
        snapshot = self.config_source.load() if self.config_source else None
        return resolve(snapshot, headers)


def build_application(environ=None) -> GateApplication:
    return GateApplication(environ)


class GateHandler(BaseHTTPRequestHandler):
    server_version = 'ActionGate'
    protocol_version = 'HTTP/1.1'

    # -- plumbing ----------------------------------------------------------------
    @property
    def app(self) -> GateApplication:
        return self.server.app

    def respond(self, status, payload, content_type='application/json', extra_headers=()):
        if content_type == 'application/json':
            body = json.dumps(payload, default=str).encode('utf-8')
        else:
            body = payload if isinstance(payload, bytes) else str(payload).encode('utf-8')
        self.send_response(status)
        suffix = '; charset=utf-8' if (content_type.startswith('text/')
                                       or content_type in ('application/json',
                                                           'application/javascript')) else ''
        self.send_header('Content-Type', content_type + suffix)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        for name, value in extra_headers:
            self.send_header(name, value)
        self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def error(self, status, code, message=None, extra=None):
        payload = {'error': code}
        if message:
            payload['message'] = message
        if extra:
            payload.update(extra)
        self.respond(status, payload)

    def read_body(self):
        try:
            length = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            raise ContractError('schema_invalid', 'invalid Content-Length', 400)
        if length > MAX_BODY_BYTES:
            raise ContractError('body_too_large', f'body exceeds {MAX_BODY_BYTES} bytes', 413)
        raw = self.rfile.read(length) if length else b''
        if not raw:
            raise ContractError('malformed_json', 'request body is empty', 400)
        try:
            return json.loads(raw)
        except ValueError as exc:
            raise ContractError('malformed_json', 'request body is not valid JSON', 400) from exc

    def log_request(self, code='-', size='-'):
        # Never log request bodies, query strings, identity headers or environment values.
        path = urlsplit(self.path).path
        print(json.dumps({'method': self.command, 'path': path[:120], 'status': code}), flush=True)

    def authenticated(self):
        """Resolve transport identity once. Returns (principal, error_response_sent)."""
        principal, failure = self.app.principal(self.headers)
        if failure:
            self.error(401, failure, 'supply a configured principal id and token header')
            return None
        return principal

    def require_capability(self, principal, capability: str):
        """Server-side role check. A hidden control in a browser is not a permission."""
        allowed = {'agent': set(), 'operator': {'config:write', 'reporting:all',
                                                'evaluation:run', 'reporting:own'}}
        if capability not in allowed.get(principal.role, set()):
            self.error(403, 'insufficient_role',
                       f'role {principal.role!r} may not use {capability}')
            return False
        return True

    # -- GET ---------------------------------------------------------------------
    def do_GET(self):
        parts = urlsplit(self.path)
        path, query = parts.path, parse_qs(parts.query)
        if path in STATIC_ASSETS:
            return self.static_asset(path)
        if path == '/':
            return self.index_page()
        if path.startswith('/v1/panel/'):
            return self.panel_request(path)
        if self.app.gateway is None:
            if path == '/health/live':
                return self.respond(200, {'status': 'alive', 'scope': 'process',
                                          'version': __version__})
            return self.error(503, 'storage_unavailable', self.app.startup_error)
        try:
            if path == '/health/live':
                return self.respond(200, {'status': 'alive', 'scope': 'process',
                                          'version': __version__, 'stage': 'policy-lifecycle'})
            if path == '/health/ready':
                status, payload = self.app.gateway.readiness()
                return self.respond(status, payload)
            if path == '/version':
                storage = self.app.repository.name
                return self.respond(200, {
                    'service': 'action-gate', 'version': __version__, 'stage': 'policy-lifecycle',
                    'storage': storage, 'durable': storage == 'postgres',
                    'runtimeCache': self.app.runtime.name,
                    'hashSalt': 'development-default' if self.app.development_salt else 'configured',
                    'configSource': getattr(self.app.config_source, 'name', 'unavailable'),
                    'bootstrap': self.app.bootstrap,
                    'policyDir': self.app.policy_dir,
                })
            if path == '/v1/config/release':
                status, payload = self.app.gateway.release_info()
                return self.respond(status, payload)
            if path == '/v1/services':
                return self.respond(200, self.app.gateway.services_info())

            # Everything below returns another caller's data or changes configuration, so it needs
            # an identity, and the configuration routes need the operator capability as well.
            if path == '/v1/me' or path.startswith('/v1/config') or path.startswith('/v1/invocations') \
                    or path in ('/v1/report', '/v1/summary', '/v1/audit/export', '/v1/audit/events'):
                principal = self.authenticated()
                if principal is None:
                    return None
                if path == '/v1/me':
                    return self.respond(200, self.app.gateway.me(principal))
                if path.startswith('/v1/config'):
                    if not self.require_capability(principal, CONFIG_WRITE_CAPABILITY):
                        return None
                    return self.config_get(path, query, principal)
                if path == '/v1/report':
                    since, until = window_bounds(query)
                    return self.respond(200, self.app.operator_reporting.report(since, until,
                        None if principal.role == 'operator' else principal.id))
                if path == '/v1/summary':
                    return self.summary(query, principal)
                if path == '/v1/audit/export':
                    return self.audit_export(query, principal)
                if path == '/v1/audit/events':
                    return self.audit_events(query, principal)
                if path == '/v1/invocations':
                    return self.invocation_list(query, principal)
                invocation_id = path[len('/v1/invocations/'):]
                if not invocation_id:
                    return self.error(404, 'not_found')
                return self.invocation_trace(invocation_id, principal)
            return self.error(404, 'not_found')
        except ConfigurationError as exc:
            return self.error(503, 'configuration_invalid', str(exc))
        except ConfigConflict as exc:
            return self.error(409, exc.code, exc.detail)
        except ContractError as exc:
            return self.error(exc.status, exc.code, exc.message)
        except RepositoryError as exc:
            return self.error(503, 'storage_unavailable', exc.code)
        except Exception as exc:
            return self.error(500, 'internal_error', type(exc).__name__)

    def static_asset(self, path):
        name, content_type = STATIC_ASSETS[path]
        target = (self.app.static_dir / name).resolve()
        if self.app.static_dir.resolve() not in target.parents or not target.is_file():
            return self.error(404, 'not_found')
        return self.respond(200, target.read_bytes(), content_type)

    def index_page(self):
        target = self.app.static_dir / 'index.html'
        if target.is_file():
            return self.respond(200, target.read_bytes(), 'text/html')
        return self.respond(200, self.fallback_page(), 'text/html')

    def fallback_page(self):
        import html
        storage = self.app.repository.name if self.app.repository else 'unavailable'
        return (
            "<!doctype html><html lang='en'><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'>"
            "<title>Action Gate</title><main>"
            f"<h1>Action Gate {html.escape(__version__)}</h1>"
            "<p>The protected invocation path is active: content controls, semantic evaluation, "
            "budget reservation, one controlled dispatch, output controls and durable audit.</p>"
            f"<p>Storage: <code>{html.escape(storage)}</code> · "
            f"runtime cache: <code>{html.escape(self.app.runtime.name)}</code></p>"
            "<p>The interactive console was not found in this build.</p>"
            "</main></html>")

    # -- configuration routes ------------------------------------------------------
    def config_get(self, path, query, principal):
        service = self.app.config_service
        if path == '/v1/config/active':
            snapshot = self.app.config_source.load()
            return self.respond(200, {
                'release': snapshot.release_hash,
                'fileHash': snapshot.file_hash,
                'schemaVersion': snapshot.schema_version,
                'activationGeneration': snapshot.activation_generation,
                'componentHashes': dict(snapshot.component_hashes),
                'editableDocuments': service.editable_documents(snapshot),
                'storage': self.app.repository.name,
                'source': snapshot.source,
            })
        if path == '/v1/config/releases':
            limit = self.bounded_int(query, 'limit', 50, 1, 200)
            before = query.get('before', [None])[0]
            return self.respond(200, {'releases': service.releases(limit, before)})
        if path == '/v1/config/activations':
            limit = self.bounded_int(query, 'limit', 50, 1, 200)
            return self.respond(200, {'activations': service.activations(limit)})
        if path == '/v1/config/export':
            release = query.get('release', [None])[0]
            return self.respond(200, service.export_bundle(release))
        if path.startswith('/v1/config/drafts/'):
            draft_id = path[len('/v1/config/drafts/'):]
            if not draft_id:
                return self.error(404, 'not_found')
            record = service.get_draft(draft_id)
            return self.respond(200, {
                'draftId': record['draft_id'], 'revision': record['revision'],
                'baseRelease': record['base_release'], 'source': record.get('source'),
                'createdBy': record.get('created_by'),
                'updatedAt': _iso(record.get('updated_at')),
                'documents': record['documents'],
            })
        if path == '/v1/config/drafts':
            return self.respond(200, {'drafts': service.store.list_drafts(
                self.bounded_int(query, 'limit', 20, 1, 100))})
        if path.startswith('/v1/config/evaluations/'):
            evaluation_id = path[len('/v1/config/evaluations/'):]
            record = service.store.get_evaluation(evaluation_id)
            if record is None:
                return self.error(404, 'not_found')
            return self.respond(200, _evaluation_public(record))
        return self.error(404, 'not_found')

    def config_post(self, path, body, principal):
        service = self.app.config_service
        if path == '/v1/config/drafts':
            documents = body.get('documents')
            parsed = parse_documents(documents, require_all=False) if documents else None
            result = service.create_draft(documents=parsed, created_by=principal.id,
                                          source=body.get('source') or 'api')
            return self.respond(201, {'draftId': result.draft_id, 'revision': result.revision,
                                      'candidateHash': result.candidate_hash,
                                      'baseRelease': self.app.config_source.load().release_hash,
                                      'documents': result.documents})
        if path == '/v1/config/validate':
            documents = parse_documents(body.get('documents'), require_all=False)
            candidate = service.preview(documents)
            return self.respond(200, {'valid': True, 'candidateHash': candidate.release_hash,
                                      'componentHashes': dict(candidate.component_hashes)})
        if path == '/v1/config/import':
            # The contract layer checks the bundle *shape*; the service validates the documents, so
            # an unacceptable policy is reported as an invalid candidate rather than a bad request.
            documents = parse_bundle(body)
            result = service.import_bundle({'schemaVersion': body.get('schemaVersion'),
                                            'documents': documents},
                                           created_by=principal.id)
            return self.respond(201, {'draftId': result.draft_id, 'revision': result.revision,
                                      'candidateHash': result.candidate_hash,
                                      'documents': result.documents,
                                      'note': 'Imported bundles are stored as a draft and never '
                                              'activate themselves.'})
        if path.startswith('/v1/config/drafts/'):
            return self.draft_action(path[len('/v1/config/drafts/'):], body, principal)
        if path == '/v1/config/activations':
            return self.activate(body, principal)
        if path == '/v1/config/rollbacks':
            return self.rollback(body, principal)
        return self.error(404, 'not_found')

    def draft_action(self, remainder, body, principal):
        service = self.app.config_service
        draft_id, _, action = remainder.partition('/')
        if not draft_id:
            return self.error(404, 'not_found')
        if action == '':
            expected = parse_expected_revision(body)
            documents = parse_documents(body.get('documents'), require_all=False)
            result = service.save_draft(draft_id, expected_revision=expected, documents=documents,
                                        created_by=principal.id)
            return self.respond(200, {'draftId': result.draft_id, 'revision': result.revision,
                                      'candidateHash': result.candidate_hash,
                                      'documents': result.documents,
                                      'note': 'Saving a draft does not change the active release.'})
        if action == 'compare':
            return self.compare(draft_id, body, principal)
        return self.error(404, 'not_found')

    def compare(self, draft_id, body, principal):
        from .evaluation import EvaluationRequest
        request = parse_evaluation(body)
        # The editor states which revision it compared; omitting it compares the newest one.
        revision = None if 'expectedRevision' not in body else parse_expected_revision(body)
        service = self.app.config_service
        candidate, payload = service.candidate_from_draft(draft_id, revision)
        if request.detector_profile and request.detector_profile != candidate.detectors['default']:
            return self.error(422, 'schema_invalid',
                              'this build compares a candidate against its own default profile')
        enriched = EvaluationRequest(
            cases=request.cases, detector_profile=request.detector_profile,
            candidate={'documents': payload, 'revision': revision,
                       'datasetHash': request.dataset_hash, 'mode': request.mode,
                       'hash': candidate.release_hash})
        status, result = self.app.gateway.evaluate(enriched)
        if status == 200:
            active = self.app.config_source.load()
            evaluation_id = service.record_evaluation(
                result, active=active, candidate_hash=candidate.release_hash,
                candidate_revision=revision, dataset_hash=request.dataset_hash,
                detector_profile=result['detector']['profile'], actor=principal.id)
            result['evaluationId'] = evaluation_id
            result['candidate']['revision'] = revision
            result['note'] = (result['note'] + ' This run is the evidence an activation needs; it '
                              'is bound to these hashes and this detector identity.')
        return self.respond(status, result)

    def activate(self, body, principal):
        draft_id = body.get('draftId')
        if not isinstance(draft_id, str) or not draft_id.strip():
            raise ContractError('schema_invalid', 'draftId is required')
        result = self.app.config_service.activate(
            draft_id=draft_id.strip(),
            expected_revision=parse_expected_revision(body),
            expected_generation=parse_expected_revision(body, 'expectedActiveGeneration'),
            evaluation_id=_optional_str(body, 'evaluationId'),
            operation_key=_optional_str(body, 'operationKey'),
            actor=principal.id,
            reason=_optional_str(body, 'reason'))
        return self.respond(200, result)

    def rollback(self, body, principal):
        target = _optional_str(body, 'targetReleaseHash')
        if not target:
            raise ContractError('schema_invalid', 'targetReleaseHash is required')
        result = self.app.config_service.rollback(
            target_release_hash=target,
            expected_generation=parse_expected_revision(body, 'expectedActiveGeneration'),
            operation_key=_optional_str(body, 'operationKey'),
            actor=principal.id,
            reason=parse_reason(body))
        return self.respond(200, result)

    # -- reporting -----------------------------------------------------------------
    def summary(self, query, principal):
        since, until = window_bounds(query)
        payload = self.app.gateway.summary(
            since, until, principal_id=None if principal.role == 'operator' else principal.id)
        if principal.role != 'operator':
            payload['budget'] = dict(payload.get('budget') or {},
                                     label='Current shared budget (UTC day, all callers)',
                                     note='An agent sees its own rows; the shared ledger is not '
                                          'this agent\'s personal budget.')
        payload['unified'] = self.app.operator_reporting.report(since, until, None if principal.role == 'operator' else principal.id)
        payload['scope'] = 'bench' if principal.role == 'operator' else 'own'
        if principal.role != 'operator':
            # An agent's counters cover its own rows only; the shared ledger stays visible because
            # it is shared, and it is labelled as shared rather than as this agent's budget.
            payload['ownInvocations'] = dict(payload['invocations'])
            payload['ownOutcomes'] = dict(payload['outcomes'])
        return self.respond(200, payload)

    def invocation_list(self, query, principal):
        since, until = window_bounds(query)
        limit = self.bounded_int(query, 'limit', DEFAULT_LIST_LIMIT, 1, MAX_LIST_LIMIT)
        cursor = query.get('cursor', [None])[0]
        filters = {
            'decision': _one_of(query, 'decision', ('allow', 'redact', 'block')),
            'outcome': _one_of(query, 'outcome', ('succeeded', 'not_started', 'unknown', 'failed')),
            'service': query.get('service', [None])[0],
            'action': query.get('action', [None])[0],
            'dryRun': _optional_bool(query, 'dryRun'),
        }
        if principal.role != 'operator':
            filters['principal_id'] = principal.id
        page = self.app.repository.list_invocations(since, until, limit, cursor, filters)
        page['window'] = {'since': since, 'until': until}
        page['scope'] = 'bench' if principal.role == 'operator' else 'own'
        page['filters'] = {key: value for key, value in filters.items() if value is not None}
        return self.respond(200, page)

    def invocation_trace(self, invocation_id, principal):
        status, payload = self.app.gateway.trace(invocation_id)
        if status != 200:
            return self.respond(status, payload)
        record = payload['invocation']
        if principal.role != 'operator' and record.get('principal_id') != principal.id:
            # Another principal's trace is reported as absent, not as forbidden: an agent must not
            # be able to probe which invocation ids exist.
            return self.error(404, 'not_found')
        return self.respond(200, payload)

    def audit_export(self, query, principal):
        since, until = window_bounds(query)
        limit = self.bounded_int(query, 'limit', DEFAULT_EXPORT_LIMIT, 1, MAX_EXPORT_LIMIT)
        cursor = query.get('cursor', [None])[0]
        filters = {'kind': _one_of(query, 'kind', None)}
        if principal.role != 'operator':
            filters['principal_id'] = principal.id
        page = self.app.operator_reporting.audit_page(since, until, limit, cursor, filters)
        rows = page['events']
        lines = '\n'.join(json.dumps(row, default=str, ensure_ascii=False) for row in rows)
        headers = [('X-Action-Gate-Next-Cursor', page['nextCursor'] or ''),
                   ('X-Action-Gate-Truncated', 'true' if page['truncated'] else 'false'),
                   ('X-Action-Gate-Window-Since', since),
                   ('X-Action-Gate-Window-Until', until)]
        return self.respond(200, lines + ('\n' if lines else ''), 'application/x-ndjson', headers)

    def audit_events(self, query, principal):
        since, until = window_bounds(query)
        limit = self.bounded_int(query, 'limit', DEFAULT_LIST_LIMIT, 1, MAX_LIST_LIMIT)
        cursor = query.get('cursor', [None])[0]
        filters = {'kind': _one_of(query, 'kind', None)}
        if principal.role != 'operator':
            filters['principal_id'] = principal.id
        page = self.app.operator_reporting.audit_page(since, until, limit, cursor, filters)
        page['window'] = {'since': since, 'until': until}
        return self.respond(200, page)

    def bounded_int(self, query, name: str, default: int, lower: int, upper: int) -> int:
        raw = query.get(name, [str(default)])[0]
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise ContractError('schema_invalid', f'{name} must be an integer')
        return max(lower, min(upper, value))

    # -- POST --------------------------------------------------------------------
    def do_POST(self):
        path = urlsplit(self.path).path
        if path == '/v1/responses':
            return self.model_request()
        if path.startswith('/v1/panel/'):
            return self.panel_request(path)
        if self.app.gateway is None:
            return self.error(503, 'storage_unavailable', self.app.startup_error)
        if not (path in ('/v1/invocations', '/v1/evaluations') or path.startswith('/v1/config')):
            return self.error(404, 'not_found')
        try:
            body = self.read_body()
        except ContractError as exc:
            return self.error(exc.status, exc.code, exc.message)
        try:
            principal = self.authenticated()
            if principal is None:
                return None
            if path.startswith('/v1/config'):
                if not self.require_capability(principal, CONFIG_WRITE_CAPABILITY):
                    return None
                return self.config_post(path, body, principal)
            snapshot = self.app.config_source.load()
            if path == '/v1/invocations':
                request = parse_invocation(body, snapshot)
                status, payload = self.app.gateway.invoke(request, principal, snapshot=snapshot)
                return self.respond(status, payload)
            evaluation = parse_evaluation(body)
            status, payload = self.app.gateway.evaluate(evaluation)
            return self.respond(status, payload)
        except ContractError as exc:
            return self.error(exc.status, exc.code, exc.message)
        except ConfigConflict as exc:
            return self.error(409, exc.code, exc.detail)
        except ConfigurationError as exc:
            return self.error(503, 'configuration_invalid', str(exc))
        except RepositoryError as exc:
            return self.error(503, 'storage_unavailable', exc.code)
        except Exception as exc:
            return self.error(500, 'internal_error', type(exc).__name__)

    def do_PUT(self):
        path = urlsplit(self.path).path
        if path.startswith('/v1/panel/'):
            return self.panel_request(path)
        if not path.startswith('/v1/config'):
            return self.error(405, 'method_not_allowed')
        if self.app.gateway is None:
            return self.error(503, 'storage_unavailable', self.app.startup_error)
        try:
            body = self.read_body()
        except ContractError as exc:
            return self.error(exc.status, exc.code, exc.message)
        try:
            principal = self.authenticated()
            if principal is None:
                return None
            if not self.require_capability(principal, CONFIG_WRITE_CAPABILITY):
                return None
            return self.config_put(path, body, principal)
        except ContractError as exc:
            return self.error(exc.status, exc.code, exc.message)
        except ConfigConflict as exc:
            return self.error(409, exc.code, exc.detail)
        except ConfigurationError as exc:
            return self.error(503, 'configuration_invalid', str(exc))
        except RepositoryError as exc:
            return self.error(503, 'storage_unavailable', exc.code)
        except Exception as exc:
            return self.error(500, 'internal_error', type(exc).__name__)

    def config_put(self, path, body, principal):
        """PUT is the documented editor write: it replaces the editable documents of a draft.

        It is never optimistic: the caller states the revision it edited, and a mismatch is a
        ``409`` rather than a silent overwrite of someone else's change.
        """
        if path.startswith('/v1/config/drafts/'):
            remainder = path[len('/v1/config/drafts/'):]
            draft_id, _, action = remainder.partition('/')
            if draft_id and not action:
                expected = parse_expected_revision(body)
                documents = parse_documents(body.get('documents'), require_all=False)
                result = self.app.config_service.save_draft(
                    draft_id, expected_revision=expected, documents=documents,
                    created_by=principal.id)
                return self.respond(200, {'draftId': result.draft_id,
                                          'revision': result.revision,
                                          'candidateHash': result.candidate_hash,
                                          'documents': result.documents,
                                          'note': 'Saving a draft does not change the active '
                                                  'release.'})
        return self.error(404, 'not_found')

    def model_request(self):
        try:
            if self.app.model_proxy is None:
                raise ProxyError('storage_unavailable', 503)
            principal, failure = self.app.principal(self.headers)
            if principal is None:
                raise ProxyError(failure or 'missing_identity', 503 if failure == 'configuration_invalid' else 401)
            if self.headers.get('Transfer-Encoding') or int(self.headers.get('Content-Length') or 0) < 0:
                raise ProxyError('invalid_body_framing', 400)
            body = self.read_body()
            validate_request(body)
            reply = self.app.model_proxy.invoke(body, principal)
            if reply.stream:
                return self.respond(reply.status, sse(reply.body), 'text/event-stream',
                                    (*reply.headers, ('X-Action-Gate-Streaming', 'buffered')))
            return self.respond(reply.status, reply.body, extra_headers=reply.headers)
        except (ProxyError, ContractError) as exc:
            return self.respond(exc.status, error_body(exc.code))
        except (ValueError, TypeError):
            return self.respond(422, error_body('schema_invalid'))
        except Exception:
            return self.respond(503, error_body('dependency_unavailable'))

    def panel_request(self, path):
        """Original panel contract: one server evaluator for compare and controlled execution.

        Operators can edit policy and run explicitly synthetic requests on behalf of a demo agent.
        Agent callers can invoke only; the service derives their subject from transport identity.
        Nothing in the service catalog is a network destination for this local runtime.
        """
        if self.app.panel_service is None:
            return self.error(503, 'storage_unavailable', self.app.startup_error)
        try:
            principal = self.authenticated()
            if principal is None:
                return None
            if not (self.command == 'POST' and path == '/v1/panel/invoke'):
                if not self.require_capability(principal, CONFIG_WRITE_CAPABILITY):
                    return None
            body = {} if self.command == 'GET' else self.read_body()
            if not isinstance(body, dict):
                raise ContractError('schema_invalid', 'request body must be a JSON object')
            status, payload = self.app.panel_service.dispatch(
                self.command, path[len('/v1/panel'):], body, principal)
            return self.respond(status, payload)
        except ContractError as exc:
            return self.error(exc.status, exc.code, exc.message)
        except PanelValidationError as exc:
            return self.error(422, exc.code, str(exc))
        except ConfigConflict as exc:
            return self.error(409, exc.code, exc.detail)
        except ConfigurationError as exc:
            return self.error(503, 'configuration_invalid', str(exc))
        except RepositoryError as exc:
            return self.error(503, 'storage_unavailable', exc.code)
        except Exception as exc:
            return self.error(500, 'internal_error', type(exc).__name__)

    do_DELETE = do_PATCH = do_PUT


def _accepts_principal(func) -> bool:
    try:
        return 'principal_id' in func.__code__.co_varnames
    except AttributeError:
        return False


def _iso(value):
    return iso_utc(value) if hasattr(value, 'isoformat') else value


def _looks_transient(exc: Exception) -> bool:
    """Connection-level failures worth one more attempt. Nothing else is retried."""
    name = type(exc).__name__
    message = str(exc).lower()
    if name in ('OperationalError', 'InterfaceError', 'RepositoryError'):
        return True
    return any(marker in message for marker in ('could not connect', 'connection refused',
                                               'server closed the connection', 'starting up',
                                               'storage_busy', 'timeout expired'))


def _optional_str(body: dict, key: str, limit: int = 200):
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ContractError('schema_invalid', f'{key} must be a non-empty string')
    value = value.strip()
    if len(value) > limit:
        raise ContractError('schema_invalid', f'{key} exceeds {limit} characters')
    return value


def _one_of(query, name: str, allowed=None):
    value = query.get(name, [None])[0]
    if value is None:
        return None
    if allowed is not None and value not in allowed:
        raise ContractError('schema_invalid', f'{name} must be one of {", ".join(allowed)}')
    return value


def _optional_bool(query, name: str):
    value = query.get(name, [None])[0]
    if value is None:
        return None
    if value.lower() in ('true', '1', 'yes'):
        return True
    if value.lower() in ('false', '0', 'no'):
        return False
    raise ContractError('schema_invalid', f'{name} must be true or false')


def _evaluation_public(record: dict) -> dict:
    return {
        'evaluationId': record['evaluation_id'],
        'environment': record['environment'],
        'active': {'release': record['active_hash'],
                   'activationGeneration': record['active_generation']},
        'candidate': {'release': record['candidate_hash'],
                      'revision': record.get('candidate_revision')},
        'datasetHash': record.get('dataset_hash'),
        'detector': {'profile': record['detector_profile'],
                     'identity': record.get('detector_identity'),
                     'instructionVersion': record.get('instruction_version')},
        'mode': record.get('mode'),
        'status': record['status'],
        'passed': record.get('passed'),
        'modelCalls': record.get('model_calls'),
        'caseCount': record.get('case_count'),
        'summary': record.get('summary'),
        'createdBy': record.get('created_by'),
        'createdAt': _iso(record.get('created_at')),
    }


def window_bounds(query) -> tuple[str, str]:
    """Resolve one reporting window: ``[since, until)`` in UTC, with both bounds validated.

    A naive timestamp, an unparseable one, or an interval that does not move forward is a schema
    error rather than a silently different window: every metric in a report must be computed over
    the same, explicit interval.
    """
    now = datetime.now(timezone.utc)
    minutes = query.get('window', [str(DEFAULT_WINDOW_MINUTES)])[0]
    try:
        minutes = max(1, min(MAX_WINDOW_MINUTES, int(minutes)))
    except (TypeError, ValueError):
        raise ContractError('schema_invalid', 'window must be an integer number of minutes')
    raw_until = query.get('until', [None])[0]
    raw_since = query.get('since', [None])[0]
    until = _parse_bound(raw_until, 'until') if raw_until else now
    since = _parse_bound(raw_since, 'since') if raw_since else until - timedelta(minutes=minutes)
    if since >= until:
        raise ContractError('schema_invalid', 'since must be earlier than until')
    return iso_utc(since), iso_utc(until)


def _parse_bound(value: str, name: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ContractError('schema_invalid', f'{name} must be an ISO-8601 timestamp') from exc
    if parsed.tzinfo is None:
        # An ambiguous local time is refused instead of guessed: the ledger day is UTC.
        raise ContractError('schema_invalid',
                            f'{name} must include a timezone offset (for example Z)')
    return parsed


def main():
    application = build_application()
    address = (os.environ.get('APP_BIND', '0.0.0.0'), int(os.environ.get('APP_PORT', '8000')))
    server = ThreadingHTTPServer(address, GateHandler)
    server.daemon_threads = True
    server.app = application
    print(json.dumps({
        'event': 'startup', 'service': 'action-gate', 'version': __version__,
        'stage': 'policy-lifecycle', 'bind': address[0], 'port': address[1],
        'storage': application.repository.name if application.repository else 'unavailable',
        'runtimeCache': application.runtime.name, 'policyDir': application.policy_dir,
        'configSource': getattr(application.config_source, 'name', 'unavailable'),
        'bootstrap': application.bootstrap, 'startupError': application.startup_error,
    }), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
