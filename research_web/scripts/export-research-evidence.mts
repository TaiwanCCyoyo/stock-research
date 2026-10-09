import { createHash } from "node:crypto";
import { mkdir, readFile, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync, gzipSync } from "node:zlib";
import { validateBundle } from "../src/domain/opportunities/model.ts";
import { validateResearchBundle } from "../src/domain/opportunities/research.ts";
import { withEtfReferences } from "../src/domain/opportunities/etfReferences.ts";
import type {
    SavedResearchBundle,
    SavedResearchRun,
} from "../src/domain/opportunities/research.ts";
import type {
    OpportunityBundle,
    OpportunityPortfolio,
    ResearchMethod,
    SourceRef,
} from "../src/domain/opportunities/types.ts";

const ADAPTER_VERSION = "saved-ledger-evidence-adapter.v2";
const MONEY_TOLERANCE = 1e-6;
type RecordValue = Record<string, unknown>;
interface Definition {
    filename: string;
    portfolioId: string;
    taskId: string;
    runId: string;
    verdict: string;
    status: ResearchMethod["status"];
    rules: string[];
    conclusion: string;
}
const DEFINITIONS: Definition[] = [
    {
        filename: "20261002-add-retry--normal-v1.json",
        portfolioId: "stock:20261002-add-retry:normal-v1",
        taskId: "20261002-add-retry",
        runId: "normal-v1",
        verdict:
            "normal_development_screen_passed_final_validation_not_approved",
        status: "exploratory",
        rules: [
            "起始 200 萬元、最多五檔；一張試單受原 10 萬元可負擔限制。",
            "持有經濟報酬達 +10% 時，以原 30 萬元 gross target 加碼；每日 rank>30 或未上榜退出。",
            "原加碼單已確認終止且完全未成交後，僅在第一個允許決策時重查條件，最多多一次次交易日重試。",
            "部分成交、不明終止狀態、已重試或不符合當下條件均不重試；不持續追蹤至成交。",
        ],
        conclusion:
            "正常成交情境通過開發篩選，值得繼續研究；尚未最終批准，也未證明延遲問題已解決。",
    },
    {
        filename: "20261002-entry-extension-cap--cap-v1.json",
        portfolioId: "stock:20261002-entry-extension-cap:cap-v1",
        taskId: "20261002-entry-extension-cap",
        runId: "cap-v1",
        verdict: "candidate_failed",
        status: "failed",
        rules: [
            "保留同一 daily 基礎策略、收盤後決策及次交易日模型成交。",
            "僅於初始 BUY 前剔除決策日原始 ret60>50% 的提案；不重新排序、不用較低順位補入。",
            "不限制加碼，保留原每日 rank30／未上榜退出條件。",
        ],
        conclusion:
            "候選已完成且失敗；開發期報酬與命中廣度不足以晉級。帳本對帳完成不改變失敗結論。",
    },
];

export interface LedgerInput {
    filename: string;
    path: string;
    sha256: string;
    value: unknown;
}
export interface EvidenceSources {
    catalogPath: string;
    catalogHash: string;
    receiptPath: string;
    receiptHash: string;
}
function fail(reason: string): never {
    throw new Error(`Invalid research evidence: ${reason}`);
}
function object(value: unknown, label: string): RecordValue {
    if (!value || typeof value !== "object" || Array.isArray(value))
        fail(`${label} must be an object`);
    return value as RecordValue;
}
function list(value: unknown, label: string): unknown[] {
    if (!Array.isArray(value)) fail(`${label} must be an array`);
    return value;
}
function text(value: unknown, label: string): string {
    if (typeof value !== "string" || !value.trim())
        fail(`${label} must be a nonempty string`);
    return value;
}
function strings(value: unknown, label: string): string[] {
    return list(value, label).map((entry) => text(entry, label));
}
function finite(value: unknown, label: string, minimum = -Infinity): number {
    if (typeof value !== "number" || !Number.isFinite(value) || value < minimum)
        fail(`${label} must be finite and >= ${minimum}`);
    return value;
}
function count(value: unknown, label: string): number {
    const result = finite(value, label, 0);
    if (!Number.isInteger(result)) fail(`${label} must be an integer`);
    return result;
}
function hash(value: unknown, label: string): string {
    const result = text(value, label);
    if (!/^[a-f\d]{64}$/i.test(result)) fail(`${label} must be SHA-256`);
    return result.toLowerCase();
}
function sha256(value: Buffer | string): string {
    return createHash("sha256").update(value).digest("hex");
}
function close(
    actual: number,
    expected: number,
    label: string,
    tolerance = MONEY_TOLERANCE,
): void {
    if (Math.abs(actual - expected) > tolerance)
        fail(`${label} does not reconcile (${actual} versus ${expected})`);
}
function day(value: unknown, label: string): string {
    const timestamp = text(value, label);
    if (
        !/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d\+08:00$/.test(
            timestamp,
        ) ||
        !Number.isFinite(Date.parse(timestamp))
    )
        fail(`${label} must retain an Asia/Taipei timestamp`);
    const result = timestamp.slice(0, 10);
    if (new Date(`${result}T00:00:00Z`).toISOString().slice(0, 10) !== result)
        fail(`${label} has invalid date`);
    return result;
}
function nextDay(value: string): string {
    return new Date(Date.parse(`${value}T00:00:00Z`) + 86_400_000)
        .toISOString()
        .slice(0, 10);
}
function securityId(value: unknown): string {
    const code = text(value, "security code").replace(/^TW:/, "");
    if (!/^[\dA-Za-z]+$/.test(code)) fail("expected Taiwan security code");
    return `TW:${code}`;
}
function nullableNumber(value: unknown, label: string): number | null {
    return value === undefined || value === null ? null : finite(value, label);
}
function finiteJson(value: unknown): void {
    if (typeof value === "number") finite(value, "JSON number");
    else if (Array.isArray(value)) value.forEach(finiteJson);
    else if (value !== null && typeof value === "object")
        Object.values(value).forEach(finiteJson);
}

/** Adapt only these two explicitly reviewed runs; never replay source events. */
function adaptLedger(
    input: LedgerInput,
    definition: Definition,
    calendar: Set<string>,
    sourceIds: string[],
    verifiedNativeHashes: ReadonlySet<string>,
) {
    const ledger = object(input.value, "ledger");
    if (
        ledger.schema !== "native-ledger-presentation.v1" ||
        ledger.status !==
            "reconciled_accounting_export_not_strategy_approval" ||
        ledger.portfolio_id !== definition.portfolioId
    )
        fail("unsupported ledger identity/status");
    const units = object(ledger.units, "units");
    if (
        units.money !== "TWD" ||
        units.weights !== "fraction" ||
        units.quantities !== "shares"
    )
        fail("unsupported ledger units");
    const metadata = object(ledger.method_metadata, "method_metadata");
    const record = object(metadata.catalog_record, "catalog_record");
    const packet = object(metadata.packet_parameters, "packet_parameters");
    if (
        record.portfolio_id !== definition.portfolioId ||
        record.task_id !== definition.taskId ||
        record.run_id !== definition.runId ||
        record.scenario !== "normal_next_session" ||
        record.kind !== "strategy_run" ||
        record.is_sample !== false
    )
        fail("run/case/scenario identity mismatch");
    if (
        record.research_verdict !== definition.verdict ||
        record.execution_status !== "complete"
    )
        fail("recorded verdict/execution status changed");
    if (
        metadata.final_strategy_approved !== false ||
        packet.final_strategy_approved !== false
    )
        fail("these runs are not final approved strategies");
    text(metadata.mission_markdown, "mission_markdown");
    text(metadata.execution_report_markdown, "execution_report_markdown");
    text(record.evidence_status, "recorded evidence_status");
    if (
        !verifiedNativeHashes.has(
            hash(record.packet_sha256, "record.packet_sha256"),
        )
    )
        fail("packet hash must match a verified native source of this ledger");
    const parameters: ResearchMethod["parameters"] = {};
    for (const [key, value] of Object.entries(packet)) {
        if (typeof value === "number")
            parameters[key] = finite(value, `packet.${key}`);
        else if (typeof value === "string" || typeof value === "boolean")
            parameters[key] = value;
    }
    parameters.final_strategy_approved = false;
    parameters.candidate_id = text(record.candidate_id, "candidate_id");
    parameters.run_id = definition.runId;
    parameters.scenario = String(record.scenario);
    parameters.execution_status = String(record.execution_status);
    parameters.research_verdict = definition.verdict;
    parameters.evidence_status = String(record.evidence_status);
    parameters.adapter_version = ADAPTER_VERSION;
    const limitations = [
        ...strings(ledger.limitations, "ledger.limitations"),
        ...strings(record.limitations, "record.limitations"),
        "兩個案例使用已暴露的開發期間，不是獨立驗證；final_strategy_approved=false。",
        "僅轉換已對帳帳本，沒有重跑策略、成交或原生帳本，也沒有重評批准門檻。",
        "逐日持股與權重僅證明該紀錄日；周末、假日或缺失日不外推。",
        "20:00 帳戶狀態使用來源所記錄的原始收盤估值；權益應收及未交付股權獨立列為其他資產，不算現金或可交易持股。",
        "案例目錄以外股票的持有與估值仍保留，機會分類未知；沒有建立虛構價格。",
        "方法的完整封存參數、模型估值標記與來源時間保留於具雜湊的帳本來源；此處列出標量參數與已核對规则。",
    ];
    const method: ResearchMethod = {
        taskId: definition.taskId,
        status: definition.status,
        ruleVersion: `${text(packet.schema, "packet.schema")}; code=${text(record.method_code_commit, "method_code_commit")}; packet=${record.packet_sha256}`,
        rules: [...definition.rules],
        parameters,
        conclusion: `${definition.conclusion}${typeof record.failure_reason === "string" ? ` ${record.failure_reason}` : ""}`,
        missionPath: text(record.method_source, "method_source"),
        reportPath: text(record.report, "report"),
        limitations: [...limitations],
    };
    const sourceId = `ledger:${definition.portfolioId}`;
    const eventRows = list(ledger.events, "events");
    const eventIds = new Set<string>();
    const eventTimestamps: number[] = [];
    let previousEventTimestamp = -Infinity;
    const events: SavedResearchRun["events"] = eventRows.map((entry, index) => {
        const row = object(entry, "event");
        if (count(row.source_event_index, "source_event_index") !== index)
            fail("event source order/index mismatch");
        const id = text(row.presentation_event_id, "presentation_event_id");
        if (eventIds.has(id)) fail("duplicate event identity");
        eventIds.add(id);
        const original = object(row.source_event, "source_event");
        finiteJson(original);
        const eventDate = text(original.date, "event date");
        day(eventDate, "event date");
        const eventTimestamp = Date.parse(eventDate);
        if (eventTimestamp < previousEventTimestamp)
            fail(
                "event timestamps must be chronological in source index order",
            );
        previousEventTimestamp = eventTimestamp;
        eventTimestamps.push(eventTimestamp);
        return {
            id,
            date: eventDate,
            action: text(original.action, "event action"),
            code:
                original.code === undefined || original.code === null
                    ? null
                    : text(original.code, "event code"),
            quantity: nullableNumber(original.qty, "event quantity"),
            price: nullableNumber(original.price, "event price"),
            cashFlow: nullableNumber(original.total, "event cash flow"),
            original: structuredClone(original),
        };
    });
    const navRows = list(ledger.recorded_nav, "recorded_nav");
    const nav: SavedResearchRun["nav"] = [];
    const navByTimestamp = new Map<string, number>();
    let previousDay = "";
    for (const entry of navRows) {
        const point = object(entry, "NAV point");
        const date = day(point.date, "NAV date");
        if (date <= previousDay)
            fail("NAV dates must be unique and increasing");
        previousDay = date;
        const equity = finite(point.equity, "NAV equity", 0);
        nav.push({ date, equity });
        navByTimestamp.set(String(point.date), equity);
    }
    if (!nav.length) fail("empty recorded NAV");
    const daily = list(ledger.daily_states, "daily_states");
    const validation = object(ledger.validation, "validation");
    if (
        validation.daily_states !== daily.length ||
        validation.daily_nav_reconciled !== daily.length ||
        validation.event_count !== events.length ||
        validation.original_event_fields_retained !== true ||
        daily.length !== nav.length
    )
        fail("reconciled row/event counts mismatch");
    const declaredTolerance = finite(
        validation.absolute_tolerance_twd,
        "absolute_tolerance_twd",
        0,
    );
    if (
        declaredTolerance > MONEY_TOLERANCE ||
        finite(
            validation.max_abs_nav_difference_twd,
            "max_abs_nav_difference_twd",
            0,
        ) > MONEY_TOLERANCE
    )
        fail("source NAV reconciliation exceeds supported tolerance");
    const portfolio: OpportunityPortfolio = {
        id: definition.portfolioId,
        name: text(record.display_name, "display_name"),
        kind: "strategy",
        description: definition.conclusion,
        sourceIds,
        coverage: [],
        holdings: [],
        allocations: [],
        method,
        limitations,
    };
    previousDay = "";
    let previousEvents = 0;
    let expectedEvents = 0;
    let excludedAllocations = 0;
    const modeledMarks: { date: string; security: string }[] = [];
    for (const entry of daily) {
        const state = object(entry, "daily state");
        const date = day(state.date, "daily state date");
        if (state.date !== `${date}T20:00:00+08:00`)
            fail("daily state must be at 20:00:00+08:00");
        if (
            date <= previousDay ||
            state.portfolio_id !== definition.portfolioId
        )
            fail("daily state chronology/portfolio mismatch");
        previousDay = date;
        const eventCount = count(state.event_count, "daily event_count");
        if (eventCount < previousEvents || eventCount > events.length)
            fail("daily event prefix invalid");
        const checkpoint = Date.parse(String(state.date));
        // Both sequences are chronological. Include every event at the
        // checkpoint, preserving source index order for equal timestamps.
        while (
            expectedEvents < eventTimestamps.length &&
            eventTimestamps[expectedEvents] <= checkpoint
        )
            expectedEvents++;
        if (eventCount !== expectedEvents)
            fail(
                "daily event prefix must include exactly the events at or before the checkpoint",
            );
        previousEvents = eventCount;
        const basis = object(state.raw_mark_basis, "raw_mark_basis");
        if (
            basis.checkpoint_kind !== "daily_evening" ||
            basis.decision_at !== state.date
        )
            fail("daily state must use the recorded evening checkpoint");
        const closeDay = day(basis.close_at, "close_at");
        const availableDay = day(basis.available_at, "available_at");
        if (
            closeDay !== date ||
            availableDay !== date ||
            Date.parse(String(basis.close_at)) >
                Date.parse(String(basis.available_at)) ||
            Date.parse(String(basis.available_at)) >
                Date.parse(String(state.date))
        )
            fail("invalid raw mark availability chronology");
        const navValue = finite(state.nav_twd, "daily NAV", Number.MIN_VALUE);
        const recorded = navByTimestamp.get(String(state.date));
        if (recorded === undefined)
            fail("daily state has no exact recorded NAV timestamp");
        close(navValue, recorded, "daily recorded NAV");
        const reconciliation = object(
            state.valuation_reconciliation,
            "valuation_reconciliation",
        );
        close(
            finite(reconciliation.recorded_nav_twd, "recorded_nav_twd"),
            recorded,
            "source recorded NAV",
        );
        close(
            finite(reconciliation.replayed_nav_twd, "replayed_nav_twd"),
            navValue,
            "source replayed NAV",
        );
        close(
            finite(reconciliation.difference_twd, "difference_twd"),
            0,
            "source NAV difference",
        );
        const cash = finite(state.cash_twd, "cash_twd", 0);
        const otherAssets =
            finite(
                state.dividend_receivable_twd,
                "dividend_receivable_twd",
                0,
            ) +
            finite(
                state.capital_return_receivable_twd,
                "capital_return_receivable_twd",
                0,
            ) +
            finite(state.share_claims_value_twd, "share_claims_value_twd", 0);
        const positions: { securityId: string; weight: number }[] = [];
        const seen = new Set<string>();
        let stockValue = 0;
        portfolio.coverage.push({
            from: date,
            untilExclusive: nextDay(date),
            completeness: "full",
            kind: "snapshot",
            sourceId,
        });
        for (const item of list(
            state.tradable_positions,
            "tradable_positions",
        )) {
            const position = object(item, "tradable position");
            const security = securityId(position.security_id);
            if (seen.has(security)) fail("duplicate daily position");
            seen.add(security);
            const quantity = count(position.quantity, "position quantity");
            const value = finite(
                position.market_value_twd,
                "market_value_twd",
                0,
            );
            const rawMark = finite(position.raw_mark_twd, "raw_mark_twd", 0);
            if (quantity > 0 && rawMark <= 0)
                fail("positive quantity requires a positive raw mark");
            close(value, quantity * rawMark, "position value/raw mark");
            if (position.weight_missing_reason !== null)
                fail("position weight is not known");
            const weight = finite(
                position.weight_fraction,
                "position weight",
                0,
            );
            close(weight, value / navValue, "position weight/NAV", 1e-9);
            const markQuality = object(position.mark_quality, "mark_quality");
            const observedMark =
                markQuality.status === "observed_source_mark" &&
                markQuality.modeled_mark === false;
            const modeledMark =
                markQuality.status === "named_modeled_mark" &&
                markQuality.modeled_mark === true;
            if (
                (!observedMark && !modeledMark) ||
                markQuality.is_execution_price !== false
            )
                fail("unsupported mark_quality declarations");
            const markSource = text(
                markQuality.source_id,
                "mark_quality.source_id",
            );
            if (observedMark && markSource.trim().startsWith("modeled:"))
                fail("observed mark cannot declare a modeled source identity");
            if (modeledMark) {
                if (!/^modeled:\S/.test(markSource))
                    fail(
                        "modeled mark_quality.source_id must retain a modeled: identity",
                    );
                modeledMarks.push({ date, security });
            }
            stockValue += value;
            positions.push({ securityId: security, weight });
            if (quantity > 0)
                portfolio.holdings.push({
                    securityId: security,
                    from: date,
                    untilExclusive: nextDay(date),
                    quantity,
                    sourceId,
                });
        }
        close(
            cash + stockValue + otherAssets,
            navValue,
            "cash/stocks/receivables/claims NAV",
        );
        if (calendar.has(date))
            portfolio.allocations.push({
                date,
                completeness: "full",
                nav: navValue,
                cashWeight: cash / navValue,
                otherAssetsWeight: otherAssets / navValue,
                positions,
                sourceId,
            });
        else excludedAllocations++;
    }
    if (previousEvents !== events.length)
        fail("final daily state must account for all events");
    if (excludedAllocations)
        limitations.push(
            `${excludedAllocations} 個帳本日期不在案例價格日曆；資金快照未加入比較目錄，完整淨值與原始事件仍全部保留。`,
        );
    const modeledMarkLimitation = modeledMarks.length
        ? `來源包含 ${modeledMarks.length} 筆具名模型估值：${modeledMarks.map(({ date, security }) => `${date} ${security}`).join("、")}。這些數字沿用原始帳本的模型估值，不是當日觀察到的收盤價，也不是成交價。`
        : null;
    if (modeledMarkLimitation) {
        limitations.push(modeledMarkLimitation);
        method.limitations.push(modeledMarkLimitation);
    }
    const measurement = object(
        ledger.recorded_measurement,
        "recorded_measurement",
    );
    const metrics = object(record.recorded_metrics, "record.recorded_metrics");
    for (const key of [
        "endpoint_equity_twd",
        "endpoint_net_return_fraction",
        "costs_total_twd",
    ])
        close(
            finite(measurement[key], key),
            finite(metrics[key], `catalog ${key}`),
            `catalog/${key}`,
        );
    const run: SavedResearchRun = {
        id: definition.portfolioId,
        name: portfolio.name,
        from: nav[0].date,
        through: nav.at(-1)!.date,
        currency: "TWD",
        initialCapital: finite(
            measurement.initial_capital_twd,
            "initial capital",
            Number.MIN_VALUE,
        ),
        finalEquity: finite(measurement.endpoint_equity_twd, "final equity", 0),
        netReturn: finite(
            measurement.endpoint_net_return_fraction,
            "net return",
        ),
        costs: finite(measurement.costs_total_twd, "costs", 0),
        method,
        valuationBasis: modeledMarks.length
            ? "每天台北時間晚上 8 點，沿用來源記錄的原始股價與具名模型估值記錄帳戶價值；部分日期及股票使用原始帳本明確標示的模型估值，不代表當日觀察價。不是用還原股價或成交價計算的報酬。"
            : "Recorded daily_evening 20:00 Asia/Taipei account equity using available raw marks; not adjusted-price or execution-price returns.",
        limitations: [...limitations],
        sourceIds,
        nav,
        events,
    };
    close(
        run.finalEquity - run.initialCapital,
        finite(measurement.endpoint_net_pnl_twd, "net PnL"),
        "endpoint net PnL",
    );
    return { portfolio, run, modeledMarkLimitation };
}

/** Declared source paths are preserved as evidence only, never opened or executed. */
export function joinResearchEvidence(
    catalogValue: unknown,
    inputs: LedgerInput[],
    receiptValue: unknown,
    provenance: EvidenceSources,
): { opportunities: OpportunityBundle; research: SavedResearchBundle } {
    const catalog = validateBundle(catalogValue);
    if (catalog.kind === "synthetic")
        fail("real research evidence requires a historical catalog");
    const receipt = object(receiptValue, "export receipt");
    if (
        receipt.schema !== "native-ledger-presentation-export-receipt.v1" ||
        receipt.status !== "complete" ||
        receipt.strategy_runner_executed !== false ||
        receipt.strategy_verdict_changed !== false ||
        receipt.sources_unchanged !== true
    )
        fail("unsupported export receipt status");
    const outputs = object(receipt.outputs, "receipt.outputs");
    const receiptSources = object(
        receipt.source_hashes,
        "receipt.source_hashes",
    );
    const receiptValidation = object(receipt.validation, "receipt.validation");
    for (const value of Object.values(receiptSources))
        hash(value, "receipt source hash");
    const sources: SourceRef[] = [
        {
            id: "evidence-export-receipt",
            label: "Native ledger export receipt; accounting validation does not approve a strategy",
            path: text(provenance.receiptPath, "receiptPath"),
            hash: hash(provenance.receiptHash, "receiptHash"),
        },
        {
            id: "evidence-input-catalog",
            label: "Fixed retrospective opportunity catalog used for the join",
            path: text(provenance.catalogPath, "catalogPath"),
            hash: hash(provenance.catalogHash, "catalogHash"),
        },
    ];
    if (
        inputs.length !== DEFINITIONS.length ||
        new Set(inputs.map((input) => input.filename)).size !== inputs.length
    )
        fail("exactly the two reviewed ledger files are required");
    const portfolios: OpportunityPortfolio[] = [];
    const runs: SavedResearchRun[] = [];
    const modeledMarkLimitations: string[] = [];
    for (const definition of DEFINITIONS) {
        const input = inputs.find(
            (entry) => entry.filename === definition.filename,
        );
        if (!input) fail(`missing reviewed ledger: ${definition.filename}`);
        if (
            hash(input.sha256, "ledger file hash") !==
            hash(outputs[definition.filename], "receipt output hash")
        )
            fail(`ledger SHA-256 mismatch: ${definition.filename}`);
        const ledger = object(input.value, "ledger");
        const runValidation = object(ledger.validation, "ledger.validation");
        const declaredValidation = object(
            receiptValidation[definition.filename],
            "receipt ledger validation",
        );
        for (const key of [
            "daily_states",
            "daily_nav_reconciled",
            "event_count",
            "original_event_fields_retained",
            "max_abs_nav_difference_twd",
            "absolute_tolerance_twd",
        ])
            if (runValidation[key] !== declaredValidation[key])
                fail("receipt/ledger validation mismatch");
        const sourceId = `ledger:${definition.portfolioId}`;
        sources.push({
            id: sourceId,
            label: `Verified ledger bytes: ${definition.filename}`,
            path: input.path,
            hash: input.sha256,
        });
        const sourceIds = [sourceId, "evidence-export-receipt"];
        const verifiedNativeHashes = new Set<string>();
        for (const [path, declaredHash] of Object.entries(
            object(ledger.source_hashes, "ledger.source_hashes"),
        )) {
            const nativeHash = hash(declaredHash, "ledger native source hash");
            if (
                nativeHash !==
                hash(receiptSources[path], "receipt native source hash")
            )
                fail("ledger/receipt source identity mismatch");
            verifiedNativeHashes.add(nativeHash);
            const id = `native-source:${sha256(path).slice(0, 20)}`;
            const existing = sources.find((source) => source.id === id);
            if (existing && existing.hash !== nativeHash)
                fail("conflicting native source hash");
            if (!existing)
                sources.push({
                    id,
                    label: `Declared native source: ${path.replace(/\\/g, "/").split("/").at(-1)}`,
                    path,
                    hash: nativeHash,
                });
            sourceIds.push(id);
        }
        const result = adaptLedger(
            input,
            definition,
            new Set(catalog.dates),
            sourceIds,
            verifiedNativeHashes,
        );
        portfolios.push(result.portfolio);
        runs.push(result.run);
        if (result.modeledMarkLimitation)
            modeledMarkLimitations.push(
                `${result.run.id}：${result.modeledMarkLimitation}`,
            );
    }
    const existingIds = new Set(catalog.sources.map((source) => source.id));
    if (
        sources.some((source) => existingIds.has(source.id)) ||
        portfolios.some((portfolio) =>
            catalog.portfolios.some((existing) => existing.id === portfolio.id),
        )
    )
        fail("catalog already contains these evidence identities");
    const opportunities = validateBundle(
        withEtfReferences({
            ...structuredClone(catalog),
            id: `${catalog.id}+${ADAPTER_VERSION}`,
            sources: [...catalog.sources, ...sources],
            portfolios: [...catalog.portfolios, ...portfolios],
            limitations: [...catalog.limitations, ...modeledMarkLimitations],
        }),
    );
    const research = validateResearchBundle({
        schema: "saved-research-runs.v1",
        asOf: runs
            .map((run) => run.through)
            .sort()
            .at(-1),
        sources,
        runs,
    });
    return { opportunities, research };
}

function parseJson(bytes: Buffer): unknown {
    return JSON.parse(bytes.toString("utf8").replace(/^\uFEFF/, ""));
}
export async function exportResearchEvidence(
    catalogPath: string,
    ledgerDirectory: string,
    outputDirectory: string,
    includeJson = false,
) {
    const catalogFile = resolve(catalogPath);
    const directory = resolve(ledgerDirectory);
    const output = resolve(outputDirectory);
    const catalogBytes = await readFile(catalogFile);
    const catalogJson = catalogFile.toLowerCase().endsWith(".gz")
        ? gunzipSync(catalogBytes, { maxOutputLength: 64 * 1024 * 1024 })
        : catalogBytes;
    const receiptPath = join(directory, "export-receipt.json");
    const receiptBytes = await readFile(receiptPath);
    const receipt = parseJson(receiptBytes);
    const inputs: LedgerInput[] = [];
    for (const definition of DEFINITIONS) {
        const path = join(directory, definition.filename);
        const bytes = await readFile(path);
        inputs.push({
            filename: definition.filename,
            path,
            sha256: sha256(bytes),
            value: parseJson(bytes),
        });
    }
    const result = joinResearchEvidence(
        parseJson(catalogJson),
        inputs,
        receipt,
        {
            catalogPath: catalogFile,
            catalogHash: sha256(catalogBytes),
            receiptPath,
            receiptHash: sha256(receiptBytes),
        },
    );
    // Validation precedes creation. Non-recursive mkdir atomically refuses an
    // existing directory, including source directories or previous exports.
    await mkdir(output);
    const outputHashes: Record<string, string> = {};
    for (const [name, bundle] of [
        ["opportunity-explorer", result.opportunities],
        ["saved-research-runs", result.research],
    ] as const) {
        const json = Buffer.from(
            `${JSON.stringify(bundle, null, 2)}\n`,
            "utf8",
        );
        const compressed = gzipSync(json);
        await writeFile(join(output, `${name}.json.gz`), compressed, {
            flag: "wx",
        });
        outputHashes[`${name}.json.gz`] = sha256(compressed);
        if (includeJson) {
            await writeFile(join(output, `${name}.json`), json, { flag: "wx" });
            outputHashes[`${name}.json`] = sha256(json);
        }
    }
    const exportReceipt = {
        schema: "research-evidence-export-receipt.v1",
        adapterVersion: ADAPTER_VERSION,
        sourceReceiptHash: sha256(receiptBytes),
        catalogHash: sha256(catalogBytes),
        ledgerHashes: Object.fromEntries(
            inputs.map((input) => [input.filename, input.sha256]),
        ),
        outputs: outputHashes,
        runs: result.research.runs.map((run) => ({
            id: run.id,
            status: run.method.status,
            finalStrategyApproved: false,
            nav: run.nav.length,
            events: run.events.length,
        })),
    };
    await writeFile(
        join(output, "export-receipt.json"),
        `${JSON.stringify(exportReceipt, null, 2)}\n`,
        { encoding: "utf8", flag: "wx" },
    );
    return exportReceipt;
}

async function main() {
    const args = process.argv.slice(2);
    const options = new Map<string, string>();
    let includeJson = false;
    for (let i = 0; i < args.length; i++) {
        const key = args[i];
        if (key === "--json") {
            if (includeJson) throw new Error("Repeated --json");
            includeJson = true;
            continue;
        }
        const value = args[++i];
        if (
            !["--catalog", "--ledger-dir", "--out-dir"].includes(key) ||
            !value ||
            value.startsWith("--") ||
            options.has(key)
        )
            throw new Error(`Invalid argument: ${key}`);
        options.set(key, value);
    }
    if (options.size !== 3)
        throw new Error(
            "Usage: node --experimental-strip-types scripts/export-research-evidence.mts --catalog bundle.json[.gz] --ledger-dir reviewed-ledgers --out-dir new-directory [--json]",
        );
    const receipt = await exportResearchEvidence(
        options.get("--catalog")!,
        options.get("--ledger-dir")!,
        options.get("--out-dir")!,
        includeJson,
    );
    process.stdout.write(`${JSON.stringify(receipt)}\n`);
}
if (
    process.argv[1] &&
    resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
    main().catch((error: unknown) => {
        process.stderr.write(
            `${error instanceof Error ? error.message : String(error)}\n`,
        );
        process.exitCode = 1;
    });
}
