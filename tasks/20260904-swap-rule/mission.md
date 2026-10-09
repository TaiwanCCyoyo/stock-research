# Mission — a low bar to stay, a high bar to take someone's slot

Pre-registered 2026-09-04, before any cell was run.

## 0. Whose idea this is, and why it is not one of the thirteen exits already tested

The owner, 2026-09-04:

> 我們需要有一個低標準的方法，讓我們長期滿倉在大多頭持有股票，又有一個高標準的方法在飆股機率
> 較高時，把手上機率最低的股票拋掉，然後換股

Every exit rule tested in `20260826-runner-retention` decided a sale from **the position's own
behaviour** — its rank, its ATR, its N-bar low, its give-back from peak. Thirteen arms, zero
qualified, and the incumbent rank exit won. **None of them ever asked whether there was anything
better to buy.** The entry rule and the exit rule have never been coupled. That is the untested
axis, and it is the one the owner named.

## 1. The evidence the rule is built on, and the evidence that constrains it

`20260826-tail-selection` is the reason this rule has the shape it has.

**The score is a good filter.** The probability of a +30% net move within twenty trading days is
2.95% across the pool, 4.71% inside the top 120, 8.12% inside the top 30 and 11.82% inside the top
ten — monotone, and it survives netting off the down tail.

**The score is not a good ranker.** Ten candidate secondary orderings inside the already-qualified
top sixty failed in both windows, 0/10, **with every arm's sign flipping between train and
holdout**. That report's words: not a weak signal, no signal.

So the owner's "把手上機率最低的股票拋掉" cannot be built on a fine ordering, because we measured
that ordering and it is not there. It can be built on a **coarse** one, because the bucket table
above is real. **This card's rule therefore fires only on a large rank gap and never on a small
one — which is precisely what today's `rank >= 30` exit does wrong.**

Two warnings carried in from measured results rather than intuition. Codex's
`20260829-rank-debounce-next-open` tested a one-bar rank-boundary confirmation — a cosmetic
deadband — and it failed on train. And `20260826-tail-selection` measured that re-ordering the
top sixty by a second feature turns the shortlist over **3.2x** faster: a swap rule manufactures
turnover, so turnover is a gate here and not an afterthought.

## 2. The rule: three zones

```text
rank < 30                 always safe
rank 30 .. exit_rank      safe only while nobody inside `challenge_rank` wants the slot
rank >= exit_rank         sold regardless, as today
```

The swap fires only when the book is **still full after the ordinary exits**, so a slot that frees
itself is never paid for with a swap. At most one swap per bar. A holding inside `min_hold_bars`
(20) is not swappable — the minimum hold exists to stop a rank-driven sale, and a swap is one.
`challenge_rank <= top_k`, so the freed slot is filled by the ordinary buy loop.

The swap-out rank is **fixed at 30**, V5's exit rank. It is not an axis. That is what makes the
`challenge_rank = 0`, `exit_rank = 30` cell exactly V5.

## 3. The thirteen cells, and what the control family does and does not isolate

```text
base                     exit 30,  no challenge      -- today's rule, must reproduce the anchor
hold60 / hold90 / hold120   exit H,   no challenge   -- THE CONTROL FAMILY
swap{H}_{C}              exit H,   challenge C       -- H in {60,90,120}, C in {3,5,10}
```

`hold60` and `hold120` are `20260826-runner-retention`'s `rank60` and `rank120`. **`rank120` was
the best single arm in that card's train window (pool share 13.8% against `rank30`'s 12.3%), so
the control here is not a straw man — it is the standing champion of the train window.**

**The control differs from a swap arm in two ways, not one**: no challenge rule, and a looser
effective retention floor — in `hold120` a holding at rank 45 is safe, in `swap120_5` the same
holding is challengeable. So the control family bounds _"would simply holding longer have done
this?"_. It does not isolate the challenge rule by itself. Stated now rather than discovered later.

## 4. Train only; the holdout stays sealed

Train 2019-01-02..2023-12-31. Holdout 2024-01-01..2026-08-14 **is not read unless a swap cell
passes every train gate below**, as in the two preceding cards.

## 5. Frozen train gates

On the +150% population, full stored floats. `C(x)` is the arm's own `hold{H}` control.

1. **Mechanism observed.** The arm's swap count is greater than zero. A rule that never fired
   reads as a negative and is actually a null run. The count is derived in the analyzer from the
   trades themselves — a SELL whose rank that day was inside `[30, exit_rank)` can only be a swap —
   rather than from a strategy counter the engine never writes out.
2. **Capture, against the control.** `capture_rate >= C(capture_rate)`. This is the attribution
   gate and it is deliberately not on pool share. `20260826-runner-retention` measured that in a
   ten-slot book retention and coverage are near zero-sum — `give30`/`give40` lifted participation
   11% → 29%/32% while capture fell 94% → 47%/33% and pool share barely moved. A wide `hold{H}`
   buys participation by giving up capture; **the swap rule's whole job is to buy that capture
   back.** Gating on pool share alone would hide whether the mechanism did anything.
3. **Participation, against the control.** `participation >= 0.90 x C(participation)` — the arm
   must keep most of what widening bought it while recovering capture, not simply undo the widening.
4. **Pool share, against `base`.** `pool_share >= base pool_share`. Rules 2 and 3 say the mechanism
   worked; this says it was worth doing.
5. **Turnover.** No more than 1.25x `base` and below 12 per slot per year. A swap rule that pays
   for capture with churn is the outcome the owner asked to avoid.
6. **Account.** Return positive and maximum drawdown no more than 5 percentage points worse
   than `base`.
7. **Plateau.** Rules 1-6 hold for three contiguous cells within one family — three consecutive
   `challenge_rank` at a fixed hold, or three consecutive holds at a fixed challenge.
8. **Anchor.** `base` reproduces `20260826-runner-retention`'s stored `rank30` cell trade for
   trade in the train window. `on_bar` is replicated in the arm rather than extended, so this gate
   is what protects the copy; checked on the holdout only if the holdout is legitimately opened.

## 6. The prediction, recorded before the run

I expect the `hold{H}` cells to beat `base` on pool share in train, because `rank120` already did.
**If the best cell in this card is a `hold{H}` cell, the swap rule adds nothing and the card is
negative even if swap cells also beat `base`.** Widening the exit is not this card's contribution;
it is last card's control that already won.

## 7. What this card may not conclude

It tests a swap rule **at ten slots**, on the standing sizing, under the standing same-close
execution convention. `20260904-execution-delay` closed negative and I wrote there that execution
resilience and capture may be two faces of one constraint — **that is a hypothesis from one
window's failure, not a measured link, and it is not a premise here.** If this card fails, "the
book was too small" is a candidate explanation to test, not a conclusion to report.

The named case 2344 is reported and never gated; its run is in the sealed holdout regardless.
