import { apiUrl } from "../../api/base.ts";
import { artifactMode, type ArtifactMode } from "../../api/artifactMode.ts";
import {
    directionTaskId,
    readDirectionDetail,
    readDirectionIndex,
} from "./model.ts";

export function directionMode(): ArtifactMode {
    return artifactMode(import.meta.env?.VITE_ARTIFACT_MODE);
}
async function readJson(
    path: string,
    signal: AbortSignal,
    mode: ArtifactMode,
    fetcher: typeof fetch,
) {
    signal.throwIfAborted();
    const response = await fetcher(apiUrl(path), {
        signal,
        cache: "no-store",
        headers: { "X-Research-Data-Mode": mode },
    });
    if (!response.ok)
        throw new Error(
            response.status === 404
                ? "找不到這份方向草稿，請返回清單確認。"
                : `方向草稿暫時無法讀取（${response.status}），請稍後重試。`,
        );
    if (!response.headers.get("content-type")?.includes("application/json"))
        throw new Error(
            "方向草稿服務沒有回傳可讀取的資料，請確認本機 API 已啟動。",
        );
    const value: unknown = await response.json();
    signal.throwIfAborted();
    return value;
}
export async function fetchDirectionIndex(
    signal: AbortSignal,
    mode: ArtifactMode = directionMode(),
    fetcher: typeof fetch = fetch,
) {
    return readDirectionIndex(
        await readJson("/direction-drafts", signal, mode, fetcher),
        mode,
    );
}
export async function fetchDirectionDetail(
    taskId: string,
    signal: AbortSignal,
    mode: ArtifactMode = directionMode(),
    fetcher: typeof fetch = fetch,
) {
    if (!directionTaskId(taskId))
        throw new Error("方向草稿的網址無效，請返回清單。");
    if (mode === "public-synthetic")
        throw new Error("示範模式不提供私人方向草稿。");
    return readDirectionDetail(
        await readJson(
            `/direction-drafts/${encodeURIComponent(taskId)}`,
            signal,
            mode,
            fetcher,
        ),
        taskId,
        mode,
    );
}
