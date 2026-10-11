# Data contract: `owner-hhhl-labels.v1`

**Stable ID:** `owner-hhhl-labels.v1`. **Producer:** `scripts/build_owner_hhhl_labels.py` and
`scripts/capture_owner_hhhl_rule_hits.py` (run on 2026-10-08 as the task-local scripts at commit
`8e891eb`). **Reader:** `research_core.owner_hhhl_labels.load()`. **Status:** complete for
batches 1-5; immutable. A later labelling round gets a new version and does not edit these
files; both producers publish only into a directory that does not exist yet.

## What it answers

- What did the owner judge, on which chart, and with which notes?
- What exactly was the owner shown for each judgment?
- Which items in a blind batch were rule picks and which were controls?
- How were the published recall and precision numbers of batches 2-5 obtained?

## What it does not answer

- Whether any rule version is approved. Approval states live in `docs/en/pattern-definitions.md`
  and the batch result files.
- Future returns. These are judgments of chart shape only.
- Point-in-time knowledge. Mid-window breakouts were shown together with their aftermath.
  So these labels are hindsight judgments; do not use them as same-day features.

## `data/owner_labels.json`

```
{schema, exported_on, note,
 pages: {<page_id>: {artifact, collection, chart_set, documents: [<document>, ...]}}}
```

`page_id` is one of `r1 b2 b3a b3b b4a b4b b5a b5b reviews lines missed`. `chart_set` names the
zip member holding what was shown. Each document is the database row as written, keyed by `id`,
which matches the chart set item's `id`.

| schema                                        | fields                                                                                                                                                                                                                                      | meaning                                                |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------ |
| `hhhl-label.v2`..`v4` (r1, b2, b3a, b4a, b5a) | `points[]`: `d` date, `k` = `L` low / `H` high / `BO` breakout, `rel` = `first` / `higher` / `same` / `lower` vs the previous point of the same kind, `ref` optional comparison date, `cat` breakout tag; `verdict` chart-level tag; `note` | the owner's own structure reading                      |
| `hhhl-judge-b3b/b4b/b5b.v1`                   | `verdict` = `yes` 算 / `no` 不算 / `unsure` 看不出來 / `""` unanswered; `reasons[]`; `note`                                                                                                                                                 | judgment of one breakout day, blind to rule or control |
| `hhhl-review.v1`                              | `verdict`, `reasons[]`, `rule_cat`, `note`                                                                                                                                                                                                  | critique of a rule breakout                            |
| `hhhl-lines.v1`                               | `answer` (for example `close` = close enough), `viewed_k`, `best_k`, `note`                                                                                                                                                                 | whether the drawn big-range line is right              |
| `hhhl-missed.v1`                              | `answer` (for example `should`), `owner_date`, `reason`, `note`                                                                                                                                                                             | whether a breakout v3 missed should have been caught   |

Breakout tags `cat` counted as owner buy-breakouts: `像`, `區間突破`, `底部打底`, `漲停急拉後整理`.
Other values (`不像`, `看不出來`, empty) are not positives. `saved_at` is UTC.

## `data/chart_sets.zip`, `data/history.zip`, `data/rule_sources.zip`

Each zip has a `manifest.json` with the SHA-256 of every member.

- `chart_sets.zip` `sets/<name>.json`: what each page showed, as a list of items
  `{id?, code, date, bars: [[date, open, high, low, close], ...], ...}`.
    - B sets carry `kind` (`rule`, `control`, and in batch 5 `small_range`) plus rule tags
      (`cat`, `context`, `big_hhhl`, `limit_up`).
    - Bars are the prices the page drew: atlas-v2 prices before batch 4, and cash-dividend
      reference-factor prices (`adjprice`) from batch 4 on.
- `history.zip`:
    - `sets/`: early example sets and the dropped batch 5 extension set;
    - `earlier_dumps/<dump>/...`: the local dumps the result files were scored from;
    - `pages/`: page sources (`*_body.html`, templates) and `owner_labels.py` (chat transcription).
- `rule_sources.zip` `rules/`: the exact rule sources the capture ran.

## `data/rule_hits.json`

`batches.<b2|b3a|b4a|b5a>.<chart id> = {window: [first, last], sessions: [...], events: {<variant>: [dates]}}`.
`sessions` is the stock's own session list from 3 sessions before the window to 3 after, so
matching within +-1 session never needs other data. The rule sources are pinned by
`data/rule_sources.zip`; the market data read is pinned by `data/rule_hits_inputs.zip`.

## `data/rule_hits_inputs.zip`

`inputs.json`: the SHA-256 of every atlas-v2 table the capture read (120 codes), and, for the 60 codes
run on `adjprice`, the exact corporate-action rows applied (`ex_date`, `event_type`, `price_factor`).
A recapture against changed data can be detected by comparing these.

## `data/timeline_receipt.zip`

`receipt.json`: per batch, the preregistration's and chart sets' filesystem modification times, sizes
and SHA-256 in the `.tmp` working directory, whether the preregistration equals the committed copy,
and the owner's first `saved_at`. The first two are retrospective filesystem metadata recorded on
2026-10-08, not cryptographic proof. The verifier checks the third against the archive.

## Access

Everything is Git-tracked under `tasks/20261010-owner-hhhl-labels/`. Read it in code with
`research_core.owner_hhhl_labels.load()`, which refuses the archive unless every check below
passes, and reuse `buy_points`, `recall` and `precision` from the same module when scoring a
new rule against these labels. To check the archive and recompute every published number:

```
uv run python scripts/verify_owner_hhhl_labels.py --check
```

The check re-hashes every zip member, compares every owner document with its archived dump, and
checks each artifact against a digest pinned in `research_core/owner_hhhl_labels.py` (`PINNED`).
The v1 digest is SHA-256 of `json.dumps(sort_keys=True, ensure_ascii=False)` (`contract_digest`);
it is also stored inside `rule_hits_inputs.zip`, so v1 keeps that exact form. A new export or
capture is a new dataset version with its own pins.

The live databases remain at the artifact URLs in `owner_labels.json`, but this archive is the
canonical copy for research. Do not read the live pages as the reference.

## 2026-10-10 old-name migration

By owner decision, path and name strings inside this archive were rewritten to this checkout
(`docs/en/bootstrap-stock-research.md#old-name-migration-2026-10-10`): `rule_hits.json`, its
input receipt, and the `detect.py`/`adjprice.py` default paths inside `rule_sources.zip`. The
atlas-v2 tables the capture read were relabelled (`dataset_id` only), so the 120 table digests in
`rule_hits_inputs.zip` now name the relabelled bytes. No capture was re-run: every rule day and
every recomputed batch number is unchanged. The exact capture-time bytes are in Git at
`87366ba`, and the predecessor checkout still holds the original tables.
