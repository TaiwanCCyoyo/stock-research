---
name: stock-research-query
description: Query local stock research task artifacts through deterministic scripts or a local MCP server. Use when Codex needs to answer trade-reason, same-day values, backtest evidence, position sizing, cash, signal reason, or task trade-list questions from task artifacts.
---

# Stock Research Query

## Purpose

Use this skill before manually reading task JSON or price CSV files when answering local stock research evidence questions.

Primary examples:

- Why did a stock buy or sell on a date?
- What were the same-day OHLC, moving averages, convergence, trend, and signal values?
- How much cash was available before a trade, and how was quantity/cost computed?
- Which task trades should be inspected before choosing one specific trade?

## Preferred Tool Flow

1. Use the local MCP tools if they are already connected. Do not start a stdio server in a
   foreground shell for a one-off query; starting it does not connect it to this client.

The server exposes:

- `inspect_task_trade`
- `list_task_trades`
- `list_research_tasks`

2. If MCP is not available in the current client, use the CLI fallback:

```powershell
uv run python scripts/inspect_task_trade.py --task <task> --code <code> --date <YYYY-MM-DD> --action <BUY|SELL>
```

3. Treat the returned JSON as the source of truth for the response. Do not recompute from raw artifacts unless the tool is missing a needed field.

For report-only studies, `uv run --no-sync python -m scripts.research_evidence catalog`
lists artifact availability without opening economics. Task names and file existence
do not imply a passing or independently confirmed study.

Price inspection fails when a recorded path is missing; do not silently replace it
with current data. An explicit `--data-path` override is a non-original view. Report
`data_provenance`: the resolved path alone does not verify the snapshot's hash.

## Response Rules

- Return user-facing explanations in Traditional Chinese.
- Preserve numeric values from tool output.
- Separate facts from interpretation.
- Mention the tool output fields used for verification when the user asks for validation.
- If the requested trade is ambiguous, call `list_task_trades` first, then inspect the selected `trade_id`.

## Output Contract

`inspect_task_trade` returns structured JSON with:

- task, query, trade_id, trade_index
- trade
- signal_events
- cash_context
- price_context
- strategy_params

`list_task_trades` returns compact rows with:

- trade_id
- date
- code
- action
- price
- qty
- total
- signal_reason

`list_research_tasks` returns task ids and artifact availability flags.
