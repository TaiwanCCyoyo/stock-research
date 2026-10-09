import type {
    DataQualityResponse,
    PricesResponse,
    TaskBundle,
    TaskListResponse,
    TradeDetail,
    TradesResponse,
} from "./types";

/**
 * Base URL for the research API. In dev the Vite proxy maps /api -> :8503,
 * so the default works with `open_research_api.cmd` running locally.
 */
const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";

export class ApiError extends Error {
    status: number;

    constructor(status: number, detail: string) {
        super(detail);
        this.status = status;
    }
}

async function getJson<T>(path: string): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`);
    if (!response.ok) {
        let detail = `HTTP ${response.status}`;
        try {
            const body = await response.json();
            if (typeof body.detail === "string") detail = body.detail;
        } catch {
            // non-JSON error body; keep the status text
        }
        throw new ApiError(response.status, detail);
    }
    return (await response.json()) as T;
}

export function fetchTasks(): Promise<TaskListResponse> {
    return getJson("/tasks");
}

/** Data quality is a global, task-independent view over the local price archive. */
export function fetchDataQuality(): Promise<DataQualityResponse> {
    return getJson("/data-quality");
}

export function fetchTaskBundle(taskId: string): Promise<TaskBundle> {
    return getJson(`/tasks/${encodeURIComponent(taskId)}`);
}

export function fetchPrices(
    taskId: string,
    codes: string[],
): Promise<PricesResponse> {
    const query = encodeURIComponent(codes.join(","));
    return getJson(
        `/tasks/${encodeURIComponent(taskId)}/prices?codes=${query}`,
    );
}

export function fetchTrades(
    taskId: string,
    filters: {
        code?: string;
        action?: string;
        limit?: number;
        summaryFile?: string;
    } = {},
): Promise<TradesResponse> {
    const params = new URLSearchParams();
    if (filters.code) params.set("code", filters.code);
    if (filters.action) params.set("action", filters.action);
    params.set("limit", String(filters.limit ?? 500));
    if (filters.summaryFile) params.set("summary_file", filters.summaryFile);
    return getJson(
        `/tasks/${encodeURIComponent(taskId)}/trades?${params.toString()}`,
    );
}

export function fetchTradeDetail(
    taskId: string,
    tradeId: string,
    summaryFile?: string,
): Promise<TradeDetail> {
    const suffix = summaryFile
        ? `?summary_file=${encodeURIComponent(summaryFile)}`
        : "";
    return getJson(
        `/tasks/${encodeURIComponent(taskId)}/trades/${encodeURIComponent(tradeId)}${suffix}`,
    );
}

const CSRF_HEADERS = { "X-Requested-With": "research-web" };

/**
 * Tells the server the browser tab is still open. Sent on an interval from App;
 * the launcher's monitor (research_api/__main__.py) stops the server after a
 * grace period without one. Failures are swallowed — a dropped heartbeat should
 * not surface as a dashboard error, only eventually trigger auto-shutdown.
 */
export async function sendHeartbeat(): Promise<void> {
    try {
        await fetch(`${API_BASE}/heartbeat`, {
            method: "POST",
            headers: CSRF_HEADERS,
        });
    } catch {
        // network hiccup; the next interval tick will retry
    }
}

/** Requests a graceful server shutdown. Returns whether the request succeeded. */
export async function shutdownDashboard(): Promise<boolean> {
    try {
        const response = await fetch(`${API_BASE}/shutdown`, {
            method: "POST",
            headers: CSRF_HEADERS,
        });
        return response.ok;
    } catch {
        return false;
    }
}
