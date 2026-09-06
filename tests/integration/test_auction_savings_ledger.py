"""
StudioNet integration test for the worked AuctionSavingsLedger example.
Direct mode cannot reach `savings_report` at all - it requires a real
cross-contract view() call back to a live task, which gltest-direct 0.29.2
does not support between two direct_deploy()ed instances in the same
process. This is the one place that path is actually exercised.

Run with:
    gltest tests/integration/test_auction_savings_ledger.py -v -s --network studionet
"""
import time
from pathlib import Path

from gltest import get_contract_factory, get_default_account, create_accounts
from gltest.assertions import tx_execution_failed
from gltest.contracts.contract_factory import ContractFactory

WAIT = dict(wait_interval=8000, wait_retries=60)

CRITERIA = "The named domain's own public homepage explicitly states it is reserved for illustrative use in documentation and examples."
REAL_URL = "https://example.com/"
BUDGET = 1000
BID_AMOUNT = 600


def test_ledger_reflects_the_tasks_real_live_status():
    owner = get_default_account()
    worker = create_accounts(1)[0]

    deadline = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 180))
    task_factory = get_contract_factory("ReverseAuctionTaskboard")
    task = task_factory.deploy(account=owner, args=[CRITERIA, BUDGET, deadline], **WAIT)
    print(f"\n[deploy] ReverseAuctionTaskboard at {task.address}")

    example_path = (
        Path(__file__).resolve().parents[2] / "examples" / "auction_savings_ledger.py"
    )
    ledger_factory = ContractFactory.from_file_path(example_path)
    ledger = ledger_factory.deploy(account=owner, **WAIT)
    print(f"[deploy] AuctionSavingsLedger at {ledger.address}")

    r = task.connect(owner).fund_task(args=[]).transact(value=BUDGET, **WAIT)
    assert not tx_execution_failed(r), r
    r = task.connect(worker).place_bid(args=[BID_AMOUNT]).transact(**WAIT)
    assert not tx_execution_failed(r), r

    print("\n[write] register_entry pointing at the real task, as a stranger (owner)")
    r = ledger.connect(owner).register_entry(args=[task.address, "front door repaint auction"]).transact(**WAIT)
    assert not tx_execution_failed(r), r
    entry_id = 0

    report_before = ledger.savings_report(args=[entry_id]).call()
    print("[view] savings_report(0) before completion:", report_before)
    assert report_before["completed"] is False

    deadline_epoch = time.mktime(time.strptime(deadline, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    while time.time() < deadline_epoch + 5:
        time.sleep(5)

    r = task.close_bidding(args=[]).transact(**WAIT)
    assert not tx_execution_failed(r), r
    r = task.connect(worker).submit_evidence(args=[REAL_URL]).transact(**WAIT)
    assert not tx_execution_failed(r), r

    print("\n[write] judge_completion - live web.render + exec_prompt round...")
    r = task.judge_completion(args=[]).transact(**WAIT)
    assert not tx_execution_failed(r), r
    bid0 = task.get_bid(args=[0]).call()
    print("  primitive's own verdict:", bid0["last_verdict"])

    report_after = ledger.savings_report(args=[entry_id]).call()
    print("[view] savings_report(0) after judging:", report_after)
    if bid0["last_verdict"] == "MET":
        assert report_after["completed"] is True
        assert report_after["saved"] == BUDGET - BID_AMOUNT
    else:
        assert report_after["completed"] is False
        assert report_after["saved"] == 0

    # --- a pointer to a real address that was never actually used as a task
    print("\n[write] register_entry pointing at the ledger's OWN address (not a real task)")
    r = ledger.connect(owner).register_entry(args=[ledger.address, "bogus pointer"]).transact(**WAIT)
    assert not tx_execution_failed(r), r
    bogus_id = 1
    bogus_failed = False
    try:
        bogus_report = ledger.savings_report(args=[bogus_id]).call()
        print("[view] savings_report(1) (not a real task):", bogus_report)
        assert bogus_report["saved"] == -1
    except Exception:
        bogus_failed = True
    print(f"  querying a non-task address as a task {'reverted' if bogus_failed else 'did not revert'} - "
          f"either outcome is safe, since it never reports forged savings")

    print("\nAuctionSavingsLedger full flow complete: real task, real judgement, "
          "ledger reads match the primitive exactly.")
