"""
Direct-mode tests for the worked consumer example
(examples/auction_savings_ledger.py).

Deliberately scoped to exclude `savings_report`: it calls
`gl.get_contract_at(...)` against a real task contract, and gltest-direct
0.29.2 does not support live cross-contract calls between two
direct_deploy()ed instances in the same process -- the same known gap
documented in the sibling examples' test suites. Whether that view actually
reflects the task's live status is verified on StudioNet instead; see
tests/integration/.

What CAN be verified here, deterministically, with only this one contract
deployed: registration bookkeeping, input validation, and the zero-address
guard.
"""
import sys

sys.path.insert(0, "..")
from conftest import as_address  # noqa: E402

LEDGER = "examples/auction_savings_ledger.py"
ZERO_ADDR_HEX = "0x" + "00" * 20


def test_register_entry_rejects_empty_display_name(direct_deploy, direct_bob):
    l = direct_deploy(LEDGER)
    addr = as_address(direct_bob).as_hex
    raised = False
    try:
        l.register_entry(addr, "")
    except Exception:
        raised = True
    assert raised


def test_register_entry_rejects_name_over_max_length(direct_deploy, direct_bob):
    l = direct_deploy(LEDGER)
    addr = as_address(direct_bob).as_hex
    raised = False
    try:
        l.register_entry(addr, "x" * 81)
    except Exception:
        raised = True
    assert raised


def test_register_entry_rejects_zero_address_task(direct_deploy):
    l = direct_deploy(LEDGER)
    raised = False
    try:
        l.register_entry(ZERO_ADDR_HEX, "front door repaint")
    except Exception:
        raised = True
    assert raised


def test_register_entry_returns_sequential_ids(direct_deploy, direct_vm, direct_alice, direct_bob):
    l = direct_deploy(LEDGER)
    addr = as_address(direct_bob).as_hex
    with direct_vm.prank(direct_alice):
        e0 = l.register_entry(addr, "task one")
        e1 = l.register_entry(addr, "task two")
    assert int(e0) == 0
    assert int(e1) == 1


def test_get_entry_count_increments_monotonically(direct_deploy, direct_bob):
    l = direct_deploy(LEDGER)
    addr = as_address(direct_bob).as_hex
    assert int(l.get_entry_count()) == 0
    l.register_entry(addr, "a")
    assert int(l.get_entry_count()) == 1
    l.register_entry(addr, "b")
    assert int(l.get_entry_count()) == 2


def test_savings_report_unknown_id_reports_not_exists(direct_deploy):
    l = direct_deploy(LEDGER)
    assert l.savings_report(999)["exists"] is False


def test_max_entries_cap_is_enforced(direct_deploy, direct_bob):
    l = direct_deploy(LEDGER)
    addr = as_address(direct_bob).as_hex
    for i in range(500):
        l.register_entry(addr, f"entry {i}")
    raised = False
    try:
        l.register_entry(addr, "entry 500")
    except Exception:
        raised = True
    assert raised, "the 501st entry must be rejected"
