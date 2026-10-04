"""ExecutionCoordinator: one client operation from admission to a durable outcome.

The order below is the contract, not an implementation detail:

1. read the demonstration run and the admission flag;
2. take an immutable policy/catalog snapshot and a registry revision;
3. create the durable claim (or find the existing one) under the shared advisory lock;
4. compute rate context and evaluate the exact policy snapshot;
5. refuse before the network, or re-validate the processed arguments and reserve a slot;
6. write ``dispatch_started`` *before* sending anything;
7. make the one upstream call the operation is allowed to make;
8. validate the result, apply output controls, project per-resource access and store the sanitized
   client representation;
9. audit the decision, the effect and the disclosure separately.

A timeout or a cancellation after step 6 is never reported as "no effect": the operation stays
visible as ``outcome_unknown`` until a receipt probe, a restart reconciliation or an operator fence
resolves it.
"""
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import hmac
import json
import time
import uuid

import anyio
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from . import panel_engine
from .mcp_upstream import UpstreamError
from .policy_reader import PolicyUnavailable
from .service_registry import visibility
from .storage.operations import (STATUS_BLOCKED, STATUS_CLAIMED, STATUS_DISPATCH_STARTED,
                                 STATUS_FAILED, STATUS_SUCCEEDED, STATUS_UNKNOWN,
                                 IdempotencyConflict, OperationsError)

TOTAL_DEADLINE_MS = 8000
UPSTREAM_DEADLINE_MS = 5000
CONNECT_TIMEOUT_MS = 1000
MAX_ARGUMENT_BYTES = 512 * 1024
MAX_RESULT_BYTES = 512 * 1024
LEASE_SECONDS = 30
MAX_CONCURRENT_PER_SERVICE = 4
MAX_ATTEMPTS_PER_MINUTE = 60

DECISION_ALLOW = 'allow'


class ToolCallRejected(Exception):
    """A protocol-level refusal: no operation was created and nothing was dispatched."""

    def __init__(self, code, message, *, data=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False)


def _now():
    return datetime.now(timezone.utc)


def _ms(started):
    return round((time.perf_counter() - started) * 1000, 3)


class ExecutionCoordinator:
    def __init__(self, *, operations, policy_reader, registry_provider, upstream, salt,
                 limits=None, clock=None):
        self.operations = operations
        self.policy_reader = policy_reader
        self.registry_provider = registry_provider
        self.upstream = upstream
        self.salt = salt.encode() if isinstance(salt, str) else salt
        self.limits = {**_DEFAULT_LIMITS, **(limits or {})}
        self.clock = clock or _now

    # -- helpers ---------------------------------------------------------------------
    def fingerprint(self, binding, arguments) -> str:
        return hmac.new(self.salt, canonical({'service': binding.service_id,
                                              'tool': binding.upstream_name,
                                              'arguments': arguments}).encode(),
                        sha256).hexdigest()

    @staticmethod
    def _refusal(*, binding, operation_id, status, decision, effect, disclosure, code, message,
                 reason=None, retry_after_ms=None, replayed=False, receipt_id=None,
                 resource_id=None):
        payload = {'status': status, 'service': binding.service_id,
                   'tool': binding.published_name, 'operation_id': operation_id,
                   'service_operation_id': None, 'receipt_id': receipt_id,
                   'resource_id': resource_id, 'replayed': replayed,
                   'decision': decision, 'effect': effect, 'disclosure': disclosure,
                   'reason': reason or message,
                   'error': {'code': code, 'message': message}}
        if retry_after_ms is not None:
            payload['reason'] = f'{payload["reason"]} Retry after {retry_after_ms} ms.'
        return payload

    # -- entry point -------------------------------------------------------------------
    async def execute(self, *, principal, binding, arguments, client_operation_key, request_id):
        started = time.perf_counter()
        deadline = started + (self.limits.get('total_deadline_ms', TOTAL_DEADLINE_MS) / 1000.0)

        state = await _thread(self.operations.run_state)
        if not state.get('admission_open', True):
            raise ToolCallRejected('admission_closed',
                                   'Admission is closed for a demonstration reset; try again after '
                                   'the operator reopens it')
        run_id = state['run_id']

        if binding.review_required:
            return self._refusal(
                binding=binding, operation_id=None, status='denied', decision='block',
                effect='not_started', disclosure='none', code='tool_review_required',
                message='This tool is not published: its schema changed and awaits operator review')

        if not isinstance(arguments, dict):
            raise ToolCallRejected('invalid_arguments', 'arguments must be an object')
        arguments = json.loads(canonical(arguments))
        if len(canonical(arguments).encode('utf-8')) > self.limits.get('max_argument_bytes',
                                                                       MAX_ARGUMENT_BYTES):
            raise ToolCallRejected('arguments_too_large', 'arguments exceed the accepted size')
        try:
            # The published schema is enforced before an operation exists, so a malformed call never
            # reaches a service and never produces an operation row.
            _validate(binding.input_schema, arguments, 'arguments')
        except ValidationError as exc:
            path = '.'.join(str(part) for part in exc.absolute_path) or '(root)'
            raise ToolCallRejected('invalid_arguments',
                                   f'arguments do not satisfy the published schema at {path}: '
                                   f'{exc.message}') from exc
        if binding.mutation and not client_operation_key:
            raise ToolCallRejected(
                'operation_key_required',
                'This mutation needs a stable client operation key in '
                'params._meta["actiongate.demo/operation_key"]; without it a retry could execute '
                'the change twice')
        if not client_operation_key:
            client_operation_key = 'auto-' + uuid.uuid4().hex

        policy = await _thread(self.policy_reader.read)
        registry = self.registry_provider()
        if registry is None:
            raise ToolCallRejected('registry_unavailable',
                                   'No MCP registry revision is published yet')
        visible = visibility(policy['policy'], principal.id, binding)
        fingerprint = self.fingerprint(binding, arguments)
        try:
            claim = await _thread(self.operations.claim, {
                'demo_run_id': run_id, 'principal_id': principal.id,
                'client_operation_key': client_operation_key, 'request_fingerprint': fingerprint,
                'request_id': request_id, 'published_tool': binding.published_name,
                'upstream_tool': binding.upstream_name, 'service_id': binding.service_id,
                'panel_service': binding.panel_service, 'panel_action': binding.panel_action,
                'registry_revision': registry.revision,
                'policy_version': policy['policyVersion'], 'policy_hash': policy['policyHash']})
        except IdempotencyConflict:
            return self._refusal(
                binding=binding, operation_id=None, status='denied', decision='block',
                effect='not_started', disclosure='none', code='idempotency_conflict',
                message='This client operation key was already used with different content; '
                        'start a new request instead of reusing the key')
        except OperationsError as exc:
            raise ToolCallRejected(exc.code, 'Admission closed before the operation was claimed') from exc
        row = dict(claim['row'])
        # PostgreSQL returns the identifier as a UUID; every representation that leaves this process
        # is JSON, so the value is normalized once here.
        row['id'] = str(row['id'])
        operation_id = row['id']
        if not claim['created']:
            return await self._replay(row, policy, binding, principal, arguments, request_id)
        if not visible:
            # A guessed name of a tool this principal has no rule for is answered exactly like an
            # unknown name: the same protocol error, no dispatch, and an audited refusal that the
            # caller cannot use to probe the catalog.
            finished = await _thread(self.operations.finish, row['id'], {
                'status': STATUS_BLOCKED, 'decision': 'block',
                'reason': 'the caller has no rule for this tool', 'disclosure': 'none',
                'error_code': 'unknown_tool', 'total_ms': _ms(started)})
            await self._record_attempt(row, binding, outcome='not_visible', admitted=False)
            await self._audit(finished, policy, principal, request_id, decision='block',
                              effect='not_started', disclosure='none',
                              detail={'hiddenTool': True})
            raise ToolCallRejected('unknown_tool', 'Unknown or unavailable tool')

        rate = await _thread(self.operations.rate_context, principal.id, fingerprint)
        if rate['attempts'] >= self.limits.get('max_attempts_per_minute', MAX_ATTEMPTS_PER_MINUTE):
            return await self._finish_refusal(
                row=row, binding=binding, policy=policy, principal=principal, request_id=request_id,
                decision='throttle', status='throttled', code='rate_limited',
                message='Too many calls in the current minute at the Gate; nothing was dispatched',
                reason='gate rate limit', retry_after_ms=60000 // 2, started=started)

        context = {'rpm': rate['attempts'] + 1, 'similar': rate['similar'] + 1,
                   'tokens_used': 0, 'tokens_requested': 0}
        request = _tool_request(principal.id, binding, arguments)
        try:
            evaluation = panel_engine.evaluate(policy['policy'], request, context=context)
        except panel_engine.PanelValidationError as exc:
            raise ToolCallRejected('policy_invalid', f'{exc.code}: {exc.message}') from exc

        admission_ms = _ms(started)
        if evaluation['decision'] in ('block', 'throttle'):
            decision = evaluation['decision']
            return await self._finish_refusal(
                row=row, binding=binding, policy=policy, principal=principal, request_id=request_id,
                decision=decision, status='denied' if decision == 'block' else 'throttled',
                code='policy_denied' if decision == 'block' else 'policy_throttled',
                message=evaluation.get('triggerDetail') or f'Policy decision: {decision}',
                reason=f"check {evaluation.get('trigger')} ({evaluation.get('triggerType')})",
                retry_after_ms=evaluation.get('throttle') or None, started=started,
                admission_ms=admission_ms, evaluation=evaluation)

        processed = evaluation.get('processedParams')
        if not isinstance(processed, dict):
            return await self._finish_refusal(
                row=row, binding=binding, policy=policy, principal=principal, request_id=request_id,
                decision='block', status='denied', code='redaction_breaks_contract',
                message='The admitted arguments could not be reconstructed after content controls; '
                        'nothing was dispatched',
                reason='processed arguments unavailable', started=started,
                admission_ms=admission_ms)

        try:
            _validate(binding.input_schema, processed, 'arguments')
        except ValidationError as exc:
            return await self._finish_refusal(
                row=row, binding=binding, policy=policy, principal=principal, request_id=request_id,
                decision='block', status='denied', code='redaction_breaks_contract',
                message=f'The processed arguments no longer satisfy the published schema '
                        f'({exc.message}); nothing was dispatched',
                reason='schema re-validation failed', started=started, admission_ms=admission_ms)
        # Access is re-checked against the exact arguments that would be sent.
        recheck = panel_engine.evaluate(policy['policy'], {**request, 'params': processed},
                                        context={'rpm': 0, 'similar': 0})
        if recheck['decision'] in ('block', 'throttle'):
            return await self._finish_refusal(
                row=row, binding=binding, policy=policy, principal=principal, request_id=request_id,
                decision=recheck['decision'], status='denied', code='policy_denied',
                message='The processed arguments are refused by the access rules; nothing was '
                        'dispatched',
                reason='final access recheck', started=started, admission_ms=admission_ms)

        limit = self.limits.get('max_concurrent_per_service', MAX_CONCURRENT_PER_SERVICE)
        in_flight = await _thread(self.operations.open_reservations, binding.service_id, run_id)
        if in_flight >= limit:
            return await self._finish_refusal(
                row=row, binding=binding, policy=policy, principal=principal, request_id=request_id,
                decision='throttle', status='throttled', code='concurrency_limit',
                message=f'{binding.service_id} already has {in_flight} operations in flight '
                        f'(limit {limit})',
                reason='concurrency limit reached', retry_after_ms=1000, started=started,
                admission_ms=admission_ms)
        reserved = await _thread(self.operations.reserve, {
            'operation_id': operation_id, 'service_id': binding.service_id, 'demo_run_id': run_id,
            'principal_id': principal.id})
        if not reserved:
            return await self._finish_refusal(
                row=row, binding=binding, policy=policy, principal=principal, request_id=request_id,
                decision='throttle', status='throttled', code='concurrency_limit',
                message='The service already has the maximum number of operations in flight',
                reason='concurrency reservation refused', retry_after_ms=1000, started=started,
                admission_ms=admission_ms)

        lease = uuid.uuid4().hex
        upstream_operation_id = 'op-' + uuid.uuid4().hex
        await _thread(self.operations.mark_dispatch_started, operation_id, lease, LEASE_SECONDS,
                      upstream_operation_id)
        budget = min(self.limits.get('upstream_deadline_ms', UPSTREAM_DEADLINE_MS) / 1000.0,
                     max(0.05, deadline - time.perf_counter()))
        upstream_started = time.perf_counter()
        try:
            result = await self.upstream.call_tool(
                binding.endpoint, binding.service_id, binding.upstream_name, processed,
                {'operation_id': upstream_operation_id, 'demo_run_id': run_id,
                 'actor': principal.id},
                credential_id=binding.credential_id, deadline=budget)
        except UpstreamError as exc:
            return await self._upstream_failure(
                row=row, binding=binding, policy=policy, principal=principal, request_id=request_id,
                exc=exc, upstream_operation_id=upstream_operation_id, started=started,
                admission_ms=admission_ms, upstream_ms=_ms(upstream_started))
        upstream_ms = _ms(upstream_started)
        return await self._complete(
            row=row, binding=binding, policy=policy, principal=principal, request_id=request_id,
            result=result, upstream_operation_id=upstream_operation_id, arguments=processed,
            started=started, admission_ms=admission_ms, upstream_ms=upstream_ms)

    # -- terminal paths ------------------------------------------------------------------
    async def _finish_refusal(self, *, row, binding, policy, principal, request_id, decision,
                              status, code, message, reason, started, admission_ms=None,
                              retry_after_ms=None, evaluation=None):
        fields = {'status': STATUS_BLOCKED, 'decision': decision, 'reason': reason,
                  'disclosure': 'none', 'error_code': code,
                  'admission_ms': admission_ms if admission_ms is not None else _ms(started),
                  'total_ms': _ms(started), 'upstream_operation_id': None}
        finished = await _thread(self.operations.finish, row['id'], fields)
        await _thread(self.operations.release, row['id'], 'refused before dispatch')
        await self._record_attempt(row, binding, outcome=code, admitted=False)
        await self._audit(finished, policy, principal, request_id, decision=decision,
                          effect='not_started', disclosure='none',
                          detail={'code': code, 'reason': reason,
                                  'retryAfterMs': retry_after_ms,
                                  'trigger': evaluation.get('trigger') if evaluation else None})
        return self._refusal(binding=binding, operation_id=row['id'], status=status,
                             decision=decision, effect='not_started', disclosure='none',
                             code=code, message=message, reason=reason,
                             retry_after_ms=retry_after_ms)

    async def _upstream_failure(self, *, row, binding, policy, principal, request_id, exc,
                                upstream_operation_id, started, admission_ms, upstream_ms):
        if not exc.dispatched:
            # The connection was never established, so no effect exists and none can appear later.
            fields = {'status': STATUS_FAILED, 'decision': 'allow',
                      'reason': f'{exc.code}: upstream could not be reached',
                      'disclosure': 'none', 'error_code': exc.code,
                      'upstream_operation_id': upstream_operation_id,
                      'admission_ms': admission_ms, 'upstream_ms': upstream_ms,
                      'total_ms': _ms(started)}
            finished = await _thread(self.operations.finish, row['id'], fields)
            await _thread(self.operations.release, row['id'], 'upstream unreachable')
            await self._record_attempt(row, binding, outcome=exc.code, admitted=True)
            await self._audit(finished, policy, principal, request_id, decision='allow',
                              effect='no_effect', disclosure='none', detail={'code': exc.code})
            return self._refusal(binding=binding, operation_id=row['id'], status='failed',
                                 decision='allow', effect='no_effect', disclosure='none',
                                 code=exc.code,
                                 message='The service could not be reached; no effect was created')

        # The request may have been executed. The client is told exactly that and nothing more: the
        # operation stays visible as unknown, its reservation is kept, and it is never re-sent. The
        # receipt is read by the operator reconciliation path (``mcp_ops reconcile``) or after a
        # restart, not silently on the client's own request path, so a lost answer is never presented
        # as a completed one.
        fields = {'status': STATUS_UNKNOWN, 'decision': 'allow',
                  'reason': f'{exc.code}: the outcome is unknown',
                  'disclosure': 'none', 'error_code': exc.code,
                  'upstream_operation_id': upstream_operation_id,
                  'admission_ms': admission_ms, 'upstream_ms': upstream_ms,
                  'total_ms': _ms(started)}
        finished = await _thread(self.operations.finish, row['id'], fields)
        await self._record_attempt(row, binding, outcome=exc.code, admitted=True)
        await self._audit(finished, policy, principal, request_id, decision='allow',
                          effect='unknown', disclosure='none',
                          detail={'code': exc.code, 'lease': row.get('owner_lease')})
        return self._refusal(binding=binding, operation_id=row['id'], status='outcome_unknown',
                             decision='allow', effect='unknown', disclosure='none',
                             code=exc.code,
                             message='The request may have reached the service and the answer was '
                                     'lost. It is not retried automatically; run reconcile to read '
                                     'the service receipt')

    async def _complete(self, *, row, binding, policy, principal, request_id, result,
                        upstream_operation_id, arguments, started, admission_ms, upstream_ms):
        output_started = time.perf_counter()
        structured = result.structured if isinstance(result.structured, dict) else None
        business = _business_fields(structured) if structured else {}
        receipt_id = (structured or {}).get('receipt_id')
        resource_id = (structured or {}).get('resource_id') or binding_resource(binding, arguments)
        before_version, after_version = _versions(structured or {})

        if result.is_error:
            error = (structured or {}).get('error') or {}
            code = error.get('code') or 'service_error'
            message = error.get('message') or 'The service refused the operation'
            fields = {'status': STATUS_FAILED, 'decision': 'allow', 'reason': code,
                      'disclosure': 'none', 'error_code': code, 'receipt_id': receipt_id,
                      'resource_id': resource_id, 'upstream_operation_id': upstream_operation_id,
                      'before_version': before_version, 'after_version': after_version,
                      'bytes_out': result.bytes_out, 'admission_ms': admission_ms,
                      'upstream_ms': upstream_ms, 'output_ms': _ms(output_started),
                      'total_ms': _ms(started)}
            finished = await _thread(self.operations.finish, row['id'], fields)
            await _thread(self.operations.release, row['id'], 'service refused')
            await self._record_attempt(row, binding, outcome='service_error', admitted=True)
            await self._audit(finished, policy, principal, request_id, decision='allow',
                              effect='no_effect', disclosure='none',
                              detail={'code': code, 'businessRefusal': True})
            return self._refusal(binding=binding, operation_id=row['id'], status='failed',
                                 decision='allow', effect='no_effect', disclosure='none',
                                 code=code, message=message, reason='service refusal')

        disclosure, cleaned, cleaned_document, output_detail = self._apply_output_controls(
            binding=binding, policy=policy, principal=principal, structured=structured,
            result=result)

        if disclosure == 'withheld' and not receipt_id:
            # A malformed payload is not proof of commit. Query the authenticated
            # receipt channel once; never dispatch again to recover an answer.
            confirmed = await self._probe_receipt(row, binding, upstream_operation_id)
            if confirmed is None:
                return await self._upstream_failure(
                    row=row, binding=binding, policy=policy, principal=principal,
                    request_id=request_id, upstream_operation_id=upstream_operation_id,
                    exc=UpstreamError('invalid_upstream_result', dispatched=True),
                    started=started, admission_ms=admission_ms, upstream_ms=upstream_ms)
            receipt_id = confirmed['receipt_id']
            resource_id = confirmed.get('resource_id')

        cleaned_document = await self._project(binding, policy, principal, cleaned_document)

        envelope = {'status': 'succeeded', 'service': binding.service_id,
                    'tool': binding.published_name, 'operation_id': row['id'],
                    'service_operation_id': upstream_operation_id, 'receipt_id': receipt_id,
                    'replayed': False, 'disclosure': disclosure, 'decision': 'allow',
                    'effect': 'succeeded', 'policy_version': policy['policyVersion'],
                    'resource_id': resource_id}
        if disclosure == 'withheld':
            # The effect happened; the content is not disclosed in any representation.
            client_result = {**envelope,
                             'reason': output_detail.get('reason', 'output withheld by policy')}
        else:
            if cleaned_document is not None:
                business = _business_fields(cleaned_document)
            client_result = {**envelope, **business}

        fields = {'status': STATUS_SUCCEEDED, 'decision': 'allow', 'reason': None,
                  'disclosure': disclosure, 'receipt_id': receipt_id, 'resource_id': resource_id,
                  'upstream_operation_id': upstream_operation_id,
                  'before_version': before_version, 'after_version': after_version,
                  'result': client_result, 'error_code': None, 'bytes_out': result.bytes_out,
                  'admission_ms': admission_ms, 'upstream_ms': upstream_ms,
                  'output_ms': _ms(output_started), 'total_ms': _ms(started)}
        finished = await _thread(self.operations.finish, row['id'], fields)
        await _thread(self.operations.release, row['id'], 'terminal outcome')
        await self._record_attempt(row, binding, outcome='succeeded', admitted=True)
        await self._audit(finished, policy, principal, request_id, decision='allow',
                          effect='succeeded', disclosure=disclosure,
                          detail={'output': output_detail, 'bytesOut': result.bytes_out})
        return client_result

    # -- output controls ------------------------------------------------------------------
    @staticmethod
    def _apply_output_controls(*, binding, policy, principal, structured, result):
        """One cleaned object feeds every representation, or nothing is disclosed."""
        if structured is None:
            return 'withheld', None, None, {'reason': 'the service result was not structured JSON'}
        if result.bytes_out > MAX_RESULT_BYTES:
            return 'withheld', None, None, {'reason': 'the service result exceeded the size limit'}
        try:
            _validate(binding.output_schema, structured, 'result')
        except ValidationError as exc:
            return 'withheld', None, None, {
                'reason': 'the service result did not match its published schema'}
        text = canonical(structured)
        try:
            output = panel_engine.evaluate(policy['policy'], {
                'agent': principal.id, 'dir': 'output',
                'target': panel_engine.TOOL_RESULT_TARGET, 'text': text,
                'params': {}, 'meta': {}}, context={})
        except panel_engine.PanelValidationError as exc:
            return 'withheld', None, None, {'reason': f'output evaluation failed: {exc.code}'}
        if output['decision'] in ('block', 'throttle'):
            return 'withheld', None, None, {
                'reason': 'output withheld by policy',
                'trigger': output.get('trigger'), 'triggerDetail': output.get('triggerDetail')}
        processed = output.get('processed')
        if output['decision'] == 'redact' or processed != text:
            try:
                candidate = json.loads(processed)
            except (TypeError, ValueError):
                return 'withheld', None, None, {
                    'reason': 'the redacted output is no longer valid JSON'}
            try:
                _validate(binding.output_schema, candidate, 'redacted result')
            except ValidationError:
                return 'withheld', None, None, {
                    'reason': 'the redacted output broke the published schema'}
            return 'redacted', candidate, candidate, {'redacted': True,
                                                      'trigger': output.get('trigger')}
        return 'full', structured, structured, {'redacted': False}

    async def _project(self, binding, policy, principal, document):
        """Apply per-resource access to the data of a result, never to its envelope."""
        projection = binding.result_projection
        if not projection or document is None:
            return document
        if projection.get('kind') != 'filter_by_access':
            return document
        items = document.get(projection['list_field'])
        if not isinstance(items, list):
            return document
        allowed, hidden = [], 0
        for item in items:
            if not isinstance(item, dict):
                continue
            candidate = _tool_request(
                principal.id, binding,
                {projection['item_field']: item.get(projection['item_field'])},
                action=projection.get('panel_action', binding.panel_action))
            try:
                decision = panel_engine.evaluate(policy['policy'], candidate,
                                                 context={'rpm': 0, 'similar': 0})['decision']
            except panel_engine.PanelValidationError:
                decision = 'block'
            if decision in ('block', 'throttle'):
                hidden += 1
                continue
            allowed.append(item)
        if hidden:
            # The count of withheld entries is reported; their identifiers are not.
            document = dict(document)
            document[projection['list_field']] = allowed
            if 'count' in document:
                document['count'] = len(allowed)
            document['filtered_count'] = hidden
        return document

    # -- replay, probing and audit ------------------------------------------------------
    async def _replay(self, row, policy, binding, principal, arguments, request_id):
        request = _tool_request(principal.id, binding, arguments)
        try:
            current = panel_engine.evaluate(policy['policy'], request,
                                            context={'rpm': 0, 'similar': 0})
        except panel_engine.PanelValidationError:
            current = {'decision': 'block'}
        if row['status'] == STATUS_SUCCEEDED and row.get('result_document') is not None \
                and current['decision'] not in ('block', 'throttle'):
            document = row['result_document']
            if isinstance(document, str):
                document = json.loads(document)
            return {**document, 'replayed': True}
        if row['status'] == STATUS_SUCCEEDED:
            return self._refusal(
                binding=binding, operation_id=row['id'], status='succeeded', decision='allow',
                effect='succeeded', disclosure='withheld', code='result_not_replayable',
                message='This operation already succeeded and its content is not disclosed again '
                        'under the current policy' if current['decision'] in ('block', 'throttle')
                        else 'This operation already succeeded and its content was not retained',
                reason='replay without disclosure', replayed=True)
        if row['status'] in (STATUS_BLOCKED, STATUS_FAILED):
            return self._refusal(
                binding=binding, operation_id=row['id'],
                status='denied' if row['status'] == STATUS_BLOCKED else 'failed',
                decision=row.get('decision') or 'block',
                effect='not_started' if row['status'] == STATUS_BLOCKED else 'no_effect',
                disclosure='none', code=row.get('error_code') or 'previous_refusal',
                message='This operation key already has a recorded decision; it is not executed '
                        'again',
                reason=row.get('reason'), replayed=True)
        return self._refusal(
            binding=binding, operation_id=row['id'], status='outcome_unknown', decision='allow',
            effect='unknown', disclosure='none', code='outcome_unknown',
            message='This operation is not finished; it is not re-sent automatically',
            reason=row.get('reason'), replayed=True)

    async def _probe_receipt(self, row, binding, upstream_operation_id):
        """One bounded read-only probe after a lost response. Never a second dispatch."""
        try:
            status = await self.upstream.operation_status(
                binding.status_endpoint, binding.service_id, upstream_operation_id,
                credential_id=binding.credential_id)
        except UpstreamError:
            return None
        if status.get('status') != 'committed':
            return None
        receipt = status.get('receipt') or {}
        if (status.get('operationId') != upstream_operation_id
                or receipt.get('demo_run_id') != row['demo_run_id']
                or not receipt.get('receipt_id')):
            return None
        fields = {'status': STATUS_SUCCEEDED, 'reason': 'reconciled after a lost response',
                  'disclosure': 'withheld', 'receipt_id': receipt.get('receipt_id'),
                  'resource_id': receipt.get('resource_id'),
                  'before_version': receipt.get('before_version'),
                  'after_version': receipt.get('after_version'), 'result': None,
                  'error_code': None}
        finished = await _thread(self.operations.finish, row['id'], fields)
        await _thread(self.operations.release, row['id'], 'reconciled')
        await self._audit(finished, None, None, None, decision='allow', effect='succeeded',
                          disclosure='withheld',
                          detail={'reconciled': True, 'receiptId': receipt.get('receipt_id')},
                          principal_id=row['principal_id'])
        return finished

    async def reconcile(self, *, limit=50):
        """Operator reconciliation: read receipts for unknown operations. No new dispatch."""
        state = await _thread(self.operations.run_state)
        run_id = state['run_id']
        registry = self.registry_provider()
        pending = await _thread(self.operations.list_operations, run_id, STATUS_UNKNOWN, limit)
        outcomes = []
        for row in pending:
            binding = registry.binding(row['published_tool']) if registry else None
            if binding is None:
                outcomes.append({'operationId': str(row['id']), 'status': 'unknown',
                                 'detail': 'the published tool is no longer in the registry'})
                continue
            reconciled = await self._probe_receipt(row, binding, row.get('upstream_operation_id'))
            if reconciled is None:
                outcomes.append({'operationId': str(row['id']), 'status': 'outcome_unknown',
                                 'detail': 'no receipt at the service; an operator fence is '
                                           'required before a reset'})
            else:
                outcomes.append({'operationId': str(row['id']), 'status': 'succeeded',
                                 'receiptId': reconciled.get('receipt_id'),
                                 'detail': 'reconciled from the service receipt'})
        return {'runId': run_id, 'checked': len(pending), 'outcomes': outcomes}

    async def _record_attempt(self, row, binding, *, outcome, admitted):
        await _thread(self.operations.record_attempt, {
            'operation_id': row['id'], 'demo_run_id': row['demo_run_id'],
            'principal_id': row['principal_id'], 'service_id': binding.service_id,
            'published_tool': binding.published_name, 'outcome': outcome, 'admitted': admitted,
            'request_fingerprint': row['request_fingerprint'],
            'upstream_called': admitted})

    async def _audit(self, row, policy, principal, request_id, *, decision, effect, disclosure,
                     detail=None, principal_id=None):
        await _thread(self.operations.audit, {
            'operation_id': row['id'], 'demo_run_id': row['demo_run_id'],
            'principal_id': principal_id or (principal.id if principal else row['principal_id']),
            'published_tool': row['published_tool'], 'upstream_tool': row['upstream_tool'],
            'service_id': row['service_id'],
            'policy_version': row.get('policy_version') or (policy or {}).get('policyVersion') or 1,
            'policy_hash': row.get('policy_hash') or (policy or {}).get('policyHash') or '',
            'registry_revision': row.get('registry_revision') or 1, 'decision': decision,
            'reason': row.get('reason'), 'effect_outcome': effect, 'disclosure': disclosure,
            'receipt_id': row.get('receipt_id'), 'request_id': request_id,
            'detail': detail or {}})

async def _thread(function, *args, **kwargs):
    return await anyio.to_thread.run_sync(lambda: function(*args, **kwargs))


def _tool_request(principal_id, binding, params, action=None):
    """Panel request for a tool call. ``text`` is rendered by the evaluator from the arguments."""
    return {'agent': principal_id, 'dir': 'tool_call', 'target': None,
            'service': binding.panel_service, 'action': action or binding.panel_action,
            'params': params, 'text': '', 'meta': {}}


def _validate(schema, document, where):
    Draft202012Validator(schema).validate(document)


def _business_fields(document):
    if not isinstance(document, dict):
        return {}
    return {key: value for key, value in document.items()
            if key not in ('status', 'service', 'tool', 'operation_id', 'receipt_id', 'replayed',
                           'disclosure', 'decision', 'effect', 'policy_version', 'reason',
                           'error')}


def binding_resource(binding, arguments):
    for field in ('doc_id', 'message_id', 'ticket_id'):
        value = (arguments or {}).get(field)
        if isinstance(value, str):
            return value
    return None


def _versions(document):
    before = document.get('before_version')
    after = document.get('version') or document.get('after_version')
    return before, after


_DEFAULT_LIMITS = {
    'total_deadline_ms': TOTAL_DEADLINE_MS,
    'upstream_deadline_ms': UPSTREAM_DEADLINE_MS,
    'connect_timeout_ms': CONNECT_TIMEOUT_MS,
    'max_argument_bytes': MAX_ARGUMENT_BYTES,
    'max_result_bytes': MAX_RESULT_BYTES,
    'max_concurrent_per_service': MAX_CONCURRENT_PER_SERVICE,
    'max_attempts_per_minute': MAX_ATTEMPTS_PER_MINUTE,
}
