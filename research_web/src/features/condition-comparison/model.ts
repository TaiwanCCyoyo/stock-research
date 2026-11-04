/** Presentation-only boundary. The research producer owns the persisted schema.
 * No outcome classification, population selection or statistics happen here. */
export type Horizon = 126 | 252;
export type CellId = "neither" | "prior-only" | "today-only" | "both";
export type GroupId = CellId | "all";
export type OutcomeLabel = "hit" | "loss" | "flat-win" | "unknown";
export type CaseFilter = "all" | "hit" | "not-hit" | "unknown";
export const CELLS: readonly CellId[] = [
    "neither",
    "prior-only",
    "today-only",
    "both",
];
export const GROUP_LABELS: Record<GroupId, string> = {
    all: "共同母體 A",
    neither: "無事前量縮 × 無當日放量",
    "prior-only": "有事前量縮 × 無當日放量",
    "today-only": "無事前量縮 × 有當日放量",
    both: "有事前量縮 × 有當日放量",
};
export interface SourceContext {
    studyId: string;
    resultId: string;
    settingsVersion: string;
    outcomeDefinition: string;
    inputVersion: string;
    priceBasis: string;
    population: string;
    source: string;
}
export interface Counts {
    hit?: number;
    known?: number;
    stocks?: number;
    unknown?: number;
    censored?: number;
}
export type Summary = (
    | { status: "evaluated"; counts: Counts }
    | { status: "not-evaluated"; counts?: Counts }
) & { reason?: string; saved?: Readonly<Record<string, number | null>> };
export interface TraceReference {
    event_id: string;
    security_id: string;
    t0: string;
    horizon: Horizon;
}
export interface SavedCase {
    eventId: string;
    securityId: string;
    date: string;
    group: CellId;
    /** Effective label from the existing event overlay, never a base-label fallback. */
    effectiveLabel: OutcomeLabel;
    eventMainEligible: boolean;
    censored: boolean;
    reasons: readonly string[];
    /** Opaque reader identifier; absence means no reader is available. */
    readerRef?: string;
}
export interface WindowView {
    all: Summary;
    cells: Partial<Record<CellId, Summary>>;
    /** Saved A\\B statistics for each B; never calculated from overlapping rates. */
    complements: Partial<Record<CellId, Summary>>;
    cases: readonly SavedCase[];
    caseCoverage: string;
    references?: Partial<Record<CellId, readonly TraceReference[]>>;
    unavailable?: readonly {
        id: string;
        GStatus: string;
        volStatus: string;
        summary: Summary;
        reasons: Readonly<
            Record<string, readonly { reason: string; event_n: number }[]>
        >;
        references: readonly TraceReference[];
    }[];
}
export interface ComparisonView {
    id: string;
    synthetic: boolean;
    source: SourceContext;
    windows: Partial<Record<Horizon, WindowView>>;
    producer?: {
        schemaVersion: string;
        scope: "synthetic" | "pilot" | "full";
        provenance: Readonly<Record<string, unknown>>;
        semantics: Readonly<Record<string, unknown>>;
    };
}
export type ReadState =
    | { status: "loading" }
    | { status: "error"; message: string }
    | { status: "ready"; value: ComparisonView };
export interface Selection {
    resultId: string;
    horizon: Horizon;
    group: GroupId;
    filter: CaseFilter;
    page: number;
    sort: "date-asc" | "date-desc";
    eventId?: string;
}
export interface NavigationContext {
    source: SourceContext;
    synthetic: boolean;
    selection: Selection;
    producer?: ComparisonView["producer"];
}
export interface CaseRequest extends NavigationContext {
    item: SavedCase;
    readerRef: string;
}
export interface QuestionRequest extends NavigationContext {
    question: string;
    intent: "discussion-only";
}
export const PAGE_SIZE = 5;
export function initialSelection(view: ComparisonView): Selection {
    return {
        resultId: view.id,
        horizon: 126,
        group: "all",
        filter: "all",
        page: 0,
        sort: "date-desc",
    };
}
export function currentSelection(
    view: ComparisonView,
    selection?: Selection,
): Selection {
    return selection?.resultId === view.id ? selection : initialSelection(view);
}
export function casePage(window: WindowView | undefined, selection: Selection) {
    const rows = (window?.cases ?? []).filter(
        (item) =>
            (selection.group === "all" || item.group === selection.group) &&
            (selection.filter === "all" ||
                (selection.filter === "not-hit"
                    ? item.effectiveLabel === "loss" ||
                      item.effectiveLabel === "flat-win"
                    : item.effectiveLabel === selection.filter)),
    );
    rows.sort(
        (a, b) =>
            (selection.sort === "date-asc" ? 1 : -1) *
                a.date.localeCompare(b.date) ||
            a.eventId.localeCompare(b.eventId),
    );
    const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
    const page = Math.max(0, Math.min(selection.page, pages - 1));
    return {
        rows: rows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
        page,
        pages,
        total: rows.length,
    };
}
/** Caller injects the producer's adapter. This is intentionally NOT a wire schema. */
export function adaptSavedComparison<T>(
    saved: T,
    adapter: (saved: T) => ComparisonView,
): ReadState {
    try {
        const value = adapter(saved);
        if (
            !value.id ||
            value.id !== value.source.resultId ||
            Object.values(value.source).some((field) => !field.trim())
        )
            throw new Error("缺少結果來源或設定版本，或結果識別不一致");
        for (const window of Object.values(value.windows)) {
            for (const summary of [
                window.all,
                ...Object.values(window.cells),
                ...Object.values(window.complements),
            ]) {
                if (summary?.status !== "evaluated") continue;
                for (const count of Object.values(summary.counts)) {
                    if (
                        count !== undefined &&
                        (!Number.isSafeInteger(count) || count < 0)
                    )
                        throw new Error("保存計數格式不正確");
                }
                if (
                    summary.counts.hit !== undefined &&
                    summary.counts.known !== undefined &&
                    summary.counts.hit > summary.counts.known
                )
                    throw new Error("命中數超過已知分母");
            }
            const ids = new Set<string>();
            for (const item of window.cases) {
                if (ids.has(item.eventId)) throw new Error("個案識別重複");
                ids.add(item.eventId);
                if (
                    !["hit", "loss", "flat-win", "unknown"].includes(
                        item.effectiveLabel,
                    )
                )
                    throw new Error("缺少既有有效結果標籤");
            }
        }
        return { status: "ready", value };
    } catch (error) {
        return {
            status: "error",
            message:
                error instanceof Error ? error.message : "無法讀取保存結果",
        };
    }
}
