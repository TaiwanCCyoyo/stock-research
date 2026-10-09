# Mission

## Scope

- Market: Taiwan stocks
- Symbols: 2330, 2454, 2317, 2881, 2303, 2412, 1301, 2002 (liquid large caps across
  semis, financials, telecom, plastics, steel)
- Data: local K-line only
- Train: 2022-01-01 to 2024-12-31
- Holdout: 2025-01-01 to 2025-12-31

## Objective

Test whether the 2B setup's edge lives in the shape of the false break itself
rather than in the exit rules.

The strategy confirms a bottom 2B when price trades below the lowest low of the
last `swing_lookback` bars by more than `two_b_break_pct`, and then closes back
above that level within `reclaim_window` bars. Three parameters therefore define
the entire pattern:

| Parameter         | What it controls                                   |
| ----------------- | -------------------------------------------------- |
| `swing_lookback`  | How far back the reference high/low is drawn       |
| `two_b_break_pct` | How decisively price must poke through it to count |
| `reclaim_window`  | How quickly price must reclaim the level           |

The hypothesis is that the default `two_b_break_pct = 0.0` is too permissive:
any tick through the prior swing registers as a break, so most "reversals" are
noise. Requiring a real poke should trade less often but win bigger relative to
its losses — which is what this project's big-wins/small-losses philosophy asks
for, and what the `min_payoff_ratio = 2.0` gate measures.

Exit and sizing parameters are deliberately held at their defaults so that any
change in results is attributable to entry structure alone.

## Data constraints

Most of the cache stops at 2026-01 (1464 of 2035 symbols) after the 2026-08-13
data-loss incident; 469 symbols have been re-downloaded to 2026-08. Both
windows above end well inside the covered range, so every symbol in the universe
has complete data for the whole test. Do not extend either window past
2025-12-31 without re-checking coverage.

The usual benchmark, `0050`, did not survive the incident and is not in the
January archive either, so `2330` is used instead. It is the single heaviest
TAIEX constituent and a reasonable proxy, but it is one stock, not the market —
read benchmark-relative numbers with that in mind.

## Constraints

- No real trading
- No broker credentials
- No internet research
- Do not modify `StockProject/engine/`
- Entry structure only: exits and sizing stay at defaults
