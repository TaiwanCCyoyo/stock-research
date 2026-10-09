[繁體中文版本](docs/zh-TW/README.md)

# stock-research

This repository is an AI-agent-assisted workspace for Taiwan stock strategy research. Evidence-backed chat reports are the primary review interface; the existing dashboard is optional for K-line and trade drilldown. Root `AGENTS.md` is the project contract. Codex loads it natively. For Claude, use Claude Code 2.1.281 or later with its built-in `agents-md` support enabled: it loads `AGENTS.md` natively when no project or ancestor `CLAUDE.md`/`CLAUDE.local.md` takes precedence. This repository intentionally provides no `CLAUDE.md` import or injection hook. Before a Claude local review, confirm root `AGENTS.md` appears in `/context` or `/memory`; if native loading is unavailable or overridden, explicitly read the root contract before reviewing. See the [official instruction-loading documentation](https://code.claude.com/docs/en/memory#agentsmd).

The [research foundation](docs/en/research-foundation.md) defines shared measurement primitives, a headless artifact catalog, exposure/correction records and explicit one-job execution with verified reuse. It does not approve a strategy or replace the owner objective. Dashboard feature expansion is paused while research correctness and reproducibility are prioritized.

The main workflow is not "run Docker yourself" and not "launch an autonomous trading bot." The expected daily use is:

1. You discuss a strategy question with your agent.
2. The agent creates or continues a task under `tasks/`.
3. The agent writes or adjusts candidate strategies when needed.
4. The agent runs a backtest via `StockProject/backtest_cli.py` (or a task wrapper), using Docker-backed execution when isolation is useful.
5. Local artifacts are written first.
6. The agent reports from versioned evidence and inspects trades via MCP/CLI. Open the optional dashboard for visual drilldown, or sync a daily log to Notion when configured.

Local artifacts under `tasks/` are the source of truth. The dashboard and Notion are read-only or derived views on top of them.

For the local clean bootstrap, source preservation, external data locations and
pending publication gates, see [bootstrap record](docs/en/bootstrap-stock-research.md).

## Current Defaults

- **Shared development rules**: Codex and Claude Code use native planning for in-session plans, repository documentation for durable planning handoff, repository-owned skills and direct verification for implementation work, native local review and hosted PR review, and explicit commit/PR workflow owners.
- **Communication preferences**: Root `AGENTS.md` owns the communication contract alongside authorization and project conventions. Use concise text for simple answers and tables, diagrams or comparisons when relationships explain the task; use interactive HTML when filtering, parameter changes or evidence drilldown helps a decision. Keep takeaways, risks, uncertainty and verification results visible, with details available on demand. Honor the requested format, preserve durable documentation in Markdown or code, and provide a copy or export path for decisions or edits captured in an artifact. These preferences apply to task explanations and deliverables; code-review findings follow the review contract.
- **Layered checks**: Edit-time hooks provide read-only diagnostics; pre-commit owns Ruff fixes, formatting and type checks.
- **Security review contract**: Local and hosted reviews apply root `AGENTS.md`'s `CRITICAL`, `HIGH`, `MEDIUM`, and `LOW` classifications. Secrets in a diff are `CRITICAL`; `CRITICAL` and `HIGH` findings block completion unless the owner accepts the risk. The three former local reviewer roles are retired; the main session owns local review judgment.
- **Editor hygiene**: `.vscode/settings.json` trims trailing whitespace, keeps exactly one final newline, enables Ruff formatting for Python, and hides generated caches and local agent state from search/watchers.

## How To Start Today

Start with the [research program and handoff index](docs/en/research-program.md).
It links the current owner decisions, method/hypothesis register, prior experiments
and next bounded work. Its [reusable-artifact contract](docs/en/research-program.md#reusable-research-artifacts)
requires useful outputs to be discoverable by purpose, with data definitions, coverage,
access paths and producer/consumer links that another session can use. A literature review is not a tested strategy; a missing task
in this checkout is not evidence that no other session has tested it.

The normal entry point is a conversation with your agent, for example:

```text
Create today's strategy research task. I want to explore whether breakout signals can reduce false positives.
```

The agent should then:

- check the research program, existing method/experiment references and reusable data before creating or continuing a task under `tasks/`;
- inspect `mission.md` and `data_audit.json` when present;
- record the hypothesis, prior comparisons, source availability and bounded batch before evaluation; use the owner's staged research and registered-job contracts rather than an automatic sweep;
- execute only the approved batch with its fixed universe, dates, metrics and execution assumptions; literature/management tasks do not need a backtest;
- when the task has executed results, read `summary.json` (or `summary_<mode>.json` / `comparison.json` for multi-mode and multi-universe runs);
- when trade evidence is needed, inspect it with the trade-query MCP tools or `scripts/inspect_task_trade.py` rather than hand-parsing JSON;
- write the task's daily research log and update its method/hypothesis status plus the research program's next action, preserving negative and incomplete results;
- index useful outputs with their data contracts, access/reproduction paths and known consumers so another session can find, obtain and understand them;
- prepare or sync a Notion summary when Notion is configured.

You should not need to remember Docker commands during normal use. Docker commands belong in troubleshooting and verification.

## Install Only What You Use

The headless research, artifact-query CLI and stdio MCP paths do not need the
HTTP API, Node, Panel or Docker. For a research-only environment use
`uv sync --locked --no-dev` and `uv run --no-dev python ...` with the approved
task command. Use `uv sync --locked --group dev` for Python development.

Optional tools have explicit dependency groups:

- `uv run --group viewer python -m research_api`: HTTP API and React viewer.
- `uv run --group static-report python -m scripts.build_research_dashboard`:
  legacy Panel/Plotly static export. This scans eligible task summaries; do not
  use it across sealed research periods. It is not a replacement for the K-line viewer.
- Commit hooks and CI install both optional groups for their type/behavior checks;
  ordinary research does not require them.

Downloader/broker SDKs and unused UI/notebook packages are no longer root
dependencies. Data acquisition stays in the submodule's own environment. Private
tools using those packages must declare their own requirements; existing data
formats, task artifacts and historical import paths are unchanged.

## Reviewing Results: The Dashboard

```powershell
.\scripts\research\open_research_dashboard.cmd
```

This builds the `research_web/` frontend on first run, installs the optional `viewer` group, starts the FastAPI process, and opens `http://127.0.0.1:8503/`. After frontend source changes, run `npm ci` and `npm run build` in `research_web/` to refresh an existing build. The dashboard is a React app served together with the research API on a single port:

- browse and filter tasks by industry or universe;
- render K-line charts with moving averages, trade markers, and corporate-action markers, including institutional buy/sell context when available;
- drill into a trade to see its trigger reason, cash/position context, and realized PnL;
- compare capital modes (`shared` / `per_stock` / `unconstrained`) or universes side by side, with contention-affected symbols flagged;
- shut the local server down from an in-page control, or let it auto-stop once the browser tab's heartbeat stops.

Research artifacts are read-only through this API. Browser backtest launch and job
polling have been retired; run an explicitly approved task through its CLI instead.
Existing `.tmp/backtest_jobs` records and logs are not deleted or migrated.
The `/heartbeat` and `/shutdown` POSTs control only the viewer's lifecycle.

The retired Panel server has been removed. `.\scripts\research\open_research_api.cmd` starts the
HTTP server without the browser/auto-stop launcher; it also serves the frontend
if `research_web/dist` exists.

## Optional Task Preparation

The agent can run the task preparation tool for you. When a manual preparation command is useful, the current Windows entry point is:

```powershell
.\scripts\run_nightly_research.ps1 `
  -Task 20260510-breakout-review `
  -Codes "2330,2454,2317" `
  -Start 2024-01-01 `
  -Objective "Prepare a daily strategy research task."
```

This creates a task folder, checks local data, and writes a next prompt for the agent. It does not replace the daily research discussion.

## Current Architecture

```text
User + agent (Codex or Claude Code)
  -> daily strategy discussion
  -> task artifacts under tasks/
  -> approved Python task runner (e.g. StockProject/backtest_cli.py)
  -> local artifacts -> trade-query CLI / MCP -> evidence-backed chat report
                    -> optional API + React K-line / trade viewer
                    -> optional static export / Notion summary
```

`StockProject/backtest_cli.py` accepts explicit `--codes` or `@universe-name` references, a capital mode, and a corporate-action-aware price policy that keeps signal prices (adjusted) separate from execution/accounting prices (raw). Historical studies may use their own runner; this change does not unify engines or migrate study formats.

Docker remains an optional isolation configuration, **not a prerequisite or a
currently validated execution guarantee**. The existing Compose source mounts
omit required modules such as `StockProject/universe.py` and
`scripts/logging_utils.py`, and write access covers entire artifact directories.
Repair and verify those boundaries for the intended job before using it. Local
CLI execution does not provide Docker's network/filesystem isolation. Container
repairs, image builds and smoke runs are deferred, not silently replaced by
unrestricted local execution of untrusted candidates.

## Directory Map

Primary workflow:

- `StockProject/`: backtest engine, strategy base, `universe.py` universe resolution, and `backtest_cli.py`.
- `universes/`: named, version-controlled universe definitions (explicit code lists or classification rules) resolved via `@universe-name`.
- `scripts/`: task creation, nightly preparation, backtest, parameter sweep, report generation, trade-query MCP server/CLI, and smoke checks.
- `docker/`: Docker image for isolated research execution.
- `docker-compose.yml`: optional legacy Docker configuration; see the limitations above before use.
- `tasks/`: task-local missions, candidates, runs, summaries, comparisons, walkthroughs, and daily research logs.
- `stock-data-downloader/`: git submodule that owns price and corporate-action data acquisition; see Repository Responsibilities below.

Dashboard and API:

- `research_api/`: optional FastAPI task/price/trade reader and viewer lifecycle control (`/shutdown`, `/heartbeat`); no backtest execution or job manager.
- `research_web/`: React + Vite + lightweight-charts frontend (dashboard v2); `npm run build` output is served by `research_api`.
- `research_lab/`: shared data/presentation helpers with lazy Panel/Plotly imports only when rendering static reports; historical import paths remain available. Not a per-task artifact location.

Research outputs:

- `tasks/`: canonical per-task research artifacts.
- `reports/`: ad hoc or smoke-test outputs.

Documentation:

- `README.md`: English project orientation.
- `docs/zh-TW/README.md`: Traditional Chinese project orientation.
- `docs/zh-TW/Plan.md`: long-form project plan and direction.
- `docs/zh-TW/Phase2B-Runner.md`: lightweight runner usage notes.
- `docs/zh-TW/mission.example.md`: current daily research mission example.
- `docs/zh-TW/Docker_Install_Guide.md`: Docker Desktop setup notes for troubleshooting.
- `openspec/`: read-only historical capability contracts and design records. The OpenSpec workflow, CLI configuration, skills and OPSX commands are retired; current planning and implementation handoff use `docs/`.

Agent support:

- `.codex/`: Codex-specific instructions, hooks, private skills, and bounded execution/evidence helpers. Native Plan Mode handles interactive planning; Repository documentation handles durable cross-agent planning handoff. Native local review and hosted PR review follow root `AGENTS.md`.
- `.claude/`: Claude Code settings, hooks, focused slash commands, skills, subagents, and path-scoped coding rules. Development workflows use Native Claude capabilities, project-owned components, and autoloaded skills; GitHub, skill-creator, and Pyright LSP remain enabled.
- `.agents/`: shared local agent memory skeleton. Local memory content is ignored by Git.
- `.gemini/`: retained future Gemini agent layer for parity with Codex or future division of labor.
- `.vscode/`: workspace editor defaults that match file hygiene and Python Ruff workflows.

## Repository Responsibilities

This repo and the `stock-data-downloader/` git submodule have a firm ownership boundary:

- **`stock-data-downloader/` owns source acquisition and normalization**: downloading prices/events/institutional/revenue observations, converting minute bars to daily bars, and consolidating official/fallback quotes into `price_daily.parquet`. Source scripts run in its own `uv` environment. `scripts/run_daily.py` refreshes its source artifacts and backups; it does not refresh Stock's on-demand research derivatives. New source acquisition belongs in that integrated pipeline.
- **This repo owns the backtest engine, research workflow, API, dashboard, research price policies, indicators, patterns and derived caches**. It reads producer source artifacts without changing them; its own versioned derivatives live outside worktrees in `research_cache/` and have a separate additive backup. The 2026-10-08 owner boundary supersedes older generic "all processing in producer" wording: source consolidation stays in the producer, research calculations live in Stock. See [derived data](docs/en/research-derived-data.md) and [pattern definitions](docs/en/pattern-definitions.md).
- **Proactively improve the producer when research benefits**: the owner authorizes schema, index and derived-artifact changes that make data easier to find, understand or reuse. Develop in isolated submodule worktrees while preserving data, consumers, backup/restore and scheduled refresh. After owner merge, safely update the primary producer `main` and deliver Stock's gitlink/consumer PR. Check shared data before acquiring more; authorized acquisition and refresh use the primary producer's canonical data location with records other sessions can find, rather than leaving shared updates only in `.tmp/` or a worktree. Follow [development and delivery](docs/en/stock-agent-operations.md#submodule-development-and-delivery) and [canonical data updates](docs/en/stock-agent-operations.md#canonical-data-updates).
- `stock-data-downloader/` is developed as a standalone project with its own documentation and `AGENTS.md`, and must not reference this repo, its engine, or its dashboard by name.

## Notion Output

When configured, Notion should receive a daily research page derived from local task artifacts. A Notion page may include:

- strategy hypothesis;
- experiments run;
- key metrics;
- risks and caveats;
- next experiment ideas;
- task id and local artifact path.

Notion must not store secrets, broker credentials, API keys, or trading execution instructions.

## Manual Verification

Use only the relevant behavioral test or runtime smoke command for the changed behavior; normal commit hooks and CI own lint, formatting and type checks:

```powershell
uv run --group dev --group viewer --group static-report python -m pytest tests/ -q
```

`research_web/` has its own frontend checks: `npm run build` and `npm run lint` from that directory. Use synthetic fixtures for plumbing checks, not real candidate studies. Docker smoke commands are not part of the default checks: the old task smoke writes `tasks/sample` and must not be treated as a read-only diagnostic.

## Public Release Preparation

See [public release preparation](docs/en/public-readiness.md) for the source
inventory and bounded local scan commands, and [new-checkout availability](docs/en/bootstrap-stock-research.md)
for synthetic/private modes and preserved legacy sources. A passing scan does
not authorize a visibility change.

## Safety Rules

- No real trading.
- No broker credentials in tasks, Notion, Docker, or reports.
- Do not mount host `.env` or agent-private state (e.g. `~/.codex`) into research containers.
- Treat `StockProject/engine/` as read-only during strategy experiments.
- Generated or experimental strategy code belongs under task-local candidates, not the core engine.
- Research output is not investment advice.

## GitHub PR Workflow

Work on a non-default branch and deliver through a PR; never commit or push directly to `main`. The upstream sync and its policy-review follow-ups are task-authorized. CI and hosted review are active; server-side branch protection is unavailable on the current private-repository plan. See [Git workflow](docs/en/git-workflow.md), [PR setup](docs/zh-TW/pr-setup.md), and [review status](docs/en/pr-review.md). The `repository-checks` CI checks changed files and the shared tooling tests without private market data.

The owner authorizes automatic [post-merge cleanup](docs/en/git-workflow.md#post-merge-cleanup): after confirming its task PR merged into `main`, the acting session updates local `main` and removes its task worktree and local/corresponding `origin` branches without asking again. Preserve research artifacts and canonical data, keep the existing submodule handoff authority and production gates, and retain separate scheduler permissions.
