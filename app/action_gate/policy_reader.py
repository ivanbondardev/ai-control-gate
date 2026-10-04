"""Read the active panel policy for the MCP runtime.

The panel stays the single source of policy. This reader looks at the same row the panel edits, but
without ``FOR UPDATE``: the runtime role needs only SELECT, and it must never hold the panel's write
lock while a network call is in flight.

A snapshot is cached by ``(state revision, policy hash)`` only for the cost of re-validating an
unchanged document; a new activation produces a new key on the next call, so an operator's change
affects the next admission and never rewrites an operation already in flight.
"""
from copy import deepcopy
from hashlib import sha256
import json
import threading


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
                      allow_nan=False)


def policy_hash(policy) -> str:
    return sha256(canonical({key: value for key, value in policy.items()
                             if key != 'version'}).encode()).hexdigest()


class PolicyUnavailable(RuntimeError):
    def __init__(self, code, detail=None):
        super().__init__(detail or code)
        self.code = code
        self.detail = detail


class PanelPolicyReader:
    """Unlocked read of the active panel policy plus its service catalog."""

    def __init__(self, repository, *, cache_size=8):
        self.repository = repository
        self.cache_size = cache_size
        self._lock = threading.RLock()
        self._cache = {}

    # -- storage ---------------------------------------------------------------------
    def _raw_state(self) -> dict:
        if getattr(self.repository, 'name', '') != 'postgres':
            state = getattr(self.repository, '_panel_state', None)
            if state is None:
                raise PolicyUnavailable('policy_unavailable', 'the panel has not been initialised')
            return json.loads(canonical(state))
        with self.repository.raw_connection() as connection:
            with connection.cursor() as cursor:
                # No FOR UPDATE: this is a read-only snapshot and it must never block activation.
                cursor.execute("SELECT revision, state->'policy', state->'services' "
                               "FROM control_panel_state WHERE id = 'default'")
                row = cursor.fetchone()
        if row is None:
            raise PolicyUnavailable('policy_unavailable', 'the panel has not been initialised')
        revision, policy, services = row
        if isinstance(policy, str):
            policy = json.loads(policy)
        if isinstance(services, str):
            services = json.loads(services)
        return {'revision': revision, 'policy': policy, 'services': services}

    # -- public ----------------------------------------------------------------------
    def read(self) -> dict:
        state = self._raw_state()
        policy = state['policy']
        digest = policy_hash(policy)
        key = (state['revision'], digest)
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                return {**cached, 'services': deepcopy(state['services'])}
        from . import panel_engine
        try:
            validated = panel_engine.validate_policy(deepcopy(policy), state['services'])
        except panel_engine.PanelValidationError as exc:
            raise PolicyUnavailable('policy_invalid', f'{exc.code}: {exc.message}') from exc
        snapshot = {'policy': validated, 'policyHash': digest, 'policyVersion': validated['version'],
                    'stateRevision': state['revision'], 'services': deepcopy(state['services'])}
        with self._lock:
            if len(self._cache) >= self.cache_size:
                self._cache.clear()
            self._cache[key] = {name: deepcopy(value) for name, value in snapshot.items()
                                if name != 'services'}
        return snapshot
