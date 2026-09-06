# Reverse Auction Taskboard

Assignment decided by **price**, not by submission order and not by
semantic similarity. A poster escrows a `max_budget` for one task; any
number of workers place **one** bid each — their own asking price, at or
below the budget — before a hard bidding deadline. Once bidding closes,
assignment goes deterministically to the **lowest** bidder (ties broken by
earliest submission). If that worker's evidence is judged `NOT_MET` or
`UNCLEAR`, assignment automatically falls through to the next-lowest
remaining bidder — a price-ordered fallback ladder. The eventual winner is
paid exactly their own bid; every unspent difference between `max_budget`
and that bid is refunded to the poster.

No owner, no admin key, no pausable switch. No bidder ever loses money to
bid — there is no bond — but an unresponsive assignee, or an assignment
whose judging never converges, can be permissionlessly skipped past after
a bounded window.

## Security fix (post-review, 2026-09-06)

An external reviewer (Joaquin) found three real gaps:

1. **Settlement was not fully bound by consensus.** The equivalence
   principle only required validators to agree on the judged *band*,
   "regardless of wording" — leaving room for a synonym of `MET` (e.g.
   `SATISFIED`) to be accepted as the same judgment under comparative
   consensus, while `parse_verdict` recognized only the exact literal enum
   and would silently default a genuinely-agreed synonym to `UNCLEAR`,
   skipping a worker who actually succeeded.
2. **No bounded recovery existed if judging never converged** after
   evidence was submitted — `skip_stalled_assignment` explicitly refused
   once evidence existed.
3. **The documented one-bid-per-worker rule was never enforced** in code.

All three are fixed:
- The equivalence principle and the leader prompt now both require the
  exact, literal, case-sensitive token (`MET` / `NOT_MET` / `UNCLEAR`) and
  explicitly reject synonyms as non-equivalent — the token validators
  converge on is the same token settlement consumes directly.
- A new `skip_unconverged_judgment()`, gated on
  `JUDGE_CONVERGENCE_WINDOW_HOURS` measured from evidence submission, gives
  a bounded recovery path once evidence exists but `judge_completion` never
  successfully resolves.
- `place_bid` now rejects a second bid from a worker who already has one.

See [`docs/DESIGN.md`](docs/DESIGN.md) section 0 for the full writeup.

## How this differs from its nearest siblings

- **Not `(bonded-claim-race)` with bids sorted by price instead of
  submission order.** That contract's claimants compete for one *fixed*
  payout in FIFO order, backed by a forfeitable bond. Here, price *is* the
  entire subject of the competition: assignment is decided by who bids
  lowest, nobody bonds anything to bid, and the poster's final cost is
  whatever price the eventually-successful worker actually bid — refunding
  every dollar of the difference from the escrowed max.
- **Not `(bounty-match-router)`.** That contract selects its single judged
  worker by embedding similarity; price never enters the selection at all.

See [`docs/DECISION_RECORD.md`](docs/DECISION_RECORD.md) for the full audit
of why this is genuinely unclaimed ground in this repo.

## Non-determinism budget

Exactly **one** real consensus round per assignment actually judged, inside
`judge_completion()`: a single `gl.nondet.web.render(url, mode="text")`
fetch followed by a single `gl.nondet.exec_prompt` call, both inside one
`leader()` closure, wrapped in one `gl.eq_principle.prompt_comparative`
round. Funding, bidding, closing the auction, and submitting evidence are
all pure deterministic Python.

## Safe-failure direction

A failed fetch or an unparseable model response both resolve to `UNCLEAR`,
which this contract treats identically to `NOT_MET` — assignment advances
to the next-lowest remaining bidder. Unparseable model output defaults to
`UNCLEAR`, never a fabricated `MET`. A failed assignee loses nothing (no
bond was ever required to bid) but simply loses the assignment. A synonym
of `MET` (e.g. `SATISFIED`) is likewise never credited as `MET` — settlement
consumes only the exact canonical token validators were required to
converge on.

## The price-ordered fallback ladder

```
close_bidding() --> assign lowest untried bid (tie: earliest submission)
judge_completion()=MET --> COMPLETED, winner paid their own bid, poster refunded the rest
judge_completion()=NOT_MET/UNCLEAR --> assign next-lowest untried bid
skip_stalled_assignment() (no evidence, after submission window) --> assign next-lowest untried bid
skip_unconverged_judgment() (evidence submitted, judging never converges) --> assign next-lowest untried bid
no untried bids remain --> EXHAUSTED, full max_budget reclaimable by poster
```

## API reference

```python
@gl.contract_interface
class IReverseAuctionTaskboard:
    class View:
        def get_task_state(self) -> dict: ...
        def get_bid(self, index: u256) -> dict: ...
    class Write:
        def fund_task(self) -> None: ...                       # payable, poster only, once
        def place_bid(self, amount: u256) -> u256: ...          # <= max_budget, before deadline, one per worker
        def close_bidding(self) -> None: ...                    # permissionless, post-deadline
        def submit_evidence(self, evidence_url: str) -> None: ...
        def judge_completion(self) -> str: ...                  # one nondet round, exact canonical token
        def skip_stalled_assignment(self) -> None: ...          # permissionless, post-submission-window, no evidence
        def skip_unconverged_judgment(self) -> None: ...        # permissionless, post-convergence-window, evidence submitted
        def reclaim_expired_task(self) -> u256: ...              # permissionless, post-expiry/exhaustion
```

## Worked consumer example

[`examples/auction_savings_ledger.py`](examples/auction_savings_ledger.py) —
an `AuctionSavingsLedger` contract that registers named entries pointing at
real tasks and reports how much `max_budget` was actually saved
(`max_budget - winning_amount`) by reading the primitive's own live
completed state — no forged savings possible for a pointer at an address
that was never actually deployed as a task.

## Running the tests

```bash
gltest tests/direct/                                             # 51 tests, mocked
gltest tests/integration/test_full_surface.py -v -s --network studionet
gltest tests/integration/test_convergence.py -v -s --network studionet
gltest tests/integration/test_auction_savings_ledger.py -v -s --network studionet
```

## Status

- `genvm-lint`: clean on both the primitive and the worked example.
- Direct-mode tests: **51 passing** (44 on the primitive, 7 on the worked
  example) — includes 9 new tests directly encoding all three reviewed
  fixes: a synonym for `MET` is never credited as `MET`, a second bid from
  the same worker is rejected, and `skip_unconverged_judgment` correctly
  gates on and advances past a non-converging judgment.
- StudioNet: **full-surface, convergence, and the worked example's
  integration test all pass, post-fix.** Canonical deployment (every write
  method exercised against it): `0xA3d708D1f3849FD50A86120CDd0dc7881EF9437A`.
- Explorer: https://explorer-studio.genlayer.com/address/0xA3d708D1f3849FD50A86120CDd0dc7881EF9437A
- Studio import: open [studio.genlayer.com](https://studio.genlayer.com) and
  import the address above.

## Measured on live consensus

Full-surface run against `0xA3d708D1f3849FD50A86120CDd0dc7881EF9437A` (3m47s
wall-clock, one real consensus round, post-fix):
- `place_bid()` before funding was correctly refused; `close_bidding()`
  before the deadline was correctly refused.
- Alice bid `700`, bob bid `400`. **Bob's second bid attempt (`100`) was
  correctly refused** — the one-bid-per-worker fix, proven live.
- After the deadline, `close_bidding()` correctly assigned **bob** — the
  lower bid — despite alice bidding first.
- A stranger's `submit_evidence()` attempt (not the assigned worker) was
  correctly refused.
- `judge_completion()` fetched `https://example.com/` fresh and ran a real
  5-validator consensus round under the strengthened equivalence
  principle, returning the exact canonical token **`MET`** in **39.6
  seconds** — bob was paid exactly his own bid (`400`), and
  `reclaim_expired_task()` on the now-`COMPLETED` task was correctly
  refused.

Convergence run across two independent deployments
(`0xF652E6Cd618cE7FD1685483aB5804e7CA55E1bB3` and
`0xFbACC07dcdaB7b74d56CF1Ea2286f0EF257400d6`), asserting the strict form —
that two independently deployed tasks, each judging the assigned bidder's
evidence against the byte-identical criteria and evidence URL, converge on
the identical exact canonical verdict token:
- Run 0: `judge_completion()` took **22.0s**, verdict **`MET`**.
- Run 1: `judge_completion()` took **33.6s**, verdict **`MET`**.
- Both runs converged on the identical band.

Worked-example run (primitive `0x74629FC2e7D76a7D37629F2Fa3bCcD00155497FB`,
ledger `0x95950D93f70a0A9F06D46b9D0e51585B8d3112cB`, 4m12s wall-clock):
- A real task (budget `1000`) was bid on at `600` and judged `MET` on real
  consensus; `savings_report` correctly reported `saved: 400`
  (`1000 - 600`), pulled live from the primitive.
- A pointer registered against a non-task address correctly reverted on
  read rather than silently reporting forged savings.

## Trust model

| Role | Can they suppress or bias the outcome? | Constraint |
|---|---|---|
| Poster | Sets `criteria`, `max_budget`, and `bidding_deadline` once; cannot change any afterward | No admin, no owner, no pause anywhere in this contract |
| Any bidder | May place exactly one bid before the deadline, at any price up to `max_budget`; cannot supply the verdict, only their own evidence once assigned | The model never sees bid prices; judgement is purely evidence-vs-criteria; a second bid from the same worker is rejected |
| Anyone else | May call `close_bidding()`, `judge_completion()`, `skip_stalled_assignment()`, and `skip_unconverged_judgment()` permissionlessly at any time they're valid | Payout always goes to whichever worker's bid actually wins, never the caller |

No case can be stranded: `reclaim_expired_task` is permissionlessly callable
if bidding closes with zero bids, or once every bid has been tried and
failed — in both cases the full `max_budget` returns to the poster. Neither
an unresponsive assignee nor a judged round that never converges can stall
the ladder indefinitely.
