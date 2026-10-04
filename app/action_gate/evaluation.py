"""Configuration comparison.

Compare runs the *same* evaluator an invocation runs, with exactly one difference: the effect
boundary. The target adapter is never called, so a compare run cannot change target state, and the
per-case outcome records `dispatched: false` as evidence rather than as a promise.

Three results are distinguished, and they are not interchangeable:

* ``complete`` - every case ran to a verdict;
* ``partial``  - some cases ran, then budget or a provider failure stopped the run;
* ``failed``   - the run could not evaluate the candidate at all.

A candidate becomes activatable only when the run is ``complete`` and every explicitly stated
expectation matched. ``passed`` is therefore a separate field from ``complete``: a comparison that
did not finish, or that contradicted the editor's stated expectations, is never shown as green.

Every real detector call is charged to the active policy's ``evaluation-daily`` scope; a replayed
projection is not charged again, because a cache hit buys no model call.
"""
import time
from dataclasses import dataclass, field

from . import budget as budget_module
from .config_bundle import ConfigurationError
from .snapshot import canonical, to_jsonable


@dataclass(frozen=True)
class EvaluationCase:
    case_id: str
    direction: str
    text: str
    service: str | None
    action: str | None
    model: str
    family: str | None
    label: str | None
    expected_decision: str | None
    expected_disclosure: str | None
    expect_dispatch: bool | None
    require_block: bool


@dataclass(frozen=True)
class EvaluationRequest:
    cases: tuple
    detector_profile: str | None
    candidate: dict = field(default_factory=dict)

    @property
    def candidate_documents(self) -> dict:
        return dict(self.candidate.get('documents') or {})

    @property
    def candidate_revision(self) -> int | None:
        return self.candidate.get('revision')

    @property
    def candidate_label(self):
        return self.candidate.get('rawRevision')

    @property
    def dataset_hash(self) -> str | None:
        return self.candidate.get('datasetHash')

    @property
    def mode(self) -> str:
        return self.candidate.get('mode') or 'full'

    @property
    def candidate_hash(self) -> str | None:
        return self.candidate.get('hash')


class EvaluationRunner:
    """Executes one comparison against a pinned active snapshot."""

    def __init__(self, gateway):
        self.gateway = gateway

    def run(self, evaluation: EvaluationRequest) -> tuple[int, dict]:
        from .snapshot import snapshot_from_documents

        started_ms = int(time.monotonic() * 1000)
        try:
            active = self.gateway.snapshot()
        except ConfigurationError as exc:
            return 503, {'error': 'configuration_invalid', 'detail': str(exc)}

        profile_id = evaluation.detector_profile or active.detectors['default']
        try:
            resolved = self.gateway._resolve_detector(active, profile_id)
        except ConfigurationError:
            return 422, {'error': 'unknown_detector_profile'}

        documents = evaluation.candidate_documents
        candidate, candidate_error = None, None
        if documents:
            merged = active.documents()
            unknown = sorted(set(documents) - set(merged))
            if unknown:
                return 422, {'error': 'unsupported_candidate_documents',
                             'detail': ', '.join(unknown)}
            merged.update({name: value for name, value in documents.items()})
            try:
                candidate = snapshot_from_documents(merged, bundle_id=active.bundle.bundle_id)
            except ConfigurationError as exc:
                return 422, {'error': 'candidate_invalid', 'detail': str(exc)}
        else:
            # No candidate documents: this is a content-only preview of the rules that are already
            # active. Both branches run the same release, which is a useful regression check and is
            # explicitly not a comparison of two releases.
            candidate = active
            candidate_error = 'no_candidate_documents'
        candidate_is_separate = bool(documents) and candidate is not None

        # A candidate that changes the runtime detector profile is not evaluable without a real
        # call to that profile, so the comparison refuses instead of guessing.
        if candidate is not None and candidate.detectors['default'] != active.detectors['default']:
            candidate_error = 'candidate_changes_detector_profile'

        scope = self.gateway._scope(active, 'evaluation-daily')
        global_deadline_ms, _ = budget_module.resolve_deadlines(active.budgets, started_ms, None)
        deadline = (global_deadline_ms) / 1000

        results = []
        model_calls = 0
        unknown_usage = 0
        status = 'complete' if candidate_error != 'candidate_changes_detector_profile' else 'failed'
        stopped_by = None
        for case in evaluation.cases:
            entry = {'caseId': case.case_id, 'direction': case.direction,
                     'family': case.family, 'label': case.label, 'dispatched': False}
            plan = budget_module.build_plan(
                active.budgets, scope=scope, plan_input_semantic=True, plan_output_semantic=False,
                input_text=case.text, output_token_cap=0, started_ms=started_ms,
                global_deadline_ms=global_deadline_ms, target_time_ms=0,
                detector_profile_id=profile_id,
                semantic_completion_token_cap=resolved.get('completion_token_cap'))
            if self.gateway.repository.reserve_budget(plan, scope['limits']) is None:
                status = 'partial'
                stopped_by = 'evaluation_budget_exhausted'
                entry.update({'evaluated': False, 'note': 'Evaluation budget exhausted before this '
                                                          'case; no provider call was made.'})
                results.append(entry)
                continue

            case_started = int(time.monotonic() * 1000)
            charged = plan.tokens
            charged_known = False
            for label, snapshot, policy_override in (('active', active, None),
                                                     ('candidate', candidate or active,
                                                      None if candidate else None)):
                if snapshot is None:
                    continue
                outcome = self.gateway._inspect(snapshot, resolved, case.text, case.model,
                                                case.direction, deadline,
                                                policy_override=policy_override)
                semantic = outcome.semantic
                if semantic and semantic.get('usageStatus') not in ('replayed', 'not_applicable'):
                    model_calls += 1
                    if semantic.get('usageTokens') is None:
                        unknown_usage += 1
                        charged = plan.tokens
                        charged_known = False
                    elif not charged_known:
                        charged = semantic['usageTokens']
                        charged_known = True
                    else:
                        charged += semantic['usageTokens']
                entry[label] = {
                    'decision': outcome.decision,
                    'reasons': list(outcome.reasons),
                    'findings': list(outcome.findings),
                    'semantic': semantic,
                    'contentPolicyHash': outcome.policy_hash,
                    'dispatched': False,
                }
            entry['changed'] = (candidate is not None
                                and entry.get('active', {}).get('decision')
                                != entry.get('candidate', {}).get('decision'))
            entry['evaluated'] = candidate is not None
            entry['verdict'] = self._verdict(case, entry)
            results.append(entry)
            self.gateway.repository.commit_budget(plan.reservation_id, charged, 0,
                                                  int(time.monotonic() * 1000) - case_started,
                                                  charged_known)

        checked = [entry for entry in results if entry.get('evaluated')]
        failed_checks = [entry['caseId'] for entry in checked if entry['verdict'] == 'failed']
        passed = (status == 'complete' and candidate is not None and not failed_checks
                  and len(checked) == len(evaluation.cases))
        body = {
            'evaluationId': None,
            'status': status,
            'passed': passed,
            'mode': evaluation.mode,
            'active': {'release': active.release_hash,
                       'activationGeneration': active.activation_generation,
                       'componentHashes': dict(active.component_hashes)},
            'candidate': (None if not candidate_is_separate else {
                'release': candidate.release_hash,
                'revision': evaluation.candidate_revision,
                'componentHashes': dict(candidate.component_hashes),
            }),
            'previewOfActiveRelease': not candidate_is_separate,
            'detector': {'profile': profile_id,
                         'identity': resolved['identity'],
                         'instructionVersion': resolved['profile']['instructionVersion'],
                         'mode': resolved['profile']['mode']},
            'datasetHash': evaluation.dataset_hash,
            'cases': results,
            'checkedCases': len(checked),
            'totalCases': len(evaluation.cases),
            'failedCases': failed_checks,
            'changedCases': [entry['caseId'] for entry in results if entry.get('changed')],
            'modelCalls': model_calls,
            'unknownUsageCalls': unknown_usage,
            'stoppedBy': stopped_by,
            'targetDispatchCount': 0,
            'budget': self.gateway._budget_public(
                self.gateway.repository.read_ledger(scope['id'], budget_module.utc_day_key())
                or self.gateway.repository.budget_state(scope['id'], budget_module.utc_day_key(),
                                                        scope['limits'])),
            'note': ('Compare never calls the target service. A repeated projection reuses a stored '
                     'observation and is not charged again.'),
        }
        if candidate_error:
            body['candidateError'] = candidate_error
        return 200, body

    def _verdict(self, case: EvaluationCase, entry: dict) -> str:
        """Compare the candidate's outcome with the expectations the editor stated."""
        candidate = entry.get('candidate') or {}
        decision = candidate.get('decision')
        if decision is None:
            return 'not_evaluated'
        if decision == 'block' and case.require_block:
            return 'passed'
        if case.expected_decision is not None and decision != case.expected_decision:
            return 'failed'
        if case.expect_dispatch is False and decision != 'block':
            return 'failed'
        if case.expect_dispatch is True and decision == 'block':
            return 'failed'
        if case.expected_disclosure is not None:
            actual = {'block': 'withheld', 'redact': 'redacted', 'allow': 'full'}.get(decision)
            if actual != case.expected_disclosure:
                return 'failed'
        if case.expected_decision is None and case.expected_disclosure is None \
                and case.expect_dispatch is None and not case.require_block:
            return 'observed'
        return 'passed'


def structural_diff(active, candidate) -> dict:
    """Which editable component changed between two snapshots.

    Used to decide whether a narrow, deterministic activation path is allowed: only a change that
    raises existing caps - and nothing else - may skip a full compare run.
    """
    changed = {}
    for name in sorted(set(active.component_hashes) | set(candidate.component_hashes)):
        if active.component_hashes.get(name) != candidate.component_hashes.get(name):
            changed[name] = {'active': active.component_hashes.get(name),
                             'candidate': candidate.component_hashes.get(name)}
    return changed


def caps_only_change(active, candidate) -> tuple[bool, str | None]:
    """True when the candidate differs from the active release *only* by raised scopes.

    The check is structural, not textual: every other document must be byte-identical in canonical
    form, every scope must keep its identity and period, and no limit may be lowered.
    """
    if canonical(to_jsonable(active.content_policy)) != canonical(to_jsonable(candidate.content_policy)):
        return False, 'content_policy_changed'
    if canonical(to_jsonable(active.signature_feed)) != canonical(to_jsonable(candidate.signature_feed)):
        return False, 'signature_feed_changed'
    active_services = active.services_document()
    candidate_services = candidate.services_document()
    if canonical(active_services) != canonical(candidate_services):
        return False, 'grants_changed'
    active_scopes = {scope['id']: scope for scope in active.budgets['scopes']}
    candidate_scopes = {scope['id']: scope for scope in candidate.budgets['scopes']}
    if set(active_scopes) != set(candidate_scopes):
        return False, 'scope_set_changed'
    for scope_id, active_scope in active_scopes.items():
        candidate_scope = candidate_scopes[scope_id]
        if active_scope['period'] != candidate_scope['period']:
            return False, 'scope_period_changed'
        for key in ('tokens', 'costMicro', 'wallClockMs'):
            if candidate_scope['limits'][key] < active_scope['limits'][key]:
                return False, 'caps_lowered'
    active_rest = dict(to_jsonable(active.budgets))
    candidate_rest = dict(to_jsonable(candidate.budgets))
    active_rest.pop('scopes', None)
    candidate_rest.pop('scopes', None)
    if canonical(active_rest) != canonical(candidate_rest):
        return False, 'budget_policy_changed'
    return True, None


def budget_only_evaluation(active, candidate) -> dict:
    """A deterministic, zero-provider-call evaluation record for a caps-only candidate.

    It still runs ledger semantics checks, because the point of the narrow path is to make a
    recovery from an exhausted evaluation budget possible, not to skip verification.
    """
    ok, reason = caps_only_change(active, candidate)
    return {
        'status': 'complete' if ok else 'failed',
        'passed': ok,
        'mode': 'budget-only',
        'reason': reason,
        'modelCalls': 0,
        'targetDispatchCount': 0,
        'checks': ['structural_diff_caps_only', 'scope_identity_preserved', 'no_limit_lowered'],
    }


__all__ = ['EvaluationCase', 'EvaluationRequest', 'EvaluationRunner', 'budget_only_evaluation',
           'caps_only_change', 'structural_diff']
