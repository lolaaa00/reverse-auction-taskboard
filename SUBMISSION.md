# Submission

**Title:** Reverse Auction Taskboard — Price-Ordered Task Assignment with a Fallback Ladder

**Description (1000 chars, verified programmatically against
`SUBMISSION_DESCRIPTION.txt` via
`python3 -c "print(len(open(path).read().rstrip(chr(10))))"`):** see
`SUBMISSION_DESCRIPTION.txt` in this folder — the exact text submitted, kept
as its own file so the character count is independently reproducible.

## Evidence links

- **GitHub repo:** https://github.com/lolaaa00/reverse-auction-taskboard
- **StudioNet contract address:** `0xA3d708D1f3849FD50A86120CDd0dc7881EF9437A`
  — canonical deployment, redeployed after the security fix below.
  Full-surface, convergence, and the worked example's own integration test
  were re-run against this deployment and two others to prove the fixed
  mechanism live (see README's "Measured on live consensus" for exact
  numbers: bob's second bid attempt was correctly refused, proving the
  one-bid-per-worker fix; the lowest bidder was still correctly assigned;
  a real judged round returned the exact canonical token MET in 39.6s
  under the strengthened equivalence principle, paying bob exactly his own
  bid), then this canonical address was deployed clean for the submission
  itself.
- **Explorer:** https://explorer-studio.genlayer.com/address/0xA3d708D1f3849FD50A86120CDd0dc7881EF9437A
- **Studio import:** open `https://studio.genlayer.com` and import
  `0xA3d708D1f3849FD50A86120CDd0dc7881EF9437A`

## Security fix (post-review, 2026-09-06)

An external reviewer (Joaquin) found that the equivalence principle only
required validators to agree on the judged band, "regardless of wording,"
leaving room for a synonym of MET (e.g. SATISFIED) to be accepted as the
same judgment under comparative consensus while `parse_verdict` — which
recognized only the exact literal enum — would silently default that
genuinely-agreed synonym to UNCLEAR, skipping a worker who actually
succeeded. Also found: no bounded recovery existed if judging never
converged after evidence was submitted, and the documented one-bid-per-
worker rule was never enforced in code.

All three are fixed: the equivalence principle and leader prompt now
require the exact literal token and explicitly reject synonyms; a new
`skip_unconverged_judgment()` gives a bounded recovery path once evidence
exists but judging never resolves; `place_bid` now rejects a second bid
from an already-bidding worker. See `docs/DESIGN.md` section 0 for the
full writeup.

## Git hygiene

Verified with:

```bash
git log --format='%B' -- "intelligent contract/(reverse-auction-taskboard)" | grep -i "co-authored\|claude\|generated with"
```

No matches — no AI/agent attribution in any commit message.
