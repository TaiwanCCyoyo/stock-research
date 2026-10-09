# Mission -- Is the structural ratchet the mechanism, or was it Darvas's entry?

## The confound this task exists to break

`tasks/20260820-kline-archetype-extension` found that the Darvas box strategy had the
best trade shape of six archetypes (profit factor 4.90, payoff 3.91, win rate 45.2%)
and by far the tightest drawdowns (holdout −6.9% to −15.2%, against buy-and-hold's
−21.9% to −39.3%). That report then suggested structural stops might beat ATR stops.

**It could not support that claim, because Darvas differs from the ATR-stopped
breakouts in two places at once**: a different entry (box breakout confirmed by volume)
_and_ a different exit (box-floor ratchet instead of a fixed ATR multiple). Any of the
observed advantage could belong to either half.

This task changes exactly one of them.

| arm            | file                                  | entry                          | exit                                                                           |
| -------------- | ------------------------------------- | ------------------------------ | ------------------------------------------------------------------------------ |
| `atr_baseline` | `candidates/donchian_atr_baseline.py` | 20-day closing high above MA60 | close below the 10-day low, or entry − 2×ATR fixed at entry                    |
| `box_ratchet`  | `candidates/donchian_box_ratchet.py`  | **identical**                  | stop at the most recently confirmed Darvas box floor, ratcheted up, never down |

`donchian_atr_baseline.py` is a byte-for-byte copy of the 20260816 study's
`donchian_breakout.py`. Its `train`, `holdout` and `holdout_shared` numbers must
reproduce that study's exactly; any divergence is a bug in this harness, not a finding.

## Why this is the right next experiment

**It isolates the mechanism.** Entry held constant, exit swapped. A win here is
attributable; a win in the 20260820 grid was not.

**It fixes the statistical power problem for free.** The 20260820 verdict was 0/15,
and ten of those failures were the pre-registered ≥30-closed-trade floor rather than a
negative result -- Darvas's own entry fired only 12–29 times per basket per window. The
Donchian entry fires 191–213 times. Grafting the ratchet onto it tests the exit at a
sample size that can actually carry a conclusion, without relaxing any threshold.

**Both outcomes are actionable.** If the ratchet holds up, it is a component that can
be bolted onto any breakout entry, and the next step is to try it on S2 and S3. If it
does not, then Darvas's advantage lived in its entry, and the priority becomes solving
that strategy's sample-size problem instead.

## Single-variable discipline, verified mechanically

`verify_isolation.py` parses both files and compares the AST of `should_enter` and
`equal_notional_quantity` with docstrings stripped. Both must be identical, and
`warmup()` must return the same number for both (61), so neither arm gets a longer
effective trading window. This runs as a gate before the sweep, because a silent drift
in the entry would turn the whole experiment into a two-variable comparison that still
looks like a one-variable one.

## Two forced deviations in the grafted exit

Both are consequences of putting a box-based stop behind a non-box entry, and both are
chosen to avoid biasing the comparison:

- **`high_lookback` is 20, not Darvas's 120.** Boxes must form around the same highs the
  Donchian entry fires on. At 120 the machine would seldom hold a confirmed box at the
  moment of a 20-day-high entry, the fallback below would carry nearly every trade, and
  the result would measure the fallback rather than the ratchet.
- **A fallback initial stop is required.** A Donchian breakout is not a box breakout, so
  the entry can fire mid-formation with no confirmed box. The fallback is the lowest low
  of the last 10 bars -- deliberately the same window the baseline uses for its channel
  exit, so neither arm starts with a structurally tighter stop. `analyze_isolation.py`
  reports what fraction of entries used the fallback; if that fraction is high, the
  comparison is weaker than it looks and the report must say so.

## Protocol -- unchanged from both prior studies

Train 2019-01-02..2023-12-31, holdout 2024-01-01..2026-08-14; the same five
`universes/*_liquid20.json` baskets; 10,000,000 TWD; equal-notional 10% of _initial_
capital in integer shares; `unconstrained` as the primary lens with `shared` for return
and drawdown; `stock_pool_buy_and_hold_return_rate` as the comparator because 0050 has
no local day file. 2 arms × 5 universes × 4 windows = 40 cells.

## Pre-registered acceptance rule

Written before any cell was run. The comparison is **paired** -- same entry, same
symbols, same bars -- so this asks whether the exit swap helps, not whether either arm
is good in absolute terms.

1. **Primary metric**: holdout `unconstrained` average full PnL per entry, as in both
   prior studies.
2. **The ratchet wins on signal quality** only if it beats the baseline in **at least 4
   of 5 baskets in the holdout** _and_ the pooled (five-basket) holdout figure is higher.
   Three of five is noise at this basket count.
3. **The ratchet wins on risk** only if its return/|max drawdown| beats the baseline's
   in at least 4 of 5 baskets in **both** `train_shared` and `holdout_shared`.
4. **Direction must be consistent.** A metric that improves in the holdout but degrades
   in the train window is reported as a non-finding, exactly as in the prior two studies.
5. **A clean negative is a result** and gets the same space in the report as a positive.

## Inherited limitations

Survivorship tilt in the baskets, close-to-close fills with no slippage model beyond fee
and the 0.3% transaction tax, and a bull-market bias in both windows. Unchanged from the
prior studies and not re-litigated here.
