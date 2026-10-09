/** Payload types mirroring the read-only research API (research_api/main.py). */

export interface TaskIndexRow {
    task: string;
    mtime: number;
    title: string;
}

export interface TaskListResponse {
    tasks: TaskIndexRow[];
}

export interface RunInfo {
    start?: string;
    end?: string;
    codes?: string[];
    universe?: string | null;
    initial_cash?: number;
    capital_mode?: string;
    per_stock_initial_cash?: number;
}

export interface Summary {
    run?: RunInfo;
    metrics?: Record<string, number | null>;
    strategy?: { name?: string; params?: Record<string, unknown> };
    trades?: TradeRecord[];
    data?: { path?: string };
    warnings?: string[];
    portfolio?: {
        cash?: number;
        positions?: unknown;
        equity_curve?: EquityPoint[];
    };
}

export interface EquityPoint {
    date: string;
    equity: number;
}

/** Formatted health values from dashboard_core.strategy_health_rows. */
export interface HealthRows {
    expectancy_fmt: string;
    payoff_ratio_fmt: string;
    profit_factor_fmt: string;
    calmar_fmt: string;
    avg_win_fmt: string;
    avg_loss_fmt: string;
    largest_win_fmt: string;
    largest_loss_fmt: string;
    closed_trade_count: number;
    verdict: string;
}

export interface Judgments {
    comparative: string;
    pools: Record<string, string>;
}

export interface TradeRecord {
    date: string;
    code: string;
    action: string;
    price: number;
    qty: number;
    total: number;
}

export interface ComparisonRow {
    mode?: string;
    [key: string]: unknown;
}

export type CapitalMode = "shared" | "per_stock" | "unconstrained";

export interface TaskBundle {
    task: string;
    title: string;
    root: string;
    summary: Summary;
    stock_names: Record<string, string>;
    mode_summaries: Record<string, Summary>;
    rankings: { stocks: RankingRow[] };
    events: { events: SignalEvent[] };
    comparison: { modes?: ComparisonRow[]; [key: string]: unknown } | null;
    diagnosis: string;
    health: HealthRows;
    mode_health: Record<string, HealthRows>;
    judgments: Judgments | null;
}

export interface RankingRow {
    code?: string;
    total_pnl?: number | null;
    max_drawdown_rate?: number | null;
    trade_count?: number | null;
    win_rate?: number | null;
    final_qty?: number | null;
    industry_category?: string | null;
    [key: string]: unknown;
}

export interface SignalEvent {
    date?: string;
    code?: string;
    event?: string;
    reason?: string;
    [key: string]: unknown;
}

/** One OHLCV row; extra engine columns (SignalClose, RawClose, ...) ride along. */
export interface PriceRow {
    Date: string;
    Open: number;
    High: number;
    Low: number;
    Close: number;
    Volume?: number;
    [key: string]: string | number | boolean | null | undefined;
}

export interface CorporateActionMarker {
    event_type: string;
    date: string;
}

export interface PricesResponse {
    task: string;
    codes: string[];
    prices: Record<string, PriceRow[]>;
    corporate_actions: Record<string, CorporateActionMarker[]>;
}

export interface TradeListRow {
    trade_id: string;
    date: string;
    code: string;
    action: string;
    price: number;
    qty: number;
    total: number;
    signal_reason: string | null;
    realized_pnl: number | null;
    cumulative_realized_pnl: number;
    is_add_on: boolean;
}

export interface TradesResponse {
    task: string;
    count: number;
    trades: TradeListRow[];
}

/** Mirrors shioaji_stock_prices's check_data_integrity.py report schema (v3).
 *
 * v3 changed the subject from the Shioaji day CSVs to price_daily.parquet, the
 * artifact research actually reads. `symbols` now lists only symbols with a
 * finding, so the scanned total comes from `coverage.symbol_count` rather than
 * the size of that map. */
export interface DataQualityFinding {
    count: number;
    examples: (
        string | { date: string; return?: number; expected_factor?: number }
    )[];
}

export type DataQualityCheckName =
    | "price_gap_without_ca_event"
    | "ca_event_without_price_gap"
    | "unexplained_fallback";

export type DataQualitySymbolEntry = Record<
    DataQualityCheckName,
    DataQualityFinding
>;

export interface DataQualityCoverage {
    first_date?: string;
    last_date?: string;
    trading_day_count?: number;
    saturday_session_count?: number;
    symbol_count?: number;
    row_count?: number;
    rows_by_source?: Record<string, number>;
    fallback_row_count?: number;
    fallback_symbol_count?: number;
    fallback_only_symbol_count?: number;
    fallback_rows_outside_official_window?: number;
    latest_day_row_count?: number;
    /** Share of the newest bar served by the official feed. Below 1 means the
     * newest bar is provisional until the backfill catches up. */
    latest_day_official_share?: number | null;
}

export interface DataQualityReport {
    schema_version: number;
    generated_at: string;
    subject: string;
    coverage: DataQualityCoverage;
    checks: Record<
        DataQualityCheckName,
        {
            description?: string;
            threshold?: number;
            symbol_count: number;
            finding_count: number;
        }
    >;
    symbols: Record<string, DataQualitySymbolEntry>;
}

/** GET /data-quality response; `report` is null when the submodule has not produced one yet. */
export interface DataQualityResponse {
    available: boolean;
    report: DataQualityReport | null;
}

export interface TradeDetail {
    task: string;
    trade_id: string;
    trade_index: number;
    trade: TradeRecord;
    signal_events: SignalEvent[];
    cash_context: Record<string, unknown>;
    price_context: Record<string, unknown>;
    strategy: { name?: string; params?: Record<string, unknown> };
    strategy_params: Record<string, unknown>;
    price_policy: Record<string, unknown>;
    data_path: string | null;
}
