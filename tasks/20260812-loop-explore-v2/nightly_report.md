# Nightly Research Report

## Hypothesis

Tightening stop_loss_pct and loosening convergence_pct raises 2B's expectancy on 2330/2454 by cutting losing trades faster while allowing more valid entries.

## Summary

- Iterations run: 8
- Accepted (passed both windows): 4
- Candidate, failed holdout: 2
- Train failed: 2
- Rejected moves (out of declared bounds): 0
- Holdout evaluations: 6
- Stopped: max_iterations reached (8)

## Iteration Log

| Iteration | Decision                 | Rationale                                                                                                                 | Train Expectancy | Train Payoff | Train PF | Holdout Expectancy | Holdout Payoff | Holdout PF |
| --------- | ------------------------ | ------------------------------------------------------------------------------------------------------------------------- | ---------------- | ------------ | -------- | ------------------ | -------------- | ---------- |
| 1         | train_failed             | Iteration 1: Test hypothesis direction — tighten stop loss to cut losses faster, loosen convergence to allow more entries | -6410.0870       | 1.4978       | 0.7247   | n/a                | n/a            | n/a        |
| 2         | accepted                 | Iteration 2: Reverse direction — loosen stop loss to preserve winners, tighter convergence to filter entries              | 10021.8333       | 2.3700       | 1.5800   | 19512.4000         | 2.2505         | 3.3757     |
| 3         | candidate_failed_holdout | Iteration 3: Tighten convergence further to filter entries more strictly while keeping stop loss loose                    | 10100.6000       | 2.6310       | 1.4799   | 51874.0000         | n/a            | n/a        |
| 4         | candidate_failed_holdout | Iteration 4: Find sweet spot between tight and loose convergence                                                          | 7814.2222        | 2.3879       | 1.4046   | 51874.0000         | n/a            | n/a        |
| 5         | train_failed             | Iteration 5: Loosen convergence beyond 1.5 to see if it improves expectancy                                               | 3468.7879        | 1.7853       | 1.1604   | n/a                | n/a            | n/a        |
| 6         | accepted                 | Iteration 6: Tighten stop loss to 8.5 while keeping convergence at best 1.5                                               | 10187.7667       | 2.3930       | 1.5953   | 19512.4000         | 2.2505         | 3.3757     |
| 7         | accepted                 | Iteration 7: Tighten stop loss further to 8.0 (default) to compare                                                        | 11117.0000       | 2.5304       | 1.6869   | 19512.4000         | 2.2505         | 3.3757     |
| 8         | accepted                 | Iteration 8: Continue tightening stop loss to see peak expectancy                                                         | 11979.8333       | 2.6729       | 1.7819   | 19512.4000         | 2.2505         | 3.3757     |

## Recommended Next Step

- Iteration 8 passed gates on both train and holdout windows (params {'stop_loss_pct': 7.5, 'convergence_pct': 1.5}). Review it for daytime promotion.
