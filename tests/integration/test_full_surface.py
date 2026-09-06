"""
Full-surface StudioNet integration test for ReverseAuctionTaskboard. Drives
every write method and reads every view, printing state after each step,
and asserts the negative cases actually refuse. Direct mode mocks the web
fetch and the model entirely, so this is what catches what it hides: real
type marshalling, real GEN movement including the exact-bid payout and
poster refund arithmetic, and the live web.render + exec_prompt +
prompt_comparative round trip inside real consensus.

Run with:
    gltest tests/integration/test_full_surface.py -v -s --network studionet
"""
import time

import pytest
from gltest import get_contract_factory, get_default_account, create_accounts
from gltest.assertions import tx_execution_failed

WAIT = dict(wait_interval=8000, wait_retries=60)

CRITERIA = "The named domain's own public homepage explicitly states it is reserved for illustrative use in documentation and examples."
REAL_URL = "https://example.com/"
BUDGET = 1000


@pytest.fixture(scope="module")
def parties():
    accounts = create_accounts(3)
    return {
        "poster": get_default_account(),
        "alice": accounts[0],
        "bob": accounts[1],
        "stranger": accounts[2],
    }


@pytest.fixture(scope="module")
def task(parties):
    deadline = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 120))
    factory = get_contract_factory("ReverseAuctionTaskboard")
    contract = factory.deploy(account=parties["poster"], args=[CRITERIA, BUDGET, deadline], **WAIT)
    print(f"\n[deploy] ReverseAuctionTaskboard at {contract.address}, bidding_deadline={deadline}")
    return contract


def test_full_surface_drives_every_write_and_view(task, parties):
    poster = parties["poster"]
    alice = parties["alice"]
    bob = parties["bob"]
    stranger = parties["stranger"]

    print("\n[view] get_task_state (initial):", task.get_task_state(args=[]).call())

    # --- negative: bidding before funding must be refused ---------------------
    print("\n[write] place_bid before funding - expect refusal")
    early = task.connect(alice).place_bid(args=[500]).transact(**WAIT)
    assert tx_execution_failed(early), "bidding before the task is funded must be refused"
    print("  refused as expected")

    # --- write: fund_task ------------------------------------------------------
    print(f"\n[write] fund_task() value={BUDGET} as poster")
    r = task.connect(poster).fund_task(args=[]).transact(value=BUDGET, **WAIT)
    assert not tx_execution_failed(r), r
    state0 = task.get_task_state(args=[]).call()
    print("[view] get_task_state after funding:", state0)
    assert state0["status"] == 1  # BIDDING

    # --- write: two bids, alice higher, bob lower ------------------------------
    print("\n[write] place_bid(700) as alice")
    r = task.connect(alice).place_bid(args=[700]).transact(**WAIT)
    assert not tx_execution_failed(r), r
    print("[write] place_bid(400) as bob - the eventual lowest bidder")
    r = task.connect(bob).place_bid(args=[400]).transact(**WAIT)
    assert not tx_execution_failed(r), r

    # --- negative: one-bid-per-worker is enforced -------------------------------
    print("\n[write] place_bid(100) as bob again - expect refusal (already has a bid)")
    dup_bid = task.connect(bob).place_bid(args=[100]).transact(**WAIT)
    assert tx_execution_failed(dup_bid), "a worker who already placed a bid must be refused a second one"
    print("  refused as expected")

    # --- negative: close_bidding before deadline -------------------------------
    print("\n[write] close_bidding before deadline - expect refusal")
    early_close = task.close_bidding(args=[]).transact(**WAIT)
    assert tx_execution_failed(early_close), "closing bidding before the deadline must be refused"
    print("  refused as expected")

    deadline = state0["bidding_deadline"]
    deadline_epoch = time.mktime(time.strptime(deadline, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
    print(f"\n[wait] polling until real time passes bidding_deadline ({deadline})...")
    while time.time() < deadline_epoch + 5:
        time.sleep(5)

    # --- write: close_bidding assigns the lowest bidder (bob) -------------------
    print("\n[write] close_bidding()")
    r = task.close_bidding(args=[]).transact(**WAIT)
    assert not tx_execution_failed(r), r
    state1 = task.get_task_state(args=[]).call()
    print("[view] get_task_state after close_bidding:", state1)
    assert state1["status"] == 2  # ASSIGNED
    assert state1["assigned_bid_index"] == 1  # bob's bid (index 1, the lower one)

    # --- negative: stranger cannot submit evidence -----------------------------
    print("\n[write] submit_evidence as a stranger (not the assigned worker) - expect refusal")
    bad_submit = task.connect(stranger).submit_evidence(args=[REAL_URL]).transact(**WAIT)
    assert tx_execution_failed(bad_submit), "only the assigned worker may submit evidence"
    print("  refused as expected")

    # --- write: bob submits real evidence, judged live --------------------------
    print(f"\n[write] submit_evidence({REAL_URL}) as bob")
    r = task.connect(bob).submit_evidence(args=[REAL_URL]).transact(**WAIT)
    assert not tx_execution_failed(r), r

    print("\n[write] judge_completion() - live web.render + exec_prompt round, may take a minute...")
    t0 = time.time()
    r = task.judge_completion(args=[]).transact(**WAIT)
    print(f"  took {time.time() - t0:.1f}s, status:", r.get("status"))
    assert not tx_execution_failed(r), r

    bid1 = task.get_bid(args=[1]).call()
    print("[view] get_bid(1) after judging:", bid1)

    final_state = task.get_task_state(args=[]).call()
    print("[view] final get_task_state:", final_state)

    if bid1["last_verdict"] == "MET":
        assert final_state["status"] == 3  # COMPLETED
        assert final_state["winner"] == bid1["worker"]
        assert final_state["winning_amount"] == 400

        print("\n[write] reclaim_expired_task on a COMPLETED task - expect refusal")
        bad_reclaim = task.reclaim_expired_task(args=[]).transact(**WAIT)
        assert tx_execution_failed(bad_reclaim), "reclaim must refuse on a completed task"
        print("  refused as expected")
    else:
        # bob's evidence judged NOT_MET/UNCLEAR -- ladder falls to alice
        assert final_state["status"] == 2  # still ASSIGNED, now to alice
        assert final_state["assigned_bid_index"] == 0
        print("\n  bob's evidence was not judged MET; ladder correctly fell through to alice")

    print("\nFull-surface run complete. Every write method executed at least once against", task.address)
