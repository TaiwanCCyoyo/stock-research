import { useEffect, useState } from "react";
import { artifactMode, assertArtifactResponseMode } from "./artifactMode.ts";
import {
    studioAccountPath,
    studioRunPath,
    studioTradePath,
} from "./strategyPaths";
import type {
    StudioAccount,
    StudioHistory,
    StudioIndex,
    StudioRun,
    StudioTrade,
} from "../domain/strategies/types";

export const STRATEGY_API = "/history-api/saved-research-studio/v1";
export async function readStrategyStudio<T>(
    path: string,
    signal?: AbortSignal,
): Promise<T> {
    const response = await fetch(`${STRATEGY_API}${path}`, {
        signal,
        headers: {
            "X-Research-Data-Mode": artifactMode(
                import.meta.env.VITE_ARTIFACT_MODE,
            ),
        },
    });
    if (!response.ok)
        throw new Error(
            response.status === 404
                ? "這份研究尚未提供完整明細。"
                : `研究資料暫時無法讀取（${response.status}）。`,
        );
    if (response.headers.get("content-type")?.includes("text/html"))
        throw new Error("研究資料服務尚未啟動。");
    const value: unknown = await response.json();
    assertArtifactResponseMode(value, import.meta.env.VITE_ARTIFACT_MODE);
    return value as T;
}
export function useStudioResource<T>(path: string | null) {
    const [data, setData] = useState<T | null>(null);
    const [loadedPath, setLoadedPath] = useState<string | null>(null);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(false);
    const [retryCount, setRetryCount] = useState(0);
    useEffect(() => {
        setData(null);
        setError("");
        if (!path) {
            setLoading(false);
            return;
        }
        const controller = new AbortController();
        let timer: ReturnType<typeof setTimeout> | undefined;
        setLoading(true);
        const read = () =>
            readStrategyStudio<T>(path, controller.signal)
                .then((value) => {
                    if (controller.signal.aborted) return;
                    setData(value);
                    setLoadedPath(path);
                    setLoading(false);
                    if (
                        typeof value === "object" &&
                        value !== null &&
                        "captureState" in value &&
                        value.captureState === "loading"
                    )
                        timer = setTimeout(read, 2000);
                })
                .catch((cause) => {
                    if (!controller.signal.aborted) {
                        setError(
                            cause instanceof Error
                                ? cause.message
                                : "研究資料無法讀取。",
                        );
                        setLoadedPath(path);
                        setLoading(false);
                    }
                });
        void read();
        return () => {
            controller.abort();
            clearTimeout(timer);
        };
    }, [path, retryCount]);
    return {
        data: loadedPath === path ? data : null,
        error: loadedPath === path ? error : "",
        loading: loading || (path !== null && loadedPath !== path),
        retry: () => setRetryCount((value) => value + 1),
    };
}
export const useStudioIndex = () => useStudioResource<StudioIndex>("/runs");
export const useStudioRun = (runId: string | null) =>
    useStudioResource<StudioRun>(runId ? studioRunPath(runId) : null);
export const useStudioTrade = (runId: string, tradeId: string | null) =>
    useStudioResource<StudioTrade>(
        tradeId ? studioTradePath(runId, tradeId) : null,
    );
export const useStudioAccount = (runId: string, date: string | null) =>
    useStudioResource<StudioAccount>(
        date ? studioAccountPath(runId, date) : null,
    );
export const useStudioHistory = () =>
    useStudioResource<StudioHistory>("/research-history");
