/** GET /data-status (research-data-status.v1), see docs/en/data-status.md. */
export interface DataStatus {
    schema: "research-data-status.v1";
    generated_at: string | null;
    status: "ok" | "partial" | "updating";
    datasets: DatasetStatus[];
    warnings: string[];
}

export interface DatasetStatus {
    id: string;
    source: "producer" | "derived" | "catalog";
    name: string;
    data_period: { from: string | null; to: string | null } | null;
    last_updated: string | null;
    update_kind?: "version_created_at" | "manifest_modified_at" | null;
    symbols: number | null;
    rows: number | null;
    status: "ok" | "stale" | "missing" | "updating";
}

export function validateDataStatus(value: unknown): DataStatus {
    const data = value as Partial<DataStatus> | null;
    if (
        !data ||
        data.schema !== "research-data-status.v1" ||
        !Array.isArray(data.datasets)
    )
        throw new Error("資料總覽格式不符，無法讀取。");
    return {
        ...data,
        warnings: Array.isArray(data.warnings) ? data.warnings : [],
    } as DataStatus;
}

export const SOURCE_GROUPS: {
    source: DatasetStatus["source"];
    title: string;
    note: string;
}[] = [
    {
        source: "producer",
        title: "市場原始資料",
        note: "每天自動下載的價格、法人、營收與公司資料",
    },
    {
        source: "derived",
        title: "共用計算資料",
        note: "還原價格與技術指標，研究共用同一份",
    },
    {
        source: "catalog",
        title: "研究資料集",
        note: "研究當時保存的固定資料，不會跟著每天更新",
    },
];

export const STATUS_LABELS: Record<DatasetStatus["status"], string> = {
    ok: "有資料",
    stale: "需要更新",
    missing: "沒有資料",
    updating: "更新中",
};

/** Catalog entries are frozen: "stale" there means only partly saved
 *  (research_core.data_status), not out of date. */
export function statusLabel(item: DatasetStatus): string {
    if (item.source === "catalog" && item.status === "stale") return "部分保存";
    if (
        item.id === "institutional" &&
        item.data_period?.from &&
        item.data_period.from >= "2019-01-01"
    )
        return "歷史缺漏";
    return STATUS_LABELS[item.status] ?? item.status;
}

/** Counts: null stays unknown, zero is a measured zero. */
export function countLabel(value: number | null, unit: string): string {
    if (value === null || value === undefined) return "未知";
    if (value >= 100_000_000)
        return `${(value / 100_000_000).toFixed(1)} 億${unit}`;
    if (value >= 10_000) return `${Math.round(value / 10_000)} 萬${unit}`;
    return `${value.toLocaleString("zh-TW")} ${unit}`;
}

export function periodLabel(period: DatasetStatus["data_period"]): string {
    const short = (value: string | null) =>
        value ? value.slice(0, 7).replace("-", "/") : "?";
    if (!period || (!period.from && !period.to)) return "期間未知";
    return `${short(period.from)} – ${short(period.to)}`;
}

/** Local calendar date of an ISO timestamp, or the date itself. */
export function updatedLabel(value: string | null): string {
    if (!value) return "更新時間未知";
    const time = Date.parse(value);
    if (Number.isNaN(time)) return "更新時間未知";
    const date = new Date(time);
    return `${date.getFullYear()}/${String(date.getMonth() + 1).padStart(2, "0")}/${String(date.getDate()).padStart(2, "0")} 更新`;
}

export function groupDatasets(datasets: readonly DatasetStatus[]) {
    return SOURCE_GROUPS.map((group) => ({
        ...group,
        datasets: datasets.filter((item) => item.source === group.source),
    })).filter((group) => group.datasets.length > 0);
}

export function datasetPeriodLabel(item: DatasetStatus): string {
    if (item.id === "derived:security-coverage-v1")
        return "最近檢查 " + (item.data_period?.to ?? "未確認");
    if (item.id === "symbol_meta")
        return "最近觀察 " + (item.data_period?.to?.slice(0, 10) ?? "未確認");
    return periodLabel(item.data_period);
}
export function datasetUpdatedLabel(item: DatasetStatus): string {
    if (item.source === "catalog") {
        if (!item.last_updated) return "固定版本";
        const label =
            item.update_kind === "version_created_at"
                ? "版本建立"
                : "說明檔最後變動";
        return "固定版本 · " + label + " " + item.last_updated.slice(0, 10);
    }
    return updatedLabel(item.last_updated);
}
export function datasetHref(item: DatasetStatus): string | null {
    if (item.source === "producer") {
        const query = new URLSearchParams({ kind: "", status: "all" });
        if (
            [
                "official_daily",
                "price_daily",
                "institutional",
                "monthly_revenue",
                "corporate_actions",
                "symbol_meta",
            ].includes(item.id)
        )
            query.set("dataset", item.id);
        return "#overview/stocks?" + query;
    }
    if (item.id === "derived:adjusted-daily-v1")
        return "#overview/stocks?dataset=adjusted_daily&kind=&status=all";
    return null;
}
