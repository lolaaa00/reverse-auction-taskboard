"""
Shared fixtures and harness workarounds for the bonded-claim-race
suite. See docs/DESIGN.md for why each of these exists.
"""

import sys
import time
import pytest


def _patch_genlayer_provider_retries():
    """StudioNet's hosted RPC intermittently drops the TLS session mid-poll
    (SSLError: 'bad record mac' / 'record layer failure') under the request
    volume a full-surface or convergence run generates. Host-side flakiness,
    not a contract or harness bug -- worked around with a small bounded
    retry rather than masked by weakening a test assertion. Idempotent:
    only patches once per process. Same pattern used in every sibling
    contract's tests/conftest.py.
    """
    try:
        from genlayer_py.provider.provider import GenLayerProvider
    except ImportError:
        return
    if getattr(GenLayerProvider, "_reverse_auction_taskboard_retry_patched", False):
        return

    original_make_request = GenLayerProvider.make_request

    def make_request_with_retry(self, method, params, _max_attempts=6):
        last_err = None
        for attempt in range(_max_attempts):
            try:
                return original_make_request(self, method, params)
            except Exception as err:  # noqa: BLE001 -- deliberately broad, see docstring
                msg = str(err)
                # StudioNet's per-minute request cap (30/min, shared across
                # whatever else is hitting the hosted RPC that minute) is hit
                # routinely by a full-surface run's steady stream of receipt
                # polls -- transient in exactly the same sense as a dropped
                # TLS session, just paced by the server's own quota window
                # instead of the network. rate_limited gets a fixed 65s sleep
                # (the server's own "retry_after_seconds": 60 plus margin)
                # rather than the shorter exponential backoff below, since
                # retrying inside the same minute window would just spend the
                # attempt budget hitting the same wall again.
                rate_limited = "Rate limit exceeded" in msg or "-32029" in msg
                transient = (
                    rate_limited
                    or "SSLError" in msg
                    or "bad record mac" in msg
                    or "record layer failure" in msg
                    or "ConnectionError" in msg
                    # "ConnectionResetError" does NOT contain "ConnectionError"
                    # as a substring ("Reset" sits between them) - discovered
                    # the hard way when a real connection-reset failure slipped
                    # straight past this check instead of being retried.
                    or "ConnectionReset" in msg
                    or "Connection aborted" in msg
                    or "Connection reset by peer" in msg
                )
                if not transient or attempt == _max_attempts - 1:
                    raise
                last_err = err
                time.sleep(65 if rate_limited else 1.5 * (attempt + 1))
        raise last_err  # pragma: no cover -- unreachable, loop always returns or raises

    GenLayerProvider.make_request = make_request_with_retry
    GenLayerProvider._reverse_auction_taskboard_retry_patched = True


_patch_genlayer_provider_retries()


def as_address(v):
    """Account fixtures may arrive as raw bytes before the SDK path is on
    sys.path. Bootstrap via gltest's own loader and wrap in Address."""
    try:
        from genlayer.py.types import Address
    except ImportError:
        from gltest.direct.sdk_loader import setup_sdk_paths
        setup_sdk_paths()
        from genlayer.py.types import Address
    if isinstance(v, Address):
        return v
    return Address(bytes(v))


def warp_to(direct_vm, iso: str) -> None:
    """Advance the VM clock everywhere the contract can read it.

    SpecComplianceBounty reads time via datetime.now(timezone.utc), which
    direct_vm.warp() patches directly. gl.message_raw['datetime'] is frozen
    at load time and never updated by warp() -- refreshed here too so this
    helper stays correct if the contract is ever extended to read it.
    """
    direct_vm.warp(iso)
    gl = sys.modules.get("genlayer.gl")
    if gl is None:
        return
    raw = getattr(gl, "message_raw", None)
    if isinstance(raw, dict):
        raw["datetime"] = iso
    nested = getattr(getattr(gl, "message", None), "raw", None)
    if isinstance(nested, dict):
        nested["datetime"] = iso


@pytest.fixture(autouse=True)
def _reset_known_contract():
    """One gl.Contract subclass per process is a gltest-direct limitation.
    Reset the registry after every test so this suite is not order-dependent
    if ever run alongside the example consumer's own suite."""
    yield
    gl_contracts = sys.modules.get("genlayer.gl.genvm_contracts")
    if gl_contracts is not None and hasattr(gl_contracts, "__known_contract__"):
        gl_contracts.__known_contract__ = None
