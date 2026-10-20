/** One entry of /reports/index.json, read from a report's <meta name="report:*"> tags. */
export type ReportEntry = {
    id: string;
    title: string;
    summary: string;
    date: string;
    status: string;
    period: string;
    kit: string;
    tags: string[];
};

export type ReportIndex = {
    schema: "research-reports.v1";
    /** Optional build identity added without changing the v1 index contract. */
    version?: string;
    reports: ReportEntry[];
};

const STATUS_LABELS: Record<string, string> = {
    exploratory: "探索中",
    descriptive: "描述性結果",
    superseded: "已被取代",
    demo: "示範",
    failed: "已淘汰",
    accepted: "已採用",
};

export function statusLabel(status: string): string {
    return STATUS_LABELS[status] ?? (status || "未標示");
}

export function validateReportIndex(
    value: unknown,
    expectedVersion?: string,
): ReportIndex {
    if (
        !value ||
        typeof value !== "object" ||
        (value as { schema?: unknown }).schema !== "research-reports.v1" ||
        !Array.isArray((value as { reports?: unknown }).reports)
    )
        throw new Error("報告清單格式不符，無法讀取。");
    if (
        expectedVersion !== undefined &&
        (value as { version?: unknown }).version !== expectedVersion
    )
        throw new Error("報告索引版本與目前頁面不一致，請重新載入頁面。");
    return value as ReportIndex;
}

/** All distinct tags, most used first, then alphabetically. */
export function reportTags(reports: ReportEntry[]): string[] {
    const counts = new Map<string, number>();
    for (const report of reports)
        for (const tag of report.tags)
            counts.set(tag, (counts.get(tag) ?? 0) + 1);
    return [...counts]
        .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
        .map(([tag]) => tag);
}

/** Case-insensitive search over title, summary, id and tags, plus an optional tag. */
export function filterReports(
    reports: ReportEntry[],
    query: string,
    tag: string | null,
): ReportEntry[] {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    return reports.filter((report) => {
        if (tag && !report.tags.includes(tag)) return false;
        const text = [report.title, report.summary, report.id, ...report.tags]
            .join(" ")
            .toLowerCase();
        return words.every((word) => text.includes(word));
    });
}

/** First-paint theme travels in the frame URL hash; later changes use postMessage. */
export function reportFrameSrc(
    id: string,
    palette: string,
    appearance: string,
): string {
    const params = new URLSearchParams({ palette, appearance });
    return `/reports/${encodeURIComponent(id)}/index.html#${params}`;
}
