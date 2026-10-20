function pause(ms: number, signal: AbortSignal) {
    return new Promise<void>((resolve, reject) => {
        signal.throwIfAborted();
        const abort = () => {
            clearTimeout(timer);
            reject(signal.reason);
        };
        const timer = setTimeout(() => {
            signal.removeEventListener("abort", abort);
            resolve();
        }, ms);
        signal.addEventListener("abort", abort, { once: true });
    });
}
/** Only retry explicit warmup responses. Every retry remains cancellable. */
export async function readShared<T>(
    path: string,
    signal: AbortSignal,
    fetcher: typeof fetch = fetch,
    wait: (ms: number, signal: AbortSignal) => Promise<void> = pause,
): Promise<T> {
    for (let attempt = 0; ; attempt++) {
        signal.throwIfAborted();
        const response = await fetcher(`/api/shared-data/v1/${path}`, {
            signal,
        });
        if (
            response.status === 503 &&
            response.headers.has("Retry-After") &&
            attempt < 20
        ) {
            await wait(
                Math.min(
                    3000,
                    Math.max(
                        1000,
                        Number(response.headers.get("Retry-After")) * 1000 ||
                            1000,
                    ),
                ),
                signal,
            );
            continue;
        }
        if (!response.headers.get("content-type")?.includes("application/json"))
            throw new Error(
                "需要本機私有資料 API，請確認前後端都以 local-private 啟動。",
            );
        const data = await response.json();
        if (!response.ok)
            throw new Error(
                typeof data.detail === "string"
                    ? data.detail
                    : `讀取失敗 (${response.status})`,
            );
        signal.throwIfAborted();
        return data as T;
    }
}
