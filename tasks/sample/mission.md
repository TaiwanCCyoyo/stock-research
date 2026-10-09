# Mission

## Scope

- Market: Taiwan stocks
- Symbols: 2330
- Data: local K-line only
- Start: 2022-01-01
- End: latest available local data

## Constraints

- No real trading
- No broker credentials
- No internet research
- Do not modify `StockProject/engine/`
- Use Docker for generated strategy execution

## Objective

- Verify that the 2B moving-average-convergence template strategy stored inside a task can be executed by the Docker research runtime.
- Write machine-readable output under `tasks/sample/runs/`.
- Keep strategy design simple; this task is a pipeline smoke test, not a performance benchmark.
