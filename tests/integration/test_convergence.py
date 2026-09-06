"""
Convergence test: the property this primitive depends on validators agreeing
about is the banded verdict itself (MET / NOT_MET / UNCLEAR), grounded in the
same fetched page and the same immutable criteria. This asserts the STRICT
form: not "no bad outcome occurred" but that two independently deployed
tasks, each judging the assigned bidder's evidence against the byte-
identical criteria and evidence URL, converge on the IDENTICAL verdict band.
A weak assertion (e.g. "verdict is one of the three valid strings") would
pass even if the equivalence principle were silently letting validators
disagree and the leader's answer through unchecked - the exact "Fake
Consensus" failure mode the design record explicitly rejects
`prompt_non_comparative` to avoid.

Run with:
    gltest tests/integration/test_convergence.py -v -s --network studionet
"""
import time

from gltest import get_contract_factory, get_default_account, create_accounts
from gltest.assertions import tx_execution_failed

WAIT = dict(wait_interval=8000, wait_retries=60)

CRITERIA = "The named domain's own public homepage explicitly states it is reserved for illustrative use in documentation and examples."
REAL_URL = "https://example.com/"
BUDGET = 1000


def test_identical_evidence_converges_on_the_identical_verdict_band():
    poster = get_default_account()
    worker = create_accounts(1)[0]

    verdicts = []
    for i in range(2):
        print(f"\n--- run {i} ---")
        deadline = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 180))
        factory = get_contract_factory("ReverseAuctionTaskboard")
        contract = factory.deploy(account=poster, args=[CRITERIA, BUDGET, deadline], **WAIT)
        print(f"[deploy] ReverseAuctionTaskboard at {contract.address}")

        r = contract.connect(poster).fund_task(args=[]).transact(value=BUDGET, **WAIT)
        assert not tx_execution_failed(r), r

        r = contract.connect(worker).place_bid(args=[500]).transact(**WAIT)
        assert not tx_execution_failed(r), r

        deadline_epoch = time.mktime(time.strptime(deadline, "%Y-%m-%dT%H:%M:%SZ")) - time.timezone
        while time.time() < deadline_epoch + 5:
            time.sleep(5)

        r = contract.close_bidding(args=[]).transact(**WAIT)
        assert not tx_execution_failed(r), r

        r = contract.connect(worker).submit_evidence(args=[REAL_URL]).transact(**WAIT)
        assert not tx_execution_failed(r), r

        t0 = time.time()
        r = contract.judge_completion(args=[]).transact(**WAIT)
        print(f"  judge_completion took {time.time() - t0:.1f}s, status:", r.get("status"))
        assert not tx_execution_failed(r), r

        bid = contract.get_bid(args=[0]).call()
        print("  verdict:", bid["last_verdict"])
        verdicts.append(bid["last_verdict"])

    print("\nverdicts across both runs:", verdicts)
    assert verdicts[0] == verdicts[1], (
        "identical evidence (byte-identical criteria + evidence_url) must "
        "converge on the identical verdict band across independently "
        f"deployed tasks; got {verdicts[0]!r} vs {verdicts[1]!r}"
    )
    assert verdicts[0] in ("MET", "NOT_MET", "UNCLEAR")
