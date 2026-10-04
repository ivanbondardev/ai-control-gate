"""Invocation pipeline.

    request -> transport identity -> pinned snapshot -> grant
            -> deterministic input controls -> reserved input semantic check
            -> reserved output/target budget + output time reserve
            -> single controlled dispatch -> output controls -> durable commit and audit

Every paid or irreversible step happens after an atomic reservation. Every refusal records why and
leaves the action outcome at ``not_started``. There is exactly one call site for the service
adapter, and it is reachable only after the gate has allowed the call.

One invocation pins exactly one :class:`~action_gate.snapshot.ConfigSnapshot`. The snapshot is
carried in a :class:`RequestContext` and handed explicitly to the parser, the grant check, the
content controls and the output controls, so no stage can observe a different release than the one
the invocation started with. Nothing on this path reads a policy file.
"""
from dataclasses import dataclass, field
import json
import time

from . import budget as budget_module
from .audit import AuditTrail, hash_salt, keyed_hash, new_invocation_id, projection_hash
from .config_bundle import ConfigurationError
from .detectors import (STATUS_AVAILABLE, DetectionOutcome, SemanticRecorder, build_detector)
from .services import DocumentDeskAdapter
from .snapshot import (ConfigSnapshot, FileConfigSource, cache_model_id, detector_identity)

STATUS_COMPLETED = 'completed'
STATUS_BLOCKED = 'blocked'
STATUS_FAILED = 'failed'
OUTCOME_NOT_STARTED = 'not_started'
OUTCOME_SUCCEEDED = 'succeeded'
OUTCOME_FAILED = 'failed'
DECISION_ALLOW = 'allow'
DECISION_REDACT = 'redact'
DECISION_BLOCK = 'block'
DEPENDENCY_REASONS = ('semantic_unavailable', 'configuration_invalid', 'storage_unavailable')
# A claim older than this is treated as an unknown outcome: the earlier attempt may have dispatched
# and simply failed to record it, so it is never executed again automatically.
CLAIM_TTL_SECONDS = 120


@dataclass
class ContentOutcome:
    decision: str
    text: str | None
    reasons: tuple
    findings: tuple
    semantic_status: str
    semantic_risk: float | None
    policy_hash: str | None
    feed_hash: str | None
    semantic: dict | None = None


@dataclass
class RequestContext:
    """Everything one invocation needs, resolved once and never re-read.

    ``snapshot`` is the release whose rules this invocation executes; ``resolved`` is the detector
    identity resolved from that snapshot before any work started. Both are carried explicitly, so
    a concurrent activation cannot change what an in-flight call evaluates.
    """

    invocation_id: str
    principal: object
    snapshot: ConfigSnapshot
    trail: AuditTrail
    started_ms: int
    resolved: dict = field(default_factory=dict)
    labels: dict = field(default_factory=dict)

    @property
    def release(self) -> str:
        return self.snapshot.release_hash

    @property
    def generation(self) -> int:
        return self.snapshot.activation_generation

    @property
    def detector_profile_id(self) -> str:
        return self.resolved['profile']['id']

    def detector(self, direction: str, deadline: float | None) -> SemanticRecorder:
        identity = self.resolved['identity']
        detector = CachingDetector(
            self.resolved['detector'], self.resolved['cache'],
            {'profile_id': self.detector_profile_id,
             'model_id': cache_model_id(identity),
             'instruction_version': self.resolved['profile']['instructionVersion']})
        return SemanticRecorder(detector, direction, deadline)


class ObservationCache:
    """Semantic observations. PostgreSQL is authoritative; Redis is only a shortcut."""

    def __init__(self, repository, runtime, salt: str):
        self.repository = repository
        self.runtime = runtime
        self.salt = salt

    def projection(self, text: str) -> str:
        return projection_hash(text, self.salt)

    def lookup(self, key: dict):
        cached = self.runtime.get_observation(key) if self.runtime else None
        if cached is None:
            cached = self.repository.get_observation(key)
            if cached is not None and self.runtime:
                self.runtime.put_observation(key, cached)
        return cached

    def store(self, key: dict, record: dict) -> int:
        observation_id = self.repository.save_observation(key, record)
        if self.runtime:
            # The cache entry carries the durable id too, so a cache hit and a database hit look
            # the same to the caller.
            self.runtime.put_observation(key, dict(record, observation_id=observation_id))
        return observation_id


class CachingDetector:
    """Replays a stored observation for an identical projection instead of paying for it twice."""

    def __init__(self, detector, cache: ObservationCache, key: dict):
        self.detector = detector
        self.cache = cache
        self.key = key

    def detect(self, text, direction, deadline=None) -> DetectionOutcome:
        key = dict(self.key, direction=direction, projection_hash=self.cache.projection(text))
        cached = self.cache.lookup(key)
        if cached is not None and cached.get('status') == STATUS_AVAILABLE:
            return DetectionOutcome(
                status=STATUS_AVAILABLE, mode=cached['mode'], detector=cached['detector'],
                profile_id=cached['profile_id'], risk=cached['risk'], category=cached.get('category'),
                instruction_version=cached['instruction_version'], latency_ms=0, usage_tokens=0,
                usage_status='replayed',
                detail={'replayed': True, 'observationId': cached.get('observation_id')})
        outcome = self.detector.detect(text, direction, deadline)
        if outcome.status == STATUS_AVAILABLE:
            self.cache.store(key, {
                'profile_id': outcome.profile_id,
                'model_id': self.key['model_id'],
                'direction': direction,
                'projection_hash': key['projection_hash'],
                'risk': outcome.risk,
                'category': outcome.category,
                'detector': outcome.detector,
                'mode': outcome.mode,
                'status': outcome.status,
                'instruction_version': outcome.instruction_version,
                'usage': {'tokens': outcome.usage_tokens, 'status': outcome.usage_status},
                'latency_ms': outcome.latency_ms,
            })
        return outcome


class Gateway:
    def __init__(self, policy_dir, repository, runtime=None, environ=None, config_source=None):
        self.policy_dir = policy_dir
        self.repository = repository
        self.runtime = runtime
        self.environ = environ if environ is not None else __import__('os').environ
        self.salt, self.development_salt = hash_salt(self.environ)
        self.observations = ObservationCache(repository, runtime, self.salt)
        self.adapter = DocumentDeskAdapter(repository)
        self.config = config_source if config_source is not None else FileConfigSource(policy_dir)

    # -- construction helpers ----------------------------------------------------
    def load_bundle(self):
        """Legacy accessor: the parsed bundle of the current snapshot."""
        return self.snapshot().bundle

    def snapshot(self) -> ConfigSnapshot:
        return self.config.load()

    def _resolve_detector(self, snapshot: ConfigSnapshot, profile_id: str) -> dict:
        """Resolve a detector profile once, before any paid work starts."""
        profile = snapshot.detector_profile(profile_id)
        if profile is None:
            raise ConfigurationError('unknown detector profile')
        detector = build_detector(profile, snapshot.budgets['estimation']['bytesPerToken'],
                                 self.environ)
        return {'profile': profile, 'detector': detector, 'identity': detector_identity(detector),
                'completion_token_cap': getattr(detector, 'completion_token_cap', None),
                'cache': self.observations}

    def _build_gate(self, snapshot: ConfigSnapshot, resolved: dict, direction: str,
                    deadline: float | None):
        detector = CachingDetector(
            resolved['detector'], self.observations,
            {'profile_id': resolved['profile']['id'],
             'model_id': cache_model_id(resolved['identity']),
             'instruction_version': resolved['profile']['instructionVersion']})
        recorder = SemanticRecorder(detector, direction, deadline)
        return snapshot.content_gate(recorder), recorder

    def _inspect(self, snapshot: ConfigSnapshot, resolved: dict, text, model, direction, deadline,
                 policy_override=None) -> ContentOutcome:
        gate, recorder = self._build_gate(snapshot, resolved, direction, deadline)
        if policy_override is not None:
            from .content import ContentGate
            gate = ContentGate(policy_override, snapshot.signatures,
                               gate.policy_hash, gate.feed_hash, gate.detector)
        result = gate.inspect(text, model=model, direction=direction)
        semantic = recorder.last.as_public_dict() if recorder.last else None
        return ContentOutcome(result.decision, result.text, tuple(result.reasons),
                              tuple(result.findings), result.semantic_status, result.semantic_risk,
                              result.policy_hash, result.feed_hash, semantic)

    def _scope(self, snapshot: ConfigSnapshot, scope_id=None):
        scope = snapshot.budget_scope(scope_id)
        if scope is None:
            raise ConfigurationError('unknown budget scope')
        return scope

    def _budget_public(self, row) -> dict:
        if not row:
            return {}
        remaining = row['limit_tokens'] - row['used_tokens'] - row['reserved_tokens']
        return {
            'scope': row['scope_id'],
            'period': row['period_key'],
            'periodKind': 'utc_day',
            'limitTokens': row['limit_tokens'],
            'usedTokens': row['used_tokens'],
            'reservedTokens': row['reserved_tokens'],
            'remainingTokens': remaining,
            'availableTokens': max(0, remaining),
            'overLimit': remaining < 0,
            'overdraftTokens': row.get('overdraft_tokens', 0),
            'limitCostMicro': row['limit_cost_micro'],
            'usedCostMicro': row['used_cost_micro'],
            'reservedCostMicro': row.get('reserved_cost_micro', 0),
            'limitMs': row['limit_ms'],
            'usedMs': row['used_ms'],
            'reservedMs': row.get('reserved_ms', 0),
            'unknownUsageCount': row.get('unknown_usage_count', 0),
        }

    def _http_status(self, decision: str, reasons) -> int:
        if decision != DECISION_BLOCK:
            return 200
        return 503 if any(reason in DEPENDENCY_REASONS for reason in reasons) else 403

    def _model_not_allowed(self, snapshot: ConfigSnapshot, model) -> bool:
        allowed = snapshot.content_policy.get('allowed_models')
        return not isinstance(allowed, (list, tuple)) or model not in allowed

    # -- persistence -------------------------------------------------------------
    def _invocation_row(self, ctx: RequestContext, request, request_hash, snapshot, decision,
                        outcome, disclosure, reasons, findings, semantic_status, semantic_risk,
                        profile_id, latency_ms, response, budget_scope=None,
                        idempotency_key=None):
        return {
            'invocation_id': ctx.invocation_id,
            'idempotency_key': idempotency_key or request.idempotency_key,
            'principal_id': ctx.principal.id if ctx.principal else 'unknown',
            'principal_role': ctx.principal.role if ctx.principal else 'unknown',
            'service_id': request.service,
            'action_id': request.action,
            'request_hash': request_hash,
            'release_hash': (snapshot.release_hash if snapshot else 'unknown'),
            'decision': decision,
            'action_outcome': outcome,
            'disclosure': disclosure,
            'reasons': [str(reason) for reason in reasons],
            'findings': [str(finding) for finding in findings],
            'semantic_status': semantic_status or 'not_run',
            'semantic_risk': semantic_risk,
            'detector_profile': profile_id or 'unset',
            'latency_ms': int(latency_ms or 0),
            'dry_run': bool(request.dry_run),
            'budget_scope': budget_scope or '',
            'response': response,
        }

    def _persist(self, trail: AuditTrail, invocation: dict) -> bool:
        """Invocation row, audit events and the claim state are written in one transaction."""
        try:
            self.repository.save_outcome(invocation, trail.rows())
            return True
        except Exception:
            try:
                self.repository.mark_claim_unknown(invocation['idempotency_key'],
                                                   invocation['invocation_id'])
            except Exception:
                pass
            return False

    def _find_owned(self, principal_id: str, idempotency_key: str):
        """Look up a stored invocation for this principal and client key, never another's."""
        finder = getattr(self.repository, 'find_principal_invocation', None)
        if finder is not None:
            return finder(principal_id, idempotency_key)
        record = self.repository.find_invocation(idempotency_key)
        if record is not None and record.get('principal_id') not in (None, principal_id):
            return None
        return record

    def _claim(self, ctx: RequestContext, request, request_hash: str, storage_key: str):
        """Claim the idempotency key, or report why this call must not proceed.

        Returns ``(None, None)`` when this caller owns the key, otherwise ``(verdict, payload)``
        with a refusal. A key that is already in flight, or whose earlier attempt never recorded an
        outcome, is never re-executed. The key is scoped to the calling principal, so two callers
        that happen to pick the same client key cannot see or block each other.
        """
        principal_id = ctx.principal.id
        existing = self._find_owned(principal_id, storage_key)
        if existing is not None:
            if existing['request_hash'] != request_hash:
                return 'conflict', None
            stored = dict(existing['response'])
            stored['replayed'] = True
            return 'replay', stored
        claim = self.repository.claim_invocation(storage_key, ctx.invocation_id, request_hash,
                                                 principal_id=principal_id)
        if claim is None:
            return None, None
        if claim['request_hash'] != request_hash:
            return 'conflict', None
        if claim['state'] == 'completed':
            stored = None
            existing = self._find_owned(principal_id, storage_key)
            if existing is not None:
                stored = dict(existing['response'])
                stored['replayed'] = True
            return 'replay', stored
        if claim['state'] == 'in_flight' and claim.get('age_seconds', 0) < CLAIM_TTL_SECONDS:
            return 'in_progress', claim
        return 'unknown', claim

    def _refuse(self, ctx: RequestContext, request, code, reasons, findings=(), http=403,
                snapshot=None, request_hash=None, profile_id=None, content=None, budget_row=None,
                semantic=None, semantic_status='not_run', semantic_risk=None, owns_claim=False,
                budget_scope=None, storage_key=None, labels=None):
        """Record a refusal that never reached dispatch and persist it in one place."""
        trail = ctx.trail
        trail.record('invocation_blocked', DECISION_BLOCK, reasons=reasons, findings=findings,
                     code=code)
        snapshot = snapshot or ctx.snapshot
        body = {
            'invocationId': ctx.invocation_id,
            'replayed': False,
            'dryRun': bool(request.dry_run),
            'status': STATUS_BLOCKED,
            'error': code,
            'policy': {
                'decision': DECISION_BLOCK,
                'reasons': [str(reason) for reason in reasons],
                'findings': [str(finding) for finding in findings],
                'release': snapshot.release_hash if snapshot else None,
                'activationGeneration': snapshot.activation_generation if snapshot else None,
                'outputDecision': 'not_run',
                'contentPolicyHash': (content.policy_hash if content else
                                      (snapshot.component_hashes.get('contentPolicy')
                                       if snapshot else None)),
                'signatureFeedHash': (content.feed_hash if content else
                                      (snapshot.component_hashes.get('signatureFeed')
                                       if snapshot else None)),
            },
            'action': {'service': request.service, 'action': request.action,
                       'outcome': OUTCOME_NOT_STARTED, 'dispatched': False, 'detail': {}},
            'output': {'disclosure': 'none', 'text': None, 'bytes': 0},
            'semantic': {'input': semantic, 'output': None, 'profile': profile_id,
                         'mode': (semantic or {}).get('mode')},
            'budget': self._budget_public(budget_row),
            'timing': {'totalMs': int(time.monotonic() * 1000) - ctx.started_ms},
            'audit': {'events': len(trail), 'trace': f'/v1/invocations/{ctx.invocation_id}',
                      'persisted': None},
        }
        if labels:
            body.update(labels)
        if request_hash is None:
            request_hash = keyed_hash(_canonical_request(request), self.salt)
        # Only a caller that owns the claim may occupy the idempotency key. A refusal that lost the
        # claim race is still audited, under a namespaced key, so it can never overwrite or block
        # the authoritative outcome of the call that does own it.
        key = storage_key or _storage_key(request)
        stored_key = key if owns_claim else '{}#i:{}'.format(key, ctx.invocation_id)
        row = self._invocation_row(ctx, request, request_hash, snapshot, DECISION_BLOCK,
                                   OUTCOME_NOT_STARTED, 'none', reasons, findings, semantic_status,
                                   semantic_risk, profile_id, body['timing']['totalMs'], body,
                                   budget_scope=budget_scope, idempotency_key=stored_key)
        body['audit']['persisted'] = self._persist(trail, row)
        return http, body

    # -- invocation --------------------------------------------------------------
    def invoke(self, request, principal, snapshot: ConfigSnapshot | None = None,
               request_context: dict | None = None) -> tuple[int, dict]:
        started_ms = int(time.monotonic() * 1000)
        invocation_id = new_invocation_id()
        trail = AuditTrail(invocation_id)
        trail.record('invocation_received', service=request.service, action=request.action,
                     idempotencyKeyHash=keyed_hash(request.idempotency_key, self.salt)[:16],
                     dryRun=bool(request.dry_run))

        request_hash = keyed_hash(_canonical_request(request), self.salt)
        try:
            snapshot = snapshot or self.snapshot()
        except ConfigurationError as exc:
            trail.record('release_pinned', DECISION_BLOCK, reasons=('configuration_invalid',),
                         error=str(exc))
            return self._refuse(_pending(invocation_id, principal, started_ms, trail), request,
                                'configuration_invalid', ('configuration_invalid',), http=503,
                                request_hash=request_hash, semantic_status='invalid')
        trail.record('release_pinned', release=snapshot.release_hash,
                     bundleId=snapshot.bundle.bundle_id,
                     activationGeneration=snapshot.activation_generation,
                     schemaVersion=snapshot.schema_version)
        trail.record('identity_resolved', principal=principal.id, role=principal.role)

        if principal.role != 'operator':
            # An agent must not be able to choose a cheaper ledger or a weaker detector profile.
            for value, code in ((request.budget_scope, 'budget_scope_override_denied'),
                                (request.detector_profile, 'detector_profile_override_denied')):
                if value is not None:
                    trail.record('grant_evaluated', DECISION_BLOCK, reasons=(code,), role=principal.role)
                    return self._refuse(_pending(invocation_id, principal, started_ms, trail), request,
                                        code, (code,), snapshot=snapshot, request_hash=request_hash)
        profile_id = request.detector_profile or snapshot.detectors['default']
        try:
            resolved = self._resolve_detector(snapshot, profile_id)
        except ConfigurationError:
            return self._refuse(_pending(invocation_id, principal, started_ms, trail), request,
                                'configuration_invalid', ('configuration_invalid',), http=503,
                                snapshot=snapshot, request_hash=request_hash)
        ctx = RequestContext(invocation_id, principal, snapshot, trail, started_ms, resolved)
        trail.record('detector_resolved', profile=profile_id, mode=resolved['profile']['mode'],
                     detector=resolved['profile']['detector'],
                     modelId=resolved['identity']['model_id'],
                     endpointHash=resolved['identity']['endpoint_hash'],
                     instructionVersion=resolved['profile']['instructionVersion'])

        scope = self._scope(snapshot, request.budget_scope)
        limits = scope['limits']
        rate = int(snapshot.budgets['estimation']['costMicroPerToken'].get(profile_id, 0))
        global_deadline_ms, output_reserve_ms = budget_module.resolve_deadlines(
            snapshot.budgets, started_ms, request.timeout_ms)

        action_spec = snapshot.action(request.service, request.action)
        granted = action_spec is not None and principal.role in action_spec.grants
        trail.record('grant_evaluated', DECISION_ALLOW if granted else DECISION_BLOCK,
                     reasons=() if granted else ('grant_denied',), role=principal.role,
                     action=request.action,
                     grants=list(action_spec.grants) if action_spec else [])
        if not granted:
            return self._refuse(ctx, request, 'grant_denied', ('grant_denied',), snapshot=snapshot,
                                request_hash=request_hash, profile_id=profile_id)

        owns_claim = False
        storage_key = _storage_key(request)
        if not request.dry_run:
            verdict, payload = self._claim(ctx, request, request_hash, storage_key)
            if verdict == 'replay':
                if payload is None:
                    return self._refuse(ctx, request, 'idempotency_unknown', ('idempotency_unknown',),
                                        http=409, snapshot=snapshot, request_hash=request_hash,
                                        profile_id=profile_id, storage_key=storage_key)
                trail.record('invocation_replayed', DECISION_ALLOW if payload.get('status') !=
                             STATUS_BLOCKED else DECISION_BLOCK)
                if payload.get('status') == STATUS_BLOCKED:
                    return self._http_status(DECISION_BLOCK, payload['policy']['reasons']), payload
                return 200, payload
            if verdict in ('conflict', 'in_progress', 'unknown'):
                code = {'conflict': 'idempotency_conflict', 'in_progress': 'idempotency_in_progress',
                        'unknown': 'idempotency_unknown'}[verdict]
                return self._refuse(ctx, request, code, (code,), http=409, snapshot=snapshot,
                                    request_hash=request_hash, profile_id=profile_id,
                                    storage_key=storage_key)
            owns_claim = True
            try:
                self.repository.record_release({'release_hash': snapshot.release_hash,
                                                'bundle_id': snapshot.bundle.bundle_id,
                                                'components': snapshot.component_hashes})
            except Exception:
                return self._refuse(ctx, request, 'storage_unavailable', ('storage_unavailable',),
                                    http=503, snapshot=snapshot, request_hash=request_hash,
                                    profile_id=profile_id, storage_key=storage_key)

        # -- deterministic input controls behind a reserved semantic check ----------------
        text = request.text or ''
        semantic_control = bool(snapshot.content_policy['controls']['semantic'])
        plan_in = budget_module.build_plan(
            snapshot.budgets, scope=scope, plan_input_semantic=semantic_control and bool(text.strip()),
            plan_output_semantic=False, input_text=text, output_token_cap=0, started_ms=started_ms,
            global_deadline_ms=global_deadline_ms, target_time_ms=0, detector_profile_id=profile_id,
            semantic_completion_token_cap=resolved.get('completion_token_cap'))
        if self.repository.reserve_budget(plan_in, limits) is None:
            trail.record('budget_refused', DECISION_BLOCK, reasons=('budget_exhausted',), phase='input',
                         requestedTokens=plan_in.tokens)
            return self._refuse(ctx, request, 'budget_exhausted', ('budget_exhausted',), http=429,
                                snapshot=snapshot, request_hash=request_hash, profile_id=profile_id,
                                owns_claim=owns_claim, storage_key=storage_key,
                                budget_scope=scope['id'],
                                budget_row=self.repository.budget_state(scope['id'],
                                                                        plan_in.period_key, limits))

        input_started = int(time.monotonic() * 1000)
        if text.strip():
            content = self._inspect(snapshot, resolved, text, request.model, 'input',
                                    global_deadline_ms / 1000)
        else:
            content = ContentOutcome(DECISION_ALLOW, None, (), (), 'not_run', None, None, None, None)
        input_ms = int(time.monotonic() * 1000) - input_started
        if self._model_not_allowed(snapshot, request.model):
            content = ContentOutcome(DECISION_BLOCK, None, ('model_not_allowed',), (), 'not_run', None,
                                     content.policy_hash, content.feed_hash, None)
        trail.record('input_controls', content.decision, reasons=content.reasons,
                     findings=content.findings, semanticStatus=content.semantic_status,
                     semanticRisk=content.semantic_risk, latencyMs=input_ms)
        if content.semantic:
            trail.record('semantic_evaluation', direction='input', status=content.semantic['status'],
                         mode=content.semantic['mode'], risk=content.semantic['risk'],
                         usageTokens=content.semantic['usageTokens'],
                         usageStatus=content.semantic['usageStatus'],
                         latencyMs=content.semantic['latencyMs'])
        actual_in = _actual_tokens(content.semantic)
        charge_in = plan_in.tokens if actual_in is None else actual_in
        budget_row = self.repository.commit_budget(plan_in.reservation_id, charge_in,
                                                   charge_in * rate, input_ms,
                                                   actual_in is not None)

        if content.decision == DECISION_BLOCK:
            http = self._http_status(DECISION_BLOCK, content.reasons)
            return self._refuse(ctx, request, 'input_blocked', content.reasons, content.findings,
                                http=http, snapshot=snapshot, request_hash=request_hash,
                                profile_id=profile_id, content=content, budget_row=budget_row,
                                semantic=content.semantic, semantic_status=content.semantic_status,
                                semantic_risk=content.semantic_risk, owns_claim=owns_claim,
                                storage_key=storage_key, budget_scope=scope['id'])

        working_text = content.text if content.decision == DECISION_REDACT else text

        # -- output reserve, then the single dispatch -------------------------------------
        plan_out = budget_module.build_plan(
            snapshot.budgets, scope=scope, plan_input_semantic=False,
            plan_output_semantic=semantic_control, input_text=None,
            output_token_cap=snapshot.budgets['reserve']['outputTokens'], started_ms=started_ms,
            global_deadline_ms=global_deadline_ms,
            target_time_ms=snapshot.budgets['reserve']['targetTimeMs'], detector_profile_id=profile_id,
            plan_target=not request.dry_run,
            semantic_completion_token_cap=resolved.get('completion_token_cap'))
        if self.repository.reserve_budget(plan_out, limits) is None:
            trail.record('budget_refused', DECISION_BLOCK, reasons=('budget_exhausted',),
                         phase='output_and_target', requestedTokens=plan_out.tokens)
            return self._refuse(ctx, request, 'budget_exhausted', ('budget_exhausted',), http=429,
                                snapshot=snapshot, request_hash=request_hash, profile_id=profile_id,
                                owns_claim=owns_claim, storage_key=storage_key,
                                budget_scope=scope['id'],
                                budget_row=self.repository.budget_state(scope['id'],
                                                                        plan_out.period_key, limits))

        now_ms = int(time.monotonic() * 1000)
        deadline = budget_module.target_deadline(started_ms, now_ms, global_deadline_ms,
                                                snapshot.budgets['reserve'])
        if deadline is None and not request.dry_run:
            # Either the global deadline is already spent or too little of it is left to keep the
            # output window: in both cases no provider call and no dispatch may start.
            self.repository.release_budget(plan_out.reservation_id)
            code = ('deadline_exceeded' if now_ms >= global_deadline_ms
                    else 'output_reserve_unavailable')
            trail.record('budget_refused', DECISION_BLOCK, reasons=(code,), phase='before_dispatch')
            return self._refuse(ctx, request, code, (code,), http=503, snapshot=snapshot,
                                request_hash=request_hash, profile_id=profile_id,
                                budget_row=budget_row, content=content, semantic=content.semantic,
                                owns_claim=owns_claim, storage_key=storage_key,
                                budget_scope=scope['id'])
        if deadline is None:
            # A dry run performs no irreversible call, so the output window cannot be consumed.
            deadline = global_deadline_ms

        action = {'service': request.service, 'action': request.action, 'outcome': OUTCOME_NOT_STARTED,
                  'dispatched': False, 'detail': {}}
        output = {'disclosure': 'none', 'text': None, 'bytes': 0}
        semantic_out, dispatch_ms, output_ms = None, 0, 0

        if not request.dry_run:
            trail.record('dispatch_started', service=request.service, action=request.action,
                         targetWindowMs=deadline - int(time.monotonic() * 1000))
            dispatch_started = int(time.monotonic() * 1000)
            result = self.adapter.dispatch(request.action, document_id=request.document_id,
                                           text=working_text, invocation_id=invocation_id,
                                           principal_id=principal.id)
            dispatch_ms = int(time.monotonic() * 1000) - dispatch_started
            action = {'service': request.service, 'action': request.action, 'outcome': result.outcome,
                      'dispatched': True, 'detail': result.detail}
            trail.record('dispatch_finished', result.outcome, reason=result.reason, latencyMs=dispatch_ms,
                         **result.detail)

            if result.output_text is not None:
                output_started = int(time.monotonic() * 1000)
                out_content = self._inspect(snapshot, resolved, result.output_text, request.model,
                                            'output', deadline / 1000)
                output_ms = int(time.monotonic() * 1000) - output_started
                semantic_out = out_content.semantic
                trail.record('output_controls', out_content.decision, reasons=out_content.reasons,
                             findings=out_content.findings, semanticStatus=out_content.semantic_status,
                             latencyMs=output_ms)
                if out_content.semantic:
                    trail.record('semantic_evaluation', direction='output',
                                 status=out_content.semantic['status'], mode=out_content.semantic['mode'],
                                 risk=out_content.semantic['risk'],
                                 usageTokens=out_content.semantic['usageTokens'],
                                 usageStatus=out_content.semantic['usageStatus'],
                                 latencyMs=out_content.semantic['latencyMs'])
                if out_content.decision == DECISION_BLOCK:
                    output = {'disclosure': 'withheld', 'text': None, 'bytes': 0,
                              'reasons': list(out_content.reasons), 'findings': list(out_content.findings),
                              'note': 'Output control blocked disclosure; the action is not rolled back.'}
                elif out_content.decision == DECISION_REDACT:
                    output = {'disclosure': 'redacted', 'text': out_content.text,
                              'bytes': len((out_content.text or '').encode('utf-8'))}
                else:
                    output = {'disclosure': 'full', 'text': result.output_text,
                              'bytes': len(result.output_text.encode('utf-8'))}

            actual_out = _actual_tokens(semantic_out)
            charge_out = plan_out.tokens if actual_out is None else actual_out
            budget_row = self.repository.commit_budget(
                plan_out.reservation_id, charge_out, charge_out * rate,
                max(0, dispatch_ms + output_ms), actual_out is not None)
        else:
            budget_row = self.repository.commit_budget(plan_out.reservation_id, 0, 0,
                                                       int(time.monotonic() * 1000) - started_ms, True)

        timing = {'totalMs': int(time.monotonic() * 1000) - started_ms, 'inputMs': input_ms,
                  'dispatchMs': dispatch_ms, 'outputMs': output_ms}
        output_decision = {'none': 'not_run', 'full': DECISION_ALLOW, 'redacted': DECISION_REDACT,
                           'withheld': DECISION_BLOCK}[output['disclosure']]
        semantic = {'input': content.semantic, 'output': semantic_out,
                    'profile': profile_id, 'mode': (content.semantic or semantic_out or {}).get('mode'),
                    'replayed': 'replayed' in ((content.semantic or {}).get('usageStatus'),
                                               (semantic_out or {}).get('usageStatus'))}
        body = {
            'invocationId': invocation_id,
            'replayed': False,
            'dryRun': bool(request.dry_run),
            'status': STATUS_COMPLETED if action['outcome'] != OUTCOME_FAILED else STATUS_FAILED,
            'policy': {'decision': content.decision, 'reasons': list(content.reasons),
                       'findings': list(content.findings), 'release': snapshot.release_hash,
                       'activationGeneration': snapshot.activation_generation,
                       'outputDecision': output_decision,
                       'contentPolicyHash': (content.policy_hash
                                             or snapshot.component_hashes.get('contentPolicy')),
                       'signatureFeedHash': (content.feed_hash
                                             or snapshot.component_hashes.get('signatureFeed'))},
            'input': {'redacted': content.decision == DECISION_REDACT,
                      'bytes': len(text.encode('utf-8'))},
            'action': action,
            'output': output,
            'semantic': semantic,
            'budget': self._budget_public(budget_row),
            'timing': timing,
            'audit': {'events': len(trail) + 1, 'trace': f'/v1/invocations/{invocation_id}',
                      'persisted': True},
        }
        trail.record('invocation_completed' if action['outcome'] != OUTCOME_FAILED else 'invocation_failed',
                     content.decision, reasons=content.reasons, findings=content.findings,
                     outcome=action['outcome'], dispatchCount=1 if action['dispatched'] else 0)
        row = self._invocation_row(ctx, request, request_hash, snapshot, content.decision,
                                   action['outcome'], output['disclosure'], content.reasons,
                                   content.findings, content.semantic_status, content.semantic_risk,
                                   profile_id, timing['totalMs'], body, budget_scope=scope['id'],
                                   idempotency_key=storage_key)
        persisted = self._persist(trail, row)
        body['audit']['events'] = len(trail)
        body['audit']['persisted'] = persisted
        if not persisted:
            body['status'] = STATUS_FAILED
            body['error'] = 'audit_not_persisted'
            return 503, body
        return 200, body

    # -- reporting ---------------------------------------------------------------
    def release_info(self) -> tuple[int, dict]:
        try:
            snapshot = self.snapshot()
        except ConfigurationError as exc:
            return 503, {'error': 'configuration_invalid', 'detail': str(exc)}
        info = snapshot.public_dict()
        info['detectors'] = [{'id': profile['id'], 'mode': profile['mode'],
                              'detector': profile['detector']}
                             for profile in snapshot.detectors['profiles']]
        info['budgets'] = [{'id': scope['id'], 'period': scope['period'], 'limits': scope['limits']}
                           for scope in snapshot.budgets['scopes']]
        info['hashSalt'] = 'development-default' if self.development_salt else 'configured'
        info['storage'] = self.repository.name
        return 200, info

    def services_info(self) -> dict:
        snapshot = self.snapshot()
        return {'services': [
            {'id': service.id, 'description': service.description,
             'actions': [{'id': action.id, 'effect': action.effect, 'grants': list(action.grants),
                          'description': action.description} for action in service.actions.values()]}
            for service in snapshot.services.values()]}

    def me(self, principal) -> dict:
        snapshot = self.snapshot()
        capabilities = ['invoke:read']
        if principal.role == 'operator':
            capabilities = ['invoke:read', 'invoke:write', 'invoke:destructive', 'config:write',
                            'reporting:all', 'evaluation:run']
        else:
            for service in snapshot.services.values():
                for action in service.actions.values():
                    if principal.role in action.grants:
                        capabilities.append('{}.{}'.format(service.id, action.id))
        return {'principalId': principal.id, 'role': principal.role,
                'capabilities': sorted(set(capabilities)),
                'release': snapshot.release_hash,
                'activationGeneration': snapshot.activation_generation}

    def readiness(self) -> tuple[int, dict]:
        checks = {}
        try:
            snapshot = self.snapshot()
            checks['configuration'] = {'ok': True, 'release': snapshot.release_hash,
                                       'activationGeneration': snapshot.activation_generation,
                                       'schemaVersion': snapshot.schema_version}
        except ConfigurationError as exc:
            checks['configuration'] = {'ok': False, 'error': str(exc)}
        try:
            checks['storage'] = dict(self.repository.health(), ok=True)
        except Exception as exc:
            checks['storage'] = {'ok': False, 'error': type(exc).__name__}
        checks['runtimeCache'] = ({'ok': True, **self.runtime.health()} if self.runtime
                                  else {'ok': True, 'enabled': False})
        return (200 if all(check.get('ok') for check in checks.values()) else 503), {
            'ready': all(check.get('ok') for check in checks.values()), 'checks': checks}

    def trace(self, invocation_id: str) -> tuple[int, dict]:
        record = self.repository.get_invocation(invocation_id)
        if record is None:
            return 404, {'error': 'not_found'}
        return 200, {'invocation': {key: value for key, value in record.items() if key != 'response'},
                     'response': record['response'], 'events': self.repository.list_events(invocation_id)}

    def summary(self, since: str, until: str, principal_id: str | None = None) -> dict:
        snapshot = self.snapshot()
        scope = self._scope(snapshot)
        period = budget_module.utc_day_key()
        state = self.repository.read_ledger(scope['id'], period) or \
            self.repository.budget_state(scope['id'], period, scope['limits'])
        report = self.repository.summary(since, until, principal_id=principal_id)
        report['budget'] = dict(self._budget_public(state),
                                label='Current shared budget (UTC day, all callers)')
        report['release'] = snapshot.public_dict()
        report['semanticMode'] = snapshot.detector_profile(None)['mode']
        report['storage'] = {'repository': self.repository.name}
        report['runtime'] = self.runtime.health() if self.runtime else {'enabled': False}
        return report

    def export_audit(self, since: str, until: str, limit: int, cursor: str | None = None,
                     filters: dict | None = None) -> dict:
        """One bounded page of audit events. Paging and filtering live in the repository."""
        return self.repository.list_events_page(since, until, limit, cursor, filters)

    # -- configuration comparison (never dispatches) -------------------------------
    def evaluate(self, evaluation) -> tuple[int, dict]:
        from .evaluation import EvaluationRunner
        return EvaluationRunner(self).run(evaluation)


def _pending(invocation_id, principal, started_ms, trail) -> RequestContext:
    """A context for refusals that happen before a snapshot could be pinned."""
    return RequestContext(invocation_id, principal, None, trail, started_ms, {})


def _storage_key(request) -> str:
    """Physical idempotency key. A dry run never occupies the key of a real action."""
    return '{}#dry'.format(request.idempotency_key) if request.dry_run else request.idempotency_key


def _actual_tokens(semantic: dict | None):
    """Tokens to charge for one semantic stage.

    ``0`` means "known to be zero": no semantic call was planned, or the result was replayed from a
    stored observation. ``None`` means the provider did not report usage - the reservation is then
    charged in full and the event is counted as unknown, never as zero.
    """
    if not semantic:
        return 0
    if semantic.get('usageStatus') in ('replayed', 'not_applicable'):
        return 0
    return semantic.get('usageTokens')


def _canonical_request(request) -> str:
    return json.dumps({'service': request.service, 'action': request.action,
                       'documentId': request.document_id, 'text': request.text,
                       'model': request.model, 'dryRun': bool(request.dry_run),
                       'detectorProfile': request.detector_profile,
                       'budgetScope': request.budget_scope,
                       'timeoutMs': request.timeout_ms,
                       'fingerprintVersion': FINGERPRINT_VERSION},
                      sort_keys=True, ensure_ascii=False)


# Bumped when the fields that define "the same request" change; stored hashes keep their version.
FINGERPRINT_VERSION = 2
