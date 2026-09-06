"""
Adversarial direct-mode test suite for Reverse Auction Taskboard.

Each test name states the property under test, not the mechanics. Coverage
is weighted toward: input validation, funding gating, bidding-window
enforcement, the lowest-bid-wins deterministic tie-break, the price-ordered
fallback ladder on NOT_MET/UNCLEAR, the stalled-assignment skip path, the
MET/NOT_MET/UNCLEAR verdict branches including payout arithmetic, and every
value-moving branch.
"""

import json
import sys

sys.path.insert(0, "..")
from conftest import as_address, warp_to  # noqa: E402

CONTRACT = "contracts/reverse_auction_taskboard.py"

CRITERIA = "The page must show a completed, freshly repainted red front door."
URL = "https://example.com/evidence"
BUDGET = 1000

FUTURE = "2030-01-01T00:00:00Z"
PAST = "2020-01-01T00:00:00Z"
AFTER_DEADLINE = "2030-01-02T00:00:00Z"
STALL_PASSED = "2030-01-05T00:00:00Z"  # >72h after AFTER_DEADLINE assignment

MET = json.dumps({"verdict": "MET", "reason": "door repainted"})
NOT_MET = json.dumps({"verdict": "NOT_MET", "reason": "door not repainted"})
UNCLEAR = json.dumps({"verdict": "UNCLEAR", "reason": "page empty"})


def _deploy_only(direct_deploy, direct_vm, poster, criteria=CRITERIA, budget=BUDGET, deadline=FUTURE):
    with direct_vm.prank(poster):
        return direct_deploy(CONTRACT, criteria, budget, deadline)


def _fund(c, direct_vm, poster, amount=BUDGET):
    with direct_vm.prank(poster):
        direct_vm.value = amount
        c.fund_task()
        direct_vm.value = 0


def _deploy(direct_deploy, direct_vm, poster, budget=BUDGET, deadline=FUTURE):
    c = _deploy_only(direct_deploy, direct_vm, poster, budget=budget, deadline=deadline)
    _fund(c, direct_vm, poster, budget)
    return c


def _bid(c, direct_vm, worker, amount):
    with direct_vm.prank(worker):
        return c.place_bid(amount)


def _submit(c, direct_vm, worker, url=URL):
    with direct_vm.prank(worker):
        c.submit_evidence(url)


def _judge(c, direct_vm, body):
    direct_vm.mock_web(r".*", {"method": "GET", "status": 200, "body": "irrelevant, judged via mocked LLM"})
    direct_vm.mock_llm(r".*", body)
    try:
        return c.judge_completion()
    finally:
        direct_vm.clear_mocks()


# ---------------------------------------------------------------------------
# Deploy / constructor validation
# ---------------------------------------------------------------------------

def test_deploy_rejects_empty_criteria(direct_deploy, direct_vm, direct_alice):
    with direct_vm.expect_revert("EXPECTED"):
        _deploy_only(direct_deploy, direct_vm, direct_alice, criteria="   ")


def test_deploy_rejects_zero_max_budget(direct_deploy, direct_vm, direct_alice):
    with direct_vm.expect_revert("EXPECTED"):
        _deploy_only(direct_deploy, direct_vm, direct_alice, budget=0)


def test_deploy_rejects_past_bidding_deadline(direct_deploy, direct_vm, direct_alice):
    with direct_vm.expect_revert("EXPECTED"):
        _deploy_only(direct_deploy, direct_vm, direct_alice, deadline=PAST)


def test_deploy_leaves_task_awaiting_funding(direct_deploy, direct_vm, direct_alice):
    c = _deploy_only(direct_deploy, direct_vm, direct_alice)
    assert c.get_task_state()["status"] == 0


# ---------------------------------------------------------------------------
# fund_task
# ---------------------------------------------------------------------------

def test_fund_task_rejects_non_poster(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy_only(direct_deploy, direct_vm, direct_alice)
    with direct_vm.expect_revert("EXPECTED"):
        _fund(c, direct_vm, direct_bob)


def test_fund_task_rejects_wrong_amount(direct_deploy, direct_vm, direct_alice):
    c = _deploy_only(direct_deploy, direct_vm, direct_alice)
    with direct_vm.expect_revert("EXPECTED"):
        _fund(c, direct_vm, direct_alice, amount=BUDGET - 1)


def test_fund_task_twice_is_rejected(direct_deploy, direct_vm, direct_alice):
    c = _deploy_only(direct_deploy, direct_vm, direct_alice)
    _fund(c, direct_vm, direct_alice)
    with direct_vm.expect_revert("EXPECTED"):
        _fund(c, direct_vm, direct_alice)


def test_fund_task_opens_bidding(direct_deploy, direct_vm, direct_alice):
    c = _deploy_only(direct_deploy, direct_vm, direct_alice)
    _fund(c, direct_vm, direct_alice)
    assert c.get_task_state()["status"] == 1  # BIDDING


# ---------------------------------------------------------------------------
# place_bid
# ---------------------------------------------------------------------------

def test_place_bid_before_funding_is_rejected(direct_deploy, direct_vm, direct_bob):
    c = _deploy_only(direct_deploy, direct_vm, direct_bob)
    with direct_vm.expect_revert("EXPECTED"):
        _bid(c, direct_vm, direct_bob, 100)


def test_place_bid_rejects_zero_amount(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    with direct_vm.expect_revert("EXPECTED"):
        _bid(c, direct_vm, direct_bob, 0)


def test_place_bid_rejects_amount_over_max_budget(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    with direct_vm.expect_revert("EXPECTED"):
        _bid(c, direct_vm, direct_bob, BUDGET + 1)


def test_place_bid_after_deadline_is_rejected(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    warp_to(direct_vm, AFTER_DEADLINE)
    with direct_vm.expect_revert("EXPECTED"):
        _bid(c, direct_vm, direct_bob, 100)


def test_place_bid_returns_sequential_indices(direct_deploy, direct_vm, direct_alice, direct_bob, direct_charlie):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    i0 = _bid(c, direct_vm, direct_bob, 500)
    i1 = _bid(c, direct_vm, direct_charlie, 300)
    assert int(i0) == 0
    assert int(i1) == 1


# ---------------------------------------------------------------------------
# close_bidding: lowest-bid-wins, deterministic tie-break
# ---------------------------------------------------------------------------

def test_close_bidding_before_deadline_is_rejected(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 500)
    with direct_vm.expect_revert("EXPECTED"):
        c.close_bidding()


def test_close_bidding_with_no_bids_expires(direct_deploy, direct_vm, direct_alice):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    assert c.get_task_state()["status"] == 4  # EXPIRED_NO_BIDS


def test_close_bidding_assigns_the_lowest_bidder(direct_deploy, direct_vm, direct_alice, direct_bob, direct_charlie):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 500)
    _bid(c, direct_vm, direct_charlie, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    state = c.get_task_state()
    assert state["status"] == 2  # ASSIGNED
    assert state["assigned_bid_index"] == 1  # charlie's bid, the lower one


def test_close_bidding_tie_break_favors_earlier_submission(direct_deploy, direct_vm, direct_alice, direct_bob, direct_charlie):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)      # index 0, earlier
    _bid(c, direct_vm, direct_charlie, 300)  # index 1, same price, later
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    assert c.get_task_state()["assigned_bid_index"] == 0


# ---------------------------------------------------------------------------
# submit_evidence
# ---------------------------------------------------------------------------

def test_submit_evidence_rejects_non_assigned_worker(direct_deploy, direct_vm, direct_alice, direct_bob, direct_charlie):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 500)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    with direct_vm.expect_revert("EXPECTED"):
        _submit(c, direct_vm, direct_charlie)


def test_submit_evidence_rejects_non_http_url(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 500)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    with direct_vm.expect_revert("EXPECTED"):
        _submit(c, direct_vm, direct_bob, url="ftp://not-http.test/x")


def test_judge_before_evidence_submitted_is_rejected(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 500)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    with direct_vm.expect_revert("EXPECTED"):
        _judge(c, direct_vm, MET)


# ---------------------------------------------------------------------------
# judge_completion: MET pays winner + refunds difference
# ---------------------------------------------------------------------------

def test_met_verdict_completes_task_and_pays_exact_bid(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 400)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    verdict = _judge(c, direct_vm, MET)
    assert verdict == "MET"
    state = c.get_task_state()
    assert state["status"] == 3  # COMPLETED
    assert state["winner"] == as_address(direct_bob).as_hex
    assert state["winning_amount"] == 400


def test_not_met_advances_to_next_lowest_bidder(direct_deploy, direct_vm, direct_alice, direct_bob, direct_charlie):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)      # will be assigned first (lowest)
    _bid(c, direct_vm, direct_charlie, 500)  # fallback
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    assert c.get_task_state()["assigned_bid_index"] == 0
    _submit(c, direct_vm, direct_bob)
    verdict = _judge(c, direct_vm, NOT_MET)
    assert verdict == "NOT_MET"
    state = c.get_task_state()
    assert state["status"] == 2  # still ASSIGNED, now to charlie
    assert state["assigned_bid_index"] == 1
    bid0 = c.get_bid(0)
    assert bid0["tried"] is True


def test_unclear_also_advances_to_next_bidder(direct_deploy, direct_vm, direct_alice, direct_bob, direct_charlie):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    _bid(c, direct_vm, direct_charlie, 500)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    verdict = _judge(c, direct_vm, UNCLEAR)
    assert verdict == "UNCLEAR"
    assert c.get_task_state()["assigned_bid_index"] == 1


def test_all_bids_exhausted_closes_task(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    _judge(c, direct_vm, NOT_MET)
    state = c.get_task_state()
    assert state["status"] == 5  # EXHAUSTED
    assert state["assigned_bid_index"] is None


# ---------------------------------------------------------------------------
# skip_stalled_assignment
# ---------------------------------------------------------------------------

def test_skip_stalled_assignment_before_window_elapses_is_rejected(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    with direct_vm.expect_revert("EXPECTED"):
        c.skip_stalled_assignment()


def test_skip_stalled_assignment_rejects_once_evidence_submitted(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    warp_to(direct_vm, STALL_PASSED)
    with direct_vm.expect_revert("EXPECTED"):
        c.skip_stalled_assignment()


def test_skip_stalled_assignment_advances_ladder(direct_deploy, direct_vm, direct_alice, direct_bob, direct_charlie):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    _bid(c, direct_vm, direct_charlie, 500)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    assert c.get_task_state()["assigned_bid_index"] == 0
    warp_to(direct_vm, STALL_PASSED)
    c.skip_stalled_assignment()
    state = c.get_task_state()
    assert state["assigned_bid_index"] == 1
    assert c.get_bid(0)["last_verdict"] == "SKIPPED_STALLED"


# ---------------------------------------------------------------------------
# reclaim_expired_task
# ---------------------------------------------------------------------------

def test_reclaim_expired_task_rejects_while_bidding(direct_deploy, direct_vm, direct_alice):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    with direct_vm.expect_revert("EXPECTED"):
        c.reclaim_expired_task()


def test_reclaim_expired_task_pays_poster_full_budget_on_no_bids(direct_deploy, direct_vm, direct_alice):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    amount = c.reclaim_expired_task()
    assert int(amount) == BUDGET


def test_reclaim_expired_task_pays_poster_full_budget_on_exhaustion(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    _judge(c, direct_vm, NOT_MET)
    amount = c.reclaim_expired_task()
    assert int(amount) == BUDGET


def test_reclaim_expired_task_twice_is_rejected(direct_deploy, direct_vm, direct_alice):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    c.reclaim_expired_task()
    with direct_vm.expect_revert("EXPECTED"):
        c.reclaim_expired_task()


def test_reclaim_expired_task_rejected_when_completed(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    _judge(c, direct_vm, MET)
    with direct_vm.expect_revert("EXPECTED"):
        c.reclaim_expired_task()


# ---------------------------------------------------------------------------
# Model output robustness
# ---------------------------------------------------------------------------

def test_unparseable_model_output_defaults_to_unclear_never_met(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    verdict = _judge(c, direct_vm, "not json at all")
    assert verdict == "UNCLEAR"


def test_invalid_verdict_band_defaults_to_unclear(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    bad = json.dumps({"verdict": "MAYBE", "reason": "not valid"})
    verdict = _judge(c, direct_vm, bad)
    assert verdict == "UNCLEAR"


def test_get_bid_unknown_index_reports_not_exists(direct_deploy, direct_vm, direct_alice):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    assert c.get_bid(99)["exists"] is False


# ---------------------------------------------------------------------------
# Canonical verdict token: settlement never credits a synonym as MET (the
# reviewed fix). A model that outputs a semantically-equivalent but
# textually-different word instead of the exact literal enum must be
# treated as unparseable -- UNCLEAR, never a fabricated MET -- exactly
# like any other malformed output, since parse_verdict consumes the
# canonical token directly and never guesses at synonyms.
# ---------------------------------------------------------------------------

def test_a_synonym_for_met_is_never_credited_as_met(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    synonym = json.dumps({"verdict": "SATISFIED", "reason": "looks done to me"})
    verdict = _judge(c, direct_vm, synonym)
    assert verdict == "UNCLEAR", (
        "a synonym for MET (e.g. SATISFIED) must never be credited as MET; "
        "settlement consumes only the exact canonical token"
    )
    assert c.get_task_state()["status"] != 3  # never COMPLETED off a synonym


def test_lowercase_or_mixed_case_exact_token_is_still_accepted(direct_deploy, direct_vm, direct_alice, direct_bob):
    """parse_verdict upper()s before comparing, so case variation of the
    exact token itself (not a synonym) still resolves correctly -- only a
    genuinely different word is ever rejected."""
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    mixed_case = json.dumps({"verdict": "met", "reason": "door repainted"})
    verdict = _judge(c, direct_vm, mixed_case)
    assert verdict == "MET"


# ---------------------------------------------------------------------------
# One-bid-per-worker enforcement (the reviewed fix)
# ---------------------------------------------------------------------------

def test_place_bid_rejects_a_second_bid_from_the_same_worker(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 500)
    with direct_vm.expect_revert("EXPECTED"):
        _bid(c, direct_vm, direct_bob, 200)


def test_place_bid_still_allows_different_workers(direct_deploy, direct_vm, direct_alice, direct_bob, direct_charlie):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    id0 = _bid(c, direct_vm, direct_bob, 500)
    id1 = _bid(c, direct_vm, direct_charlie, 300)
    assert int(id0) == 0
    assert int(id1) == 1


# ---------------------------------------------------------------------------
# skip_unconverged_judgment: bounded recovery once evidence is submitted
# but judging never successfully resolves (the reviewed fix)
# ---------------------------------------------------------------------------

CONVERGENCE_NOT_PASSED = "2030-01-02T12:00:00Z"  # only 12 of the required 24h since submission
CONVERGENCE_PASSED = "2030-01-03T01:00:01Z"       # just past 24h since submission


def test_skip_unconverged_judgment_rejects_before_evidence_submitted(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    with direct_vm.expect_revert("EXPECTED"):
        c.skip_unconverged_judgment()


def test_skip_unconverged_judgment_rejects_before_window_elapses(direct_deploy, direct_vm, direct_alice, direct_bob):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    warp_to(direct_vm, CONVERGENCE_NOT_PASSED)
    with direct_vm.expect_revert("EXPECTED"):
        c.skip_unconverged_judgment()


def test_skip_unconverged_judgment_advances_ladder_after_window_elapses(
    direct_deploy, direct_vm, direct_alice, direct_bob, direct_charlie
):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)      # will be assigned first (lowest)
    _bid(c, direct_vm, direct_charlie, 500)  # fallback
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    assert c.get_task_state()["assigned_bid_index"] == 0
    _submit(c, direct_vm, direct_bob)
    warp_to(direct_vm, CONVERGENCE_PASSED)
    c.skip_unconverged_judgment()
    state = c.get_task_state()
    assert state["status"] == 2  # still ASSIGNED, now to charlie
    assert state["assigned_bid_index"] == 1
    bid0 = c.get_bid(0)
    assert bid0["tried"] is True
    assert bid0["last_verdict"] == "SKIPPED_UNCONVERGED"


def test_skip_unconverged_judgment_can_still_exhaust_the_task_if_no_bids_remain(
    direct_deploy, direct_vm, direct_alice, direct_bob
):
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    warp_to(direct_vm, CONVERGENCE_PASSED)
    c.skip_unconverged_judgment()
    assert c.get_task_state()["status"] == 5  # EXHAUSTED


def test_judge_completion_still_works_normally_after_unconverged_window_if_called_first(
    direct_deploy, direct_vm, direct_alice, direct_bob
):
    """The recovery path does not preempt a genuine judged verdict -- if
    judge_completion succeeds before anyone calls the recovery method, the
    normal MET path still applies."""
    c = _deploy(direct_deploy, direct_vm, direct_alice)
    _bid(c, direct_vm, direct_bob, 300)
    warp_to(direct_vm, AFTER_DEADLINE)
    c.close_bidding()
    _submit(c, direct_vm, direct_bob)
    warp_to(direct_vm, CONVERGENCE_PASSED)
    verdict = _judge(c, direct_vm, MET)
    assert verdict == "MET"
    assert c.get_task_state()["status"] == 3  # COMPLETED, not skipped
