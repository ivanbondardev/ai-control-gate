"""Budget planning and the output-reserve rule.

A reservation is taken *before* any paid or mandatory work starts, and it covers everything the
invocation still needs: the remaining semantic checks and the planned target call. If the scope
cannot cover that, the invocation is refused before dispatch and before any model call, so a
partially affordable action never runs and then loses its output control.

Time follows the same rule:

    targetDeadline = min(now + targetCap, globalDeadline - outputTimeReserve)

If that leaves less than the configured minimum window, dispatch does not start.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid

from .detectors import COMPLETION_TOKEN_CAP, render_instruction


@dataclass(frozen=True)
class PlannedCall:
    name: str
    tokens: int
    cost_micro: int
    time_ms: int


@dataclass(frozen=True)
class BudgetPlan:
    reservation_id: str
    scope_id: str
    period_key: str
    tokens: int
    cost_micro: int
    ms: int
    calls: tuple[PlannedCall, ...] = field(default_factory=tuple)
    target_deadline_ms: int = 0
    global_deadline_ms: int = 0

    def as_public_dict(self) -> dict:
        return {
            'reservationId': self.reservation_id,
            'scope': self.scope_id,
            'period': self.period_key,
            'reservedTokens': self.tokens,
            'reservedCostMicro': self.cost_micro,
            'reservedMs': self.ms,
        }


def utc_day_key(now: datetime | None = None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime('%Y-%m-%d')


def estimate_tokens(text: str | None, bytes_per_token: int) -> int:
    """Conservative size estimate: bytes divided by a configured rate, rounded up.

    This is a heuristic used to *reserve* budget before a call. It is deliberately not called a
    tokenizer count: only the provider's reported usage is treated as measured.
    """
    if not text:
        return 0
    per_token = max(1, bytes_per_token)
    size = len(text.encode('utf-8'))
    return max(1, -(-size // per_token))


def resolve_deadlines(bundle: dict, started_ms: int, request_timeout_ms: int | None) -> tuple[int, int]:
    """Return (global_deadline_ms, output_reserve_ms) as absolute/relative millisecond values."""
    reserve = bundle['reserve']
    global_cap = reserve['globalDeadlineMs']
    if request_timeout_ms:
        global_cap = min(global_cap, request_timeout_ms)
    return started_ms + global_cap, reserve['outputTimeMs']


def target_deadline(started_ms: int, now_ms: int, global_deadline_ms: int, reserve: dict) -> int | None:
    candidate = min(now_ms + reserve['targetTimeMs'], global_deadline_ms - reserve['outputTimeMs'])
    if candidate - now_ms < reserve['minTargetWindowMs']:
        return None
    return candidate


def build_plan(bundle: dict, *, scope: dict, plan_input_semantic: bool, plan_output_semantic: bool,
               input_text: str | None, output_token_cap: int, started_ms: int,
               global_deadline_ms: int, target_time_ms: int,
               detector_profile_id: str, plan_target: bool = True,
               semantic_completion_token_cap: int | None = None) -> BudgetPlan:
    estimation = bundle['estimation']
    reserve = bundle['reserve']
    bytes_per_token = estimation['bytesPerToken']
    rate = int(estimation['costMicroPerToken'].get(detector_profile_id, 0))
    calls = []
    if plan_input_semantic:
        # A provider request carries the system instruction and asks for a bounded completion, so
        # the reservation covers input + instruction + completion, not just the untrusted text.
        tokens = (estimate_tokens(input_text, bytes_per_token)
                  + estimate_tokens(render_instruction(), bytes_per_token)
                  + (semantic_completion_token_cap if semantic_completion_token_cap is not None
                     else COMPLETION_TOKEN_CAP))
        calls.append(PlannedCall('semantic_input', tokens, tokens * rate, 0))
    if plan_output_semantic:
        # The output check sees the target's answer, so its size is bounded by the same ceiling.
        tokens = min(output_token_cap, reserve['outputTokens'])
        if semantic_completion_token_cap is not None:
            # Provider output checks also send the classifier instruction and generate an answer.
            tokens += (estimate_tokens(render_instruction(), bytes_per_token)
                       + semantic_completion_token_cap)
        calls.append(PlannedCall('semantic_output', tokens, tokens * rate, 0))
    if plan_target:
        calls.append(PlannedCall('target', reserve['targetTokens'], reserve['targetCostMicro'],
                                 target_time_ms))
    tokens = sum(call.tokens for call in calls)
    cost = sum(call.cost_micro for call in calls)
    ms = sum(call.time_ms for call in calls) + reserve['outputTimeMs']
    return BudgetPlan(str(uuid.uuid4()), scope['id'], utc_day_key(), tokens, cost, ms, tuple(calls),
                      global_deadline_ms=global_deadline_ms)
