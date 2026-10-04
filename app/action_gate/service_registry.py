"""Published MCP registry: the only place where an internal service becomes a client-visible tool.

Rules this module enforces:

* a connection is taken from the checked-in bootstrap allowlist, never from free-form operator
  metadata and never from a URL submitted through a form;
* discovery reads the service's own tool list, but the description a client sees is the one the
  operator reviewed in the allowlist, not the service's own prose;
* full JSON Schemas are stored and hashed; a schema that changed since the published revision marks
  the tool as requiring review and blocks dispatch to it until an operator approves the drift;
* external ``$ref`` and redirects are not followed, and a schema is checked as a valid JSON Schema
  before it is stored.
"""
from dataclasses import dataclass
import json
import re
from hashlib import sha256
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from .mcp_upstream import UpstreamError

MAX_SERVICES = 8
MAX_TOOLS_PER_SERVICE = 20
MAX_SCHEMA_BYTES = 64 * 1024
SERVICE_ID = re.compile(r'[a-z][a-z0-9_]{0,31}\Z')
TOOL_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_.-]{0,63}\Z')
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')

UPSTREAM_ENVELOPE = ('status', 'service', 'tool', 'operation_id', 'receipt_id', 'replayed')

GATE_FIELDS = {
    # The published schema declares every field it requires, including the outcome status. A client
    # SDK validates structuredContent against this schema, so an undeclared required field would be
    # rejected by the client even though the server produced it.
    'status': {'type': 'string',
               'enum': ['succeeded', 'denied', 'throttled', 'failed', 'outcome_unknown']},
    'service': {'type': 'string'},
    'tool': {'type': 'string'},
    'operation_id': {'type': ['string', 'null']},
    'service_operation_id': {'type': ['string', 'null']},
    'receipt_id': {'type': ['string', 'null']},
    'replayed': {'type': 'boolean'},
    'disclosure': {'type': 'string', 'enum': ['full', 'redacted', 'withheld', 'none']},
    'decision': {'type': 'string', 'enum': ['allow', 'monitor', 'redact', 'throttle', 'block']},
    'effect': {'type': 'string', 'enum': ['succeeded', 'no_effect', 'not_started', 'unknown']},
    'policy_version': {'type': 'integer', 'minimum': 1},
    'resource_id': {'type': ['string', 'null']},
    'filtered_count': {'type': 'integer', 'minimum': 0},
    'reason': {'type': 'string'},
}

REFUSAL_SCHEMA = {
    'type': 'object',
    'properties': {
        'status': {'type': 'string',
                   'enum': ['denied', 'throttled', 'failed', 'outcome_unknown', 'succeeded']},
        'service': {'type': 'string'},
        'tool': {'type': 'string'},
        'operation_id': {'type': ['string', 'null']},
        'service_operation_id': {'type': ['string', 'null']},
        'receipt_id': {'type': ['string', 'null']},
        'replayed': {'type': 'boolean'},
        'decision': {'type': 'string',
                     'enum': ['allow', 'monitor', 'redact', 'throttle', 'block']},
        'effect': {'type': 'string',
                   'enum': ['succeeded', 'no_effect', 'not_started', 'unknown']},
        'disclosure': {'type': 'string', 'enum': ['full', 'redacted', 'withheld', 'none']},
        'reason': {'type': 'string'},
        'policy_version': {'type': 'integer', 'minimum': 1},
        'resource_id': {'type': ['string', 'null']},
        'filtered_count': {'type': 'integer', 'minimum': 0},
        'error': {'type': 'object',
                  'properties': {'code': {'type': 'string'}, 'message': {'type': 'string'}},
                  'required': ['code'], 'additionalProperties': False},
    },
    'required': ['status', 'operation_id', 'decision', 'effect', 'disclosure'],
    'additionalProperties': False,
}


class RegistryError(RuntimeError):
    def __init__(self, code, detail=None):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False)


def document_hash(document) -> str:
    return sha256(canonical(document).encode('utf-8')).hexdigest()


def _reject_refs(value, where, depth=0):
    """Refuse ``$ref`` outright: the runtime never resolves a reference it did not author."""
    if depth > 32:
        raise RegistryError('schema_too_deep', where)
    if isinstance(value, dict):
        if '$ref' in value:
            raise RegistryError('schema_ref_not_allowed', f'{where} uses $ref')
        if 'allOf' in value or 'anyOf' in value or 'not' in value:
            # Kept deliberately small: the runtime supports the subset the services publish.
            raise RegistryError('schema_unsupported_keyword', f'{where} uses an unsupported keyword')
        for key, item in value.items():
            _reject_refs(item, f'{where}.{key}', depth + 1)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_refs(item, f'{where}[{index}]', depth + 1)


def _check_schema(schema, where):
    if not isinstance(schema, dict):
        raise RegistryError('schema_invalid', f'{where} is not an object')
    encoded = canonical(schema)
    if len(encoded.encode('utf-8')) > MAX_SCHEMA_BYTES:
        raise RegistryError('schema_too_large', where)
    _reject_refs(schema, where)
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as exc:  # noqa: BLE001
        raise RegistryError('schema_invalid', f'{where}: {exc}') from exc
    return schema


def _validate_endpoint(endpoint, allowed_hosts, where):
    if not isinstance(endpoint, str) or len(endpoint) > 300:
        raise RegistryError('endpoint_invalid', where)
    parsed = urlsplit(endpoint)
    if parsed.scheme != 'http' or not parsed.hostname:
        raise RegistryError('endpoint_invalid', f'{where} must be a plain http URL')
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise RegistryError('endpoint_invalid', f'{where} must not carry credentials, query or '
                                                'fragment components')
    if allowed_hosts and parsed.hostname not in allowed_hosts:
        raise RegistryError('endpoint_not_allowlisted',
                            f'{where} host {parsed.hostname!r} is not in the service allowlist')
    if parsed.port is None:
        raise RegistryError('endpoint_invalid', f'{where} must state an explicit port')
    return endpoint


@dataclass(frozen=True)
class ToolBinding:
    service_id: str
    connection_ref: str
    endpoint: str
    status_endpoint: str
    credential_id: str
    published_name: str
    upstream_name: str
    panel_service: str
    panel_action: str
    description: str
    mutation: bool
    result_projection: dict | None
    input_schema: dict
    output_schema: dict
    published_output_schema: dict
    upstream_description: str
    schema_hash: str
    review_required: bool = False

    def as_document(self) -> dict:
        return {'service_id': self.service_id, 'connection_ref': self.connection_ref,
                'endpoint': self.endpoint, 'status_endpoint': self.status_endpoint,
                'credential_id': self.credential_id, 'published_name': self.published_name,
                'upstream_name': self.upstream_name, 'panel_service': self.panel_service,
                'panel_action': self.panel_action, 'description': self.description,
                'mutation': self.mutation, 'result_projection': self.result_projection,
                'input_schema': self.input_schema, 'output_schema': self.output_schema,
                'published_output_schema': self.published_output_schema,
                'upstream_description': self.upstream_description, 'schema_hash': self.schema_hash,
                'review_required': self.review_required}


@dataclass(frozen=True)
class ServiceEntry:
    service_id: str
    connection_ref: str
    endpoint: str
    status_endpoint: str
    credential_id: str
    health: str
    tools: tuple


class ActiveRegistry:
    """Lookup view over one published revision document."""

    def __init__(self, revision, document, document_hash_value=None):
        self.revision = revision
        self.document = document
        self.document_hash = document_hash_value or document_hash(document)
        self.services = {}
        self.tools = {}
        for entry in document.get('services', []):
            bindings = []
            for raw in entry.get('tools', []):
                binding = ToolBinding(
                    service_id=entry['service_id'], connection_ref=entry['connection_ref'],
                    endpoint=entry['endpoint'], status_endpoint=entry['status_endpoint'],
                    credential_id=entry['credential_id'], published_name=raw['published_name'],
                    upstream_name=raw['upstream_name'], panel_service=raw['panel_service'],
                    panel_action=raw['panel_action'], description=raw['description'],
                    mutation=bool(raw['mutation']), result_projection=raw.get('result_projection'),
                    input_schema=raw['input_schema'], output_schema=raw['output_schema'],
                    published_output_schema=raw['published_output_schema'],
                    upstream_description=raw.get('upstream_description', ''),
                    schema_hash=raw['schema_hash'],
                    review_required=bool(raw.get('review_required')))
                bindings.append(binding)
                self.tools[binding.published_name] = binding
            self.services[entry['service_id']] = ServiceEntry(
                service_id=entry['service_id'], connection_ref=entry['connection_ref'],
                endpoint=entry['endpoint'], status_endpoint=entry['status_endpoint'],
                credential_id=entry['credential_id'], health=entry.get('health', 'unknown'),
                tools=tuple(bindings))

    def binding(self, published_name):
        return self.tools.get(published_name)

    def service(self, service_id):
        return self.services.get(service_id)

    def summary(self):
        return {'revision': self.revision, 'documentHash': self.document_hash,
                'services': [{'serviceId': entry.service_id, 'health': entry.health,
                              'connectionRef': entry.connection_ref,
                              'tools': [tool.published_name for tool in entry.tools]}
                             for entry in self.services.values()]}


class ServiceRegistry:
    def __init__(self, allowlist, credentials, operations, upstream, *, allowed_hosts=None,
                 clock=None):
        self.allowlist = allowlist
        self.credentials = credentials
        self.operations = operations
        self.upstream = upstream
        self.allowed_hosts = set(allowed_hosts or [])
        self.clock = clock

    # -- allowlist -------------------------------------------------------------------
    @classmethod
    def load_allowlist(cls, path, *, allowed_hosts=None):
        document = json.loads(open(path, encoding='utf-8').read())
        return cls.validate_allowlist(document, allowed_hosts=allowed_hosts)

    @staticmethod
    def validate_allowlist(document, *, allowed_hosts=None):
        if not isinstance(document, dict) or document.get('version') != 1:
            raise RegistryError('allowlist_invalid', 'allowlist version must be 1')
        services = document.get('services')
        if not isinstance(services, list) or not 1 <= len(services) <= MAX_SERVICES:
            raise RegistryError('allowlist_invalid', f'allowlist needs 1–{MAX_SERVICES} services')
        seen = set()
        for entry in services:
            service_id = entry.get('service_id')
            if not isinstance(service_id, str) or not SERVICE_ID.fullmatch(service_id) \
                    or service_id in seen:
                raise RegistryError('allowlist_invalid', f'invalid or duplicate service id '
                                                          f'{service_id!r}')
            seen.add(service_id)
            _validate_endpoint(entry.get('endpoint'), allowed_hosts or set(),
                               f'{service_id}.endpoint')
            _validate_endpoint(entry.get('status_endpoint'), allowed_hosts or set(),
                               f'{service_id}.status_endpoint')
            for field in ('connection_ref', 'credential_id'):
                if not isinstance(entry.get(field), str) or \
                        not IDENTIFIER.fullmatch(entry[field]):
                    raise RegistryError('allowlist_invalid', f'{service_id}.{field} is invalid')
            tools = entry.get('tools')
            if not isinstance(tools, list) or not 1 <= len(tools) <= MAX_TOOLS_PER_SERVICE:
                raise RegistryError('allowlist_invalid',
                                    f'{service_id} needs 1–{MAX_TOOLS_PER_SERVICE} tool mappings')
            published = set()
            for tool in tools:
                name = tool.get('published_name')
                if not isinstance(name, str) or not TOOL_NAME.fullmatch(name) or name in published:
                    raise RegistryError('allowlist_invalid',
                                        f'{service_id} has an invalid or duplicate published name')
                published.add(name)
                if not isinstance(tool.get('upstream_name'), str) or \
                        not TOOL_NAME.fullmatch(tool['upstream_name']):
                    raise RegistryError('allowlist_invalid', f'{name}.upstream_name is invalid')
                for field in ('panel_service', 'panel_action'):
                    if not isinstance(tool.get(field), str) or not IDENTIFIER.fullmatch(tool[field]):
                        raise RegistryError('allowlist_invalid', f'{name}.{field} is invalid')
                description = tool.get('reviewed_description')
                if not isinstance(description, str) or not 1 <= len(description) <= 1000:
                    raise RegistryError('allowlist_invalid',
                                        f'{name} needs an operator-reviewed description')
        return document

    def service_entries(self):
        return self.allowlist['services']

    # -- discovery -------------------------------------------------------------------
    async def discover(self):
        """Read every allowlisted service's own tool list. A failure is recorded, not hidden."""
        result = {}
        for entry in self.service_entries():
            service_id = entry['service_id']
            try:
                tools = await self.upstream.list_tools(entry['endpoint'], service_id,
                                                       credential_id=entry['credential_id'])
                result[service_id] = {'health': 'ready', 'tools': tools, 'detail': None}
            except UpstreamError as exc:
                result[service_id] = {'health': 'unavailable', 'tools': [],
                                      'detail': f'{exc.code}: {exc.detail or ""}'.strip()}
            except Exception as exc:  # noqa: BLE001
                result[service_id] = {'health': 'unavailable', 'tools': [],
                                      'detail': f'{type(exc).__name__}: {exc}'}
        return result

    # -- revision --------------------------------------------------------------------
    def build_revision(self, discovery, *, previous=None, approve_drift=False):
        services = []
        for entry in self.service_entries():
            service_id = entry['service_id']
            found = discovery.get(service_id, {'health': 'unavailable', 'tools': []})
            available = {tool['name']: tool for tool in found['tools']}
            bindings = []
            for mapping in entry['tools']:
                upstream = available.get(mapping['upstream_name'])
                if upstream is None:
                    # A mapping whose upstream tool disappeared is published as unavailable, so the
                    # client sees the tool without it and a call is refused instead of dispatched.
                    bindings.append(self._binding(entry, mapping, None,
                                                  review_required=True).as_document()
                                   | {'health': 'missing'})
                    continue
                schema_hash = sha256(canonical({
                    'input': upstream.get('inputSchema'),
                    'output': upstream.get('outputSchema')}).encode()).hexdigest()
                previous_hash = previous.schema_hash if previous else None
                drift = previous_hash is not None and previous_hash != schema_hash
                binding = self._binding(entry, mapping, upstream,
                                        review_required=drift and not approve_drift)
                document = binding.as_document() | {'health': 'ready', 'schemaChanged': drift}
                bindings.append(document)
            services.append({'service_id': service_id,
                             'connection_ref': entry['connection_ref'],
                             'endpoint': entry['endpoint'],
                             'status_endpoint': entry['status_endpoint'],
                             'credential_id': entry['credential_id'],
                             'health': found['health'],
                             'detail': found.get('detail'),
                             'tools': bindings})
        document = {'version': 1, 'profile': {'protocol': '2025-11-25',
                                              'transport': 'streamable-http-json'},
                    'services': services}
        return document

    @staticmethod
    def _binding(entry, mapping, upstream, *, review_required=False):
        input_schema = _check_schema(
            (upstream or {}).get('inputSchema') or {'type': 'object', 'properties': {},
                                                    'additionalProperties': False},
            f'{mapping["published_name"]}.inputSchema')
        output_schema = _check_schema(
            (upstream or {}).get('outputSchema') or {'type': 'object'},
            f'{mapping["published_name"]}.outputSchema')
        published_output = _published_output_schema(output_schema)
        schema_hash = sha256(canonical({'input': input_schema,
                                        'output': output_schema}).encode()).hexdigest()
        return ToolBinding(
            service_id=entry['service_id'], connection_ref=entry['connection_ref'],
            endpoint=entry['endpoint'], status_endpoint=entry['status_endpoint'],
            credential_id=entry['credential_id'], published_name=mapping['published_name'],
            upstream_name=mapping['upstream_name'], panel_service=mapping['panel_service'],
            panel_action=mapping['panel_action'], description=mapping['reviewed_description'],
            mutation=bool(mapping.get('mutation')), result_projection=mapping.get(
                'result_projection'),
            input_schema=input_schema, output_schema=output_schema,
            published_output_schema=published_output,
            upstream_description=(upstream or {}).get('description', '') or '',
            schema_hash=schema_hash, review_required=review_required)

    def publish(self, document, *, source='bootstrap', created_by='operator-local'):
        return self.operations.publish_registry(document, document_hash(document), source,
                                                created_by)

    def active(self):
        row = self.operations.active_registry()
        if row is None:
            return None
        document = row['document']
        if isinstance(document, str):
            document = json.loads(document)
        return ActiveRegistry(row['revision'], document, row.get('document_hash'))

    def record_health(self, discovery):
        for entry in self.service_entries():
            found = discovery.get(entry['service_id'], {})
            self.operations.record_service_health(
                entry['service_id'], entry['connection_ref'], found.get('health', 'unknown'),
                {'detail': found.get('detail'),
                 'tools': [tool['name'] for tool in found.get('tools', [])]})


def _published_output_schema(upstream_output):
    """Client-visible output schema: the reviewed business fields plus the Gate envelope.

    The MCP SDK validates ``outputSchema`` as a JSON Schema object with a ``type``, so the published
    schema is one object rather than a union. The business fields of the upstream result are carried
    over unchanged and the refusal fields are added; the envelope fields are required in every case.
    Which business fields a *successful* result must contain stays documented per tool in
    ``contracts/mcp-tool-contracts.md`` and is enforced on the upstream result before disclosure, so
    weakening the union does not weaken the check.
    """
    properties = dict(upstream_output.get('properties') or {})
    business = {name: schema for name, schema in properties.items()
                if name not in UPSTREAM_ENVELOPE}
    refusal_properties = {name: schema for name, schema in REFUSAL_SCHEMA['properties'].items()
                          if name not in ('status', 'service', 'tool', 'operation_id',
                                          'service_operation_id', 'receipt_id', 'replayed',
                                          'decision', 'effect', 'disclosure')}
    return {'type': 'object',
            'properties': {**business, **GATE_FIELDS, **refusal_properties},
            'required': ['status', 'operation_id', 'disclosure', 'decision', 'effect'],
            'additionalProperties': False,
            'description': 'A successful result carries the reviewed business fields; a refusal '
                           'carries status, a typed error and no business content.'}


def visibility(policy, principal_id, binding):
    """Explicit visibility fixture: the policy says something about this subject and this tool.

    A tool with no matching rule is not in the caller's catalog, so a guessed name of a hidden tool
    is answered exactly like an unknown one. The reaction is deliberately ignored here: a declared
    refusal keeps a tool visible and callable so that the refusal is attributed to policy rather than
    to the catalog. Conditions are not evaluated either - the plan does not claim a universal
    analysis of arbitrary conditions at catalog time, and every call is checked in full anyway.
    """
    return any(rule['service'] == binding.panel_service
               and rule['action'] in (binding.panel_action, '*')
               and rule['subject'] in ('*', principal_id)
               for rule in policy.get('rules', []))


def visible_bindings(registry, policy, principal_id):
    return [binding for binding in registry.tools.values()
            if visibility(policy, principal_id, binding)]
