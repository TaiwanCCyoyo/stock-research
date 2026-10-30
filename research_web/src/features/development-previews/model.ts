export type PreviewStatus = "ready" | "stopped" | "starting" | "unavailable";

export interface PreviewItem {
    id: string;
    title: string;
    pr: number | null;
    branch: string;
    head: string;
    status: PreviewStatus;
    message: string;
    url: string | null;
}

export interface PreviewIndex {
    items: PreviewItem[];
    current: {
        id: string;
        title: string;
        pr: number | null;
        mainUrl: string;
    } | null;
}

/** Navigation is limited to the local launcher, even if an API responds badly. */
export function localPreviewUrl(value: unknown): string | null {
    if (typeof value !== "string") return null;
    try {
        const url = new URL(value);
        return url.protocol === "http:" &&
            url.hostname === "127.0.0.1" &&
            !url.username &&
            !url.password &&
            !!url.port
            ? url.href
            : null;
    } catch {
        return null;
    }
}

function record(value: unknown): value is Record<string, unknown> {
    return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function readPreviewIndex(value: unknown): PreviewIndex {
    if (!record(value) || !Array.isArray(value.items))
        throw new Error("預覽清單格式不完整。");
    const items = value.items.map((item: unknown): PreviewItem => {
        if (
            !record(item) ||
            typeof item.id !== "string" ||
            !/^[a-zA-Z0-9_-]+$/.test(item.id) ||
            typeof item.title !== "string" ||
            typeof item.branch !== "string" ||
            typeof item.head !== "string" ||
            typeof item.message !== "string" ||
            !["ready", "stopped", "starting", "unavailable"].includes(
                String(item.status),
            ) ||
            !(
                item.pr === null ||
                (Number.isSafeInteger(item.pr) && Number(item.pr) > 0)
            )
        ) {
            throw new Error("預覽清單格式不完整。");
        }
        const url = localPreviewUrl(item.url);
        const unsafe = item.status === "ready" && !url;
        return {
            id: item.id,
            title: item.title,
            branch: item.branch,
            head: item.head,
            pr: item.pr as number | null,
            status: unsafe ? "unavailable" : (item.status as PreviewStatus),
            message: unsafe
                ? "預覽網址無法確認，請重新整理清單。"
                : item.message,
            url,
        };
    });
    let current: PreviewIndex["current"] = null;
    if (record(value.current)) {
        const context = value.current;
        const mainUrl = localPreviewUrl(context.mainUrl);
        if (
            typeof context.id === "string" &&
            typeof context.title === "string" &&
            mainUrl &&
            (context.pr === null ||
                (Number.isSafeInteger(context.pr) && Number(context.pr) > 0))
        ) {
            current = {
                id: context.id,
                title: context.title,
                pr: context.pr as number | null,
                mainUrl,
            };
        }
    }
    return { items, current };
}

async function withUserMessage<T>(
    operation: Promise<T>,
    message: string,
): Promise<T> {
    try {
        return await operation;
    } catch (reason) {
        if (reason instanceof Error && reason.name === "AbortError")
            throw reason;
        throw new Error(message);
    }
}

export async function loadPreviews(
    url: string,
    signal: AbortSignal,
    fetcher = fetch,
): Promise<PreviewIndex> {
    const response = await withUserMessage(
        fetcher(url, { signal, cache: "no-store" }),
        "無法連上預覽服務，請稍後重試。",
    );
    if (!response.ok) throw new Error("暫時無法取得預覽清單，請稍後重試。");
    return readPreviewIndex(
        await withUserMessage(
            response.json(),
            "預覽清單無法讀取，請重新整理清單。",
        ),
    );
}

export async function startPreview(
    url: string,
    signal: AbortSignal,
    fetcher = fetch,
): Promise<void> {
    const response = await withUserMessage(
        fetcher(url, {
            method: "POST",
            signal,
            headers: { "X-Requested-With": "development-preview" },
        }),
        "無法連上預覽服務，尚未確認是否啟動。請重新整理清單後再試。",
    );
    const result: unknown = await withUserMessage(
        response.json(),
        "無法確認啟動結果，請重新整理清單。",
    );
    if (
        !response.ok ||
        !record(result) ||
        !["starting", "ready"].includes(String(result.status))
    ) {
        const message =
            record(result) && typeof result.message === "string"
                ? result.message
                : record(result) && typeof result.detail === "string"
                  ? result.detail
                  : "預覽未能啟動，請重試。";
        throw new Error(message);
    }
}

export const STATUS_LABELS: Record<PreviewStatus, string> = {
    ready: "可以開啟",
    stopped: "尚未啟動",
    starting: "正在啟動",
    unavailable: "暫時無法開啟",
};
