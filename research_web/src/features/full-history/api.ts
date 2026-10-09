import { HISTORY_SCHEMA } from "./types.ts";

export const HISTORY_API = "/history-api/opportunity-history/v1";
export class HistoryLoadingError extends Error {
    readonly retryAfterMs: number;
    constructor(message: string, retryAfterMs = 1000) {
        super(message);
        this.name = "HistoryLoadingError";
        this.retryAfterMs = retryAfterMs;
    }
}

export interface HistoryStatus {
    schema: string;
    state: "loading" | "ready" | "failed";
    stage: string;
    completed: number;
    total: number;
}

export async function readHistory<T>(
    path: string,
    signal: AbortSignal,
): Promise<T> {
    const response = await fetch(`${HISTORY_API}${path}`, { signal });
    if (!response.ok) {
        if (response.status === 503) {
            const body: unknown = await response.json().catch(() => null);
            if (typeof body === "object" && body !== null && "detail" in body) {
                const detail = body.detail;
                if (
                    typeof detail === "object" &&
                    detail !== null &&
                    "state" in detail &&
                    detail.state === "loading"
                ) {
                    const seconds = Number(
                        response.headers.get("Retry-After") ?? "1",
                    );
                    const retryAfterMs =
                        Number.isFinite(seconds) && seconds > 0
                            ? Math.min(seconds * 1000, 30000)
                            : 1000;
                    throw new HistoryLoadingError(
                        "正在核對歷史資料",
                        retryAfterMs,
                    );
                }
            }
        }
        throw new Error(`歷史資料服務回應 ${response.status}`);
    }
    return (await response.json()) as T;
}

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
    return new Promise((resolve, reject) => {
        if (signal.aborted) {
            reject(new DOMException("Aborted", "AbortError"));
            return;
        }
        const abort = () => {
            clearTimeout(timer);
            reject(new DOMException("Aborted", "AbortError"));
        };
        const timer = setTimeout(() => {
            signal.removeEventListener("abort", abort);
            resolve();
        }, milliseconds);
        signal.addEventListener("abort", abort, { once: true });
    });
}

/** Retry only the explicit background-loading contract, never generic service errors. */
export async function readHistoryWhenReady<T>(
    path: string,
    signal: AbortSignal,
    onStatus?: (status: HistoryStatus) => void,
): Promise<T> {
    while (!signal.aborted) {
        try {
            return await readHistory<T>(path, signal);
        } catch (cause) {
            if (!(cause instanceof HistoryLoadingError)) throw cause;
            let status: HistoryStatus;
            do {
                await delay(cause.retryAfterMs, signal);
                status = await readHistory<HistoryStatus>("/status", signal);
                if (
                    status.schema !== HISTORY_SCHEMA ||
                    !["loading", "ready", "failed"].includes(status.state)
                )
                    throw new Error("歷史資料狀態不完整");
                onStatus?.(status);
                if (status.state === "failed")
                    throw new Error(
                        "歷史資料核對未通過，請檢查本機快照後重新讀取。",
                    );
            } while (status.state === "loading");
        }
    }
    throw new DOMException("Aborted", "AbortError");
}
