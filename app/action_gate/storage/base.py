"""Repository boundary.

PostgreSQL is the durable source of truth for configuration releases, invocations, audit events,
budget ledger and synthetic effects. Redis is only a disposable accelerator (see ``runtime.py``):
losing it must not lose audit, reset a budget, or re-permit an executed action.
"""
from datetime import datetime, timezone


class RepositoryError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None):
        super().__init__(code)
        self.code = code
        self.detail = detail


class Repository:
    """Interface implemented by the memory and PostgreSQL repositories."""

    name = 'abstract'

    def health(self) -> dict:
        raise NotImplementedError

    def record_release(self, release: dict) -> None:
        raise NotImplementedError

    def find_invocation(self, idempotency_key: str) -> dict | None:
        raise NotImplementedError

    def find_principal_invocation(self, principal_id: str, idempotency_key: str) -> dict | None:
        """Look up a stored invocation for one principal only.

        Replay is scoped to the caller that owns the key: the same client key used by a different
        principal is a different operation and must never return someone else's result.
        """
        raise NotImplementedError

    def claim_invocation(self, idempotency_key: str, invocation_id: str, request_hash: str,
                         principal_id: str | None = None) -> dict | None:
        """Atomically claim an idempotency key before any paid or irreversible work.

        Returns ``None`` when this caller owns the key. Otherwise returns the existing claim so the
        caller can replay a completed invocation, refuse an in-flight one, or report an unknown
        outcome - but never execute the action a second time.
        """
        raise NotImplementedError

    def mark_claim_unknown(self, idempotency_key: str, invocation_id: str) -> None:
        raise NotImplementedError

    def save_outcome(self, record: dict, rows: list) -> None:
        """Write the invocation row, its audit events and the completed claim in one transaction."""
        raise NotImplementedError

    def save_model_checkpoint(self, record: dict, rows: list) -> None:
        """Upsert a sanitized model invocation and append new events atomically."""
        raise NotImplementedError

    def read_ledger(self, scope_id: str, period_key: str) -> dict | None:
        """Read the ledger without creating or updating it."""
        raise NotImplementedError

    def save_invocation(self, record: dict) -> None:
        raise NotImplementedError

    def get_invocation(self, invocation_id: str) -> dict | None:
        raise NotImplementedError

    def append_events(self, rows: list) -> None:
        raise NotImplementedError

    def list_events(self, invocation_id: str) -> list:
        raise NotImplementedError

    def list_events_window(self, since: str, until: str, limit: int) -> list:
        raise NotImplementedError

    def list_events_page(self, since: str, until: str, limit: int, cursor: str | None = None,
                         filters: dict | None = None) -> dict:
        """One bounded page of audit events plus an opaque cursor for the next page.

        Returns ``{'events': [...], 'nextCursor': str | None, 'truncated': bool}``. The cursor is
        bound to the window and filters it was issued for, so paging a stable window cannot skip or
        duplicate an event.
        """
        raise NotImplementedError

    def list_invocations(self, since: str, until: str, limit: int, cursor: str | None = None,
                         filters: dict | None = None) -> dict:
        """One bounded page of invocation metadata, newest first, without response bodies."""
        raise NotImplementedError

    def list_summaries(self, since: str, until: str) -> dict:
        """Aggregates that need per-row values the SQL summary cannot compute (percentiles)."""
        raise NotImplementedError

    def ensure_ledger(self, scope_id: str, period_key: str, limits: dict,
                      generation: int | None = None) -> dict:
        """Create the ledger row for a period without ever overwriting existing caps.

        Caps change in exactly one place - activation - so a read or a reservation must not be able
        to rewrite the limits a concurrent activation just installed.
        """
        raise NotImplementedError

    def reserve_budget(self, plan, limits: dict) -> dict | None:
        raise NotImplementedError

    def commit_budget(self, reservation_id: str, tokens: int, cost_micro: int, ms: int,
                      usage_known: bool) -> dict:
        raise NotImplementedError

    def release_budget(self, reservation_id: str) -> dict:
        raise NotImplementedError

    def budget_state(self, scope_id: str, period_key: str, limits: dict) -> dict:
        raise NotImplementedError

    def record_reservation_context(self, reservation_id: str, context: dict) -> None:
        """Attach provenance to a reservation: release, generation, pricing identity, caller."""
        raise NotImplementedError

    def get_observation(self, key: dict) -> dict | None:
        raise NotImplementedError

    def save_observation(self, key: dict, record: dict) -> int:
        raise NotImplementedError

    def record_effect(self, effect: dict) -> None:
        raise NotImplementedError

    def dispatch_counts(self, since: str) -> dict:
        raise NotImplementedError

    def read_document(self, document_id: str) -> dict | None:
        raise NotImplementedError

    def add_comment(self, document_id: str, body: str, author: str, invocation_id: str) -> dict | None:
        raise NotImplementedError

    def delete_document(self, document_id: str, invocation_id: str) -> bool:
        raise NotImplementedError

    def summary(self, since: str, until: str, principal_id: str | None = None) -> dict:
        """Aggregate one window, optionally restricted to one invocation owner.

        The owner restriction covers every counter, event, effect and latency sample. A None
        principal is the operator's complete bench view, never the default for an agent route.
        """
        raise NotImplementedError

    def latency_percentiles(self, since: str, until: str,
                            principal_id: str | None = None) -> dict:
        """Latency count and percentiles for one window, computed the same way in every backend.

        Percentiles are computed in Python from the actual sample because the alternative - a
        backend-specific SQL percentile - would produce two different numbers for the same data.
        """
        raise NotImplementedError

    def close(self) -> None:
        pass


def utc_now_iso() -> str:
    return iso_utc(datetime.now(timezone.utc))


def iso_utc(value: datetime) -> str:
    """One timestamp format in every answer: ISO-8601, milliseconds, explicit UTC designator.

    Every window bound, event and invocation timestamp a caller sees goes through here, so two
    backends cannot report the same instant differently.
    """
    return value.astimezone(timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
