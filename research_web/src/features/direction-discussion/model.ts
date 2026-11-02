import type { ArtifactMode } from "../../api/artifactMode.ts";

export type DirectionStatus = "ready" | "draft-only" | "unavailable";
export interface DirectionItem {
    taskId: string;
    status: DirectionStatus;
    revision: string | null;
    message: string | null;
}
export interface DirectionIndex {
    schema: "direction-drafts.v1";
    mode: ArtifactMode;
    items: DirectionItem[];
}
export interface DirectionDetail extends DirectionItem {
    schema: "direction-draft.v1";
    mode: ArtifactMode;
    draftMarkdown: string | null;
    model: Record<string, unknown> | null;
}

export function directionTaskId(value: unknown): value is string {
    return (
        typeof value === "string" &&
        /^[0-9]{8}-[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value)
    );
}
function record(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === "object" && !Array.isArray(value);
}
function readItem(value: unknown): DirectionItem {
    if (
        !record(value) ||
        !directionTaskId(value.taskId) ||
        !["ready", "draft-only", "unavailable"].includes(
            String(value.status),
        ) ||
        !(
            value.revision === null ||
            (typeof value.revision === "string" &&
                /^[a-f0-9]{40}$/i.test(value.revision))
        ) ||
        !(value.message === null || typeof value.message === "string")
    )
        throw new Error(
            "方向草稿的識別資訊不完整，請重新整理或請作者檢查來源。",
        );
    if (value.status === "ready" && value.revision === null)
        throw new Error("互動草稿沒有可核對的版本，暫時無法開啟。");
    return {
        taskId: value.taskId,
        status: value.status as DirectionStatus,
        revision: value.revision as string | null,
        message: value.message as string | null,
    };
}
function checkMode(value: Record<string, unknown>, expected: ArtifactMode) {
    if (value.mode !== expected)
        throw new Error("方向草稿的資料模式不一致，請確認前後端使用相同模式。");
}
export function readDirectionIndex(
    value: unknown,
    expected: ArtifactMode,
): DirectionIndex {
    if (
        !record(value) ||
        value.schema !== "direction-drafts.v1" ||
        !Array.isArray(value.items)
    )
        throw new Error("方向草稿清單格式無法辨識。");
    checkMode(value, expected);
    if (expected === "public-synthetic" && value.items.length)
        throw new Error("示範模式不應載入私人方向草稿，已停止顯示。");
    const items = value.items.map(readItem);
    if (new Set(items.map((item) => item.taskId)).size !== items.length)
        throw new Error("方向草稿清單有重複項目，請作者檢查來源。");
    return { schema: "direction-drafts.v1", mode: expected, items };
}
export function readDirectionDetail(
    value: unknown,
    taskId: string,
    expected: ArtifactMode,
): DirectionDetail {
    if (expected === "public-synthetic")
        throw new Error("示範模式不提供私人方向草稿。");
    if (!record(value) || value.schema !== "direction-draft.v1")
        throw new Error("方向草稿內容格式無法辨識。");
    checkMode(value, expected);
    const item = readItem(value);
    if (item.taskId !== taskId)
        throw new Error("回傳的方向草稿與目前頁面不同，已停止顯示。");
    if (
        !(
            value.draftMarkdown === null ||
            typeof value.draftMarkdown === "string"
        ) ||
        !(value.model === null || record(value.model))
    )
        throw new Error("方向草稿內容不完整，請作者檢查來源。");
    return {
        ...item,
        schema: "direction-draft.v1",
        mode: expected,
        draftMarkdown: value.draftMarkdown as string | null,
        model: value.model as Record<string, unknown> | null,
    };
}

/** Verify identity before the shared renderer sees any interactive content. */
export function interactiveModel(
    detail: DirectionDetail,
): Record<string, unknown> {
    const model = detail.model;
    if (
        detail.mode !== "local-private" ||
        detail.status !== "ready" ||
        !detail.revision ||
        !detail.draftMarkdown ||
        !model
    )
        throw new Error("這份草稿尚未提供可核對的互動內容。");
    if (
        model.schema !== "direction-discussion.v1" ||
        model.demo !== false ||
        !record(model.source) ||
        model.source.taskId !== detail.taskId ||
        model.source.draftPath !==
            `tasks/${detail.taskId}/direction-draft.md` ||
        model.source.revision !== detail.revision
    )
        throw new Error("互動內容與草稿版本不一致，先保留原文供核對。");
    return model;
}

export const directionStatusLabel: Record<DirectionStatus, string> = {
    ready: "可互動討論",
    "draft-only": "已有草稿原文",
    unavailable: "來源待核對",
};
