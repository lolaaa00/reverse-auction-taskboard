# Decision Record — Reverse Auction Taskboard

## What every existing sibling already owns

- **`(bonded-claim-race)`**: many claimants attempt one bounty, judged one at a time in
  **submission order**, with a bond that punishes a bad attempt. There is no notion of
  price at all — every claimant competes for the identical fixed bounty.
- **`(bounty-match-router)`**: a poster's requirement is matched against a pool of
  workers by **embedding similarity**, and only the single best-ranked worker is ever
  judged. Price is never part of the selection at all.
- **`(spec-compliance-bounty)`, `(deliverable-escrow)`, `(case-vault-factory)`**: a
  single named party attempts a single fixed-price case. No competition for assignment
  exists in any of them.

**The genuinely unclaimed ground:** assignment decided by **price**, not by submission
order and not by semantic similarity — a reverse (Dutch-style-by-bid) auction where
workers bid the amount they'd charge to complete a task, the *lowest* bidder is assigned
deterministically once bidding closes, and if that assigned worker's delivered evidence
is judged NOT_MET/UNCLEAR, assignment automatically falls through to the *next-lowest*
bidder — a permissionless, price-ordered fallback ladder, not a race and not a ranked
shortlist of one.

## Why price-ordered fallback, not bonded-claim-race's submission-ordered fallback

`(bonded-claim-race)` already owns "queue of competing attempts, judged one at a time,
advance on failure." Rephrasing that with bids sorted by price instead of submission
timestamp would not be a new primitive — it would be the same mechanism with a
different sort key. What makes this genuinely different is that **price here decides
who gets to attempt AT ALL, before any evidence exists**: workers commit to a price
during a bidding window that closes before work begins, and the entire point of the
auction is to spend as little of the poster's escrowed budget as possible while still
guaranteeing the work gets attempted by *someone* if any bid was ever submitted. A
failed lowest bidder does not just forfeit a bond and vacate a queue slot (as in
`(bonded-claim-race)`) — the *next* bidder is assigned the task at *their own bid
price*, and the poster's final cost is always whatever price the worker who actually
succeeded bid, refunding every unspent difference between the escrowed max budget and
that final price. Nobody in `(bonded-claim-race)` gets a variable payout depending on
who wins; here, the payout amount itself is the entire subject of the competition.

## Why a hard bidding deadline, not open-ended bidding

If bids could arrive after assignment already happened, "lowest bidder wins" would be
meaningless — a bidder could always underprice an already-assigned bidder after seeing
them fail, turning the auction into a disguised version of `(bonded-claim-race)`'s
submission race. A hard `bidding_deadline`, after which no further bids are accepted and
assignment becomes a pure deterministic sort over the sealed set of bids already placed,
is what makes the auction an actual auction rather than a race with an extra price field
bolted on.

## Rejected shapes

- **Sealed-bid commit-reveal auction** — rejected as unnecessary complexity for this
  primitive's stated scope: bids are already public on-chain the moment they're
  submitted (this is a public blockchain), so a commit-reveal scheme defends against a
  threat model (front-running a bid) that a bidding-deadline-then-sort design already
  neutralizes just as well without an extra round trip per bidder.
- **English (ascending) auction where bidders can see and undercut each other's price
  live** — rejected: turns the mechanism into `(bonded-claim-race)`-with-a-live-price-
  war, and requires an open-ended bidding window with no natural close condition other
  than "nobody undercuts for N blocks," which reintroduces exactly the race-condition
  ambiguity a hard deadline avoids.
- **Assigning to the lowest bidder permanently, with no fallback on failure** —
  rejected: that would strand the entire escrowed budget the moment the cheapest bidder
  either never delivers or delivers badly, with no path back to the second-cheapest
  bidder who was still willing to do the work.
