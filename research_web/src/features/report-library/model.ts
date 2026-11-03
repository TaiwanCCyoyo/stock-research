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

export type ReportIndexIssue =
    "version_mismatch" | "invalid_index" | "http" | "network";

export class ReportIndexError extends Error {
    readonly code: ReportIndexIssue;
    constructor(code: ReportIndexIssue, message: string) {
        super(message);
        this.name = "ReportIndexError";
        this.code = code;
    }
}

export async function readReportIndex(
    signal: AbortSignal,
    expectedVersion?: string,
    fetcher: typeof fetch = fetch,
): Promise<ReportIndex> {
    const response = await fetcher("/reports/index.json", {
        signal,
        cache: "no-store",
    });
    if (!response.ok)
        throw new ReportIndexError(
            "http",
            `報告清單讀取失敗（HTTP ${response.status}）`,
        );
    let value: unknown;
    try {
        value = await response.json();
    } catch {
        throw new ReportIndexError(
            "invalid_index",
            "報告清單回傳的內容不是有效 JSON。",
        );
    }
    return validateReportIndex(value, expectedVersion);
}

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
        throw new ReportIndexError(
            "invalid_index",
            "報告清單格式不符，無法讀取。",
        );
    if (
        expectedVersion !== undefined &&
        (value as { version?: unknown }).version !== expectedVersion
    )
        throw new ReportIndexError(
            "version_mismatch",
            "報告索引版本與目前頁面不一致，請重新載入頁面。",
        );
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

/** Standalone fallback travels in the frame URL hash; host tokens are injected
 * separately. */
export function reportFrameSrc(id: string, appearance: string): string {
    const params = new URLSearchParams({ palette: "forest", appearance });
    return `/reports/${encodeURIComponent(id)}/index.html#${params}`;
}

/** Accept only routes requested by this viewer's own frame and loaded index. */
export function reportNavigationHash(
    source: unknown,
    frameWindow: unknown,
    data: unknown,
    reportIds: readonly string[] | null,
): "#data" | `#report/${string}` | null {
    if (
        !frameWindow ||
        source !== frameWindow ||
        !data ||
        typeof data !== "object"
    )
        return null;
    const message = data as { type?: unknown; href?: unknown };
    if (message.type !== "rk:navigate" || typeof message.href !== "string")
        return null;
    if (message.href === "#data") return "#data";
    if (!message.href.startsWith("#report/")) return null;

    const encodedId = message.href.slice("#report/".length);
    let reportId: string;
    try {
        reportId = decodeURIComponent(encodedId);
    } catch {
        return null;
    }
    if (
        !/^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(reportId) ||
        encodeURIComponent(reportId) !== encodedId ||
        !reportIds?.includes(reportId)
    )
        return null;
    return `#report/${encodedId}`;
}

/** Reveal only the fixed evidence heading, from the currently mounted frame. */
export function reportRevealRequest(
    source: unknown,
    frameWindow: unknown,
    data: unknown,
): { target: "detail-title"; height: number | null } | null {
    if (
        !frameWindow ||
        source !== frameWindow ||
        !data ||
        typeof data !== "object"
    )
        return null;
    const message = data as {
        type?: unknown;
        target?: unknown;
        height?: unknown;
    };
    if (message.type !== "rk:reveal" || message.target !== "detail-title")
        return null;
    return {
        target: "detail-title",
        height: reportFrameHeight(message.height),
    };
}

export function reportFrameHeight(value: unknown): number | null {
    return typeof value === "number" && Number.isFinite(value) && value > 0
        ? Math.min(Math.ceil(value), 200_000)
        : null;
}

/** Run after React commits the frame height; stale documents cannot move the page. */
export function revealReportEvidence(
    frame: HTMLIFrameElement,
    source: Window,
    expectedDocument: Document,
): boolean {
    try {
        if (
            frame.contentWindow !== source ||
            frame.contentDocument !== expectedDocument
        )
            return false;
        const heading = expectedDocument.getElementById("detail-title");
        if (!heading) return false;
        const host = frame.ownerDocument.defaultView;
        if (!host) return false;
        const header = frame.ownerDocument.querySelector(".shell-header");
        const clearance =
            Math.max(0, header?.getBoundingClientRect().bottom ?? 0) + 16;
        heading.focus({ preventScroll: true });
        host.scrollTo({
            top: Math.max(
                0,
                host.scrollY +
                    frame.getBoundingClientRect().top +
                    heading.getBoundingClientRect().top -
                    clearance,
            ),
            behavior: "instant",
        });
        return true;
    } catch {
        return false;
    }
}
