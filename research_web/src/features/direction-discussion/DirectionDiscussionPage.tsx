import { useEffect, useMemo, useRef, useState } from "react";
import { attachDiscussion } from "./adapter.ts";
import { fetchDirectionDetail, fetchDirectionIndex } from "./api.ts";
import {
    directionStatusLabel,
    type DirectionDetail,
    type DirectionIndex,
} from "./model.ts";
import {
    useDirectionResource,
    type DirectionResource,
} from "./useDirectionResource.ts";
import "../../../discussion-kit/v1/discussion.css";
import "./direction-discussion.css";

export function DirectionEntrance() {
    return (
        <a className="u-card direction-entrance" href="#directions">
            <strong>研究方向草稿 →</strong>
            <span>查看準備研究的問題，整理比較方式與待確認事項。</span>
        </a>
    );
}
function LoadNotice({
    state,
    retry,
}: {
    state: DirectionResource<unknown>;
    retry: () => void;
}) {
    if (state.status === "loading")
        return (
            <p className="u-card" role="status">
                正在讀取方向草稿…
            </p>
        );
    if (state.status === "error")
        return (
            <div className="u-card">
                <p role="alert">{state.message}</p>
                <button className="u-chip" onClick={retry}>
                    重新讀取
                </button>
            </div>
        );
    return null;
}
export function DirectionListContent({
    state,
    retry,
}: {
    state: DirectionResource<DirectionIndex>;
    retry: () => void;
}) {
    if (state.status !== "loaded")
        return <LoadNotice state={state} retry={retry} />;
    if (!state.data.items.length)
        return (
            <div className="u-card direction-empty" role="status">
                <h2>
                    {state.data.mode === "public-synthetic"
                        ? "示範模式不顯示私人草稿"
                        : "目前還沒有研究方向草稿"}
                </h2>
                <p>
                    {state.data.mode === "public-synthetic"
                        ? "切換至本機私人資料模式後，才能讀取這個專案的方向討論。"
                        : "開始新研究時，作者會把草稿與互動內容放在這裡。現有報告不會被當成新的方向草稿。"}
                </p>
                <a href="#studies">返回研究</a>
            </div>
        );
    return (
        <ul className="direction-list">
            {state.data.items.map((item) => (
                <li key={item.taskId}>
                    <a
                        className="u-card"
                        href={`#direction/${encodeURIComponent(item.taskId)}`}
                    >
                        <span className="direction-status">
                            {directionStatusLabel[item.status]}
                        </span>
                        <h2>{item.title || "方向草稿"}</h2>
                        <p className="u-muted direction-task-id">
                            {item.taskId}
                        </p>
                        <p>
                            {item.message ||
                                (item.status === "ready"
                                    ? "開啟互動討論，看看不同選擇會改變什麼。"
                                    : "開啟查看草稿原文與目前狀態。")}
                        </p>
                    </a>
                </li>
            ))}
        </ul>
    );
}
export function DirectionListPage() {
    const { state, retry } = useDirectionResource(
        "direction-index",
        fetchDirectionIndex,
    );
    return (
        <div className="u-page direction-page">
            <a href="#studies">← 返回研究</a>
            <div className="u-eyebrow">研究方向</div>
            <h1 className="u-title">研究方向草稿</h1>
            <p className="u-lede">
                切換可能的答案、比較研究範圍，把你的想法帶回草稿討論。
            </p>
            <DirectionListContent state={state} retry={retry} />
        </div>
    );
}
function InteractiveDirection({
    detail,
    initialFeedback,
}: {
    detail: DirectionDetail;
    initialFeedback?: unknown;
}) {
    const container = useRef<HTMLDivElement>(null);
    const [error, setError] = useState("");
    useEffect(() => {
        setError("");
        if (!container.current) return;
        try {
            return attachDiscussion(
                container.current,
                detail,
                undefined,
                initialFeedback,
            );
        } catch (reason) {
            setError(
                reason instanceof Error
                    ? reason.message
                    : "互動內容暫時無法開啟，請先查看草稿原文。",
            );
        }
    }, [detail, initialFeedback]);
    return (
        <>
            <div className="direction-view" ref={container} />
            {error && (
                <p className="u-card" role="alert">
                    {error}
                </p>
            )}
        </>
    );
}
export function DirectionDetailContent({
    detail,
    initialFeedback,
}: {
    detail: DirectionDetail;
    initialFeedback?: unknown;
}) {
    return (
        <>
            {detail.status === "ready" ? (
                <InteractiveDirection
                    key={`${detail.taskId}:${detail.revision}`}
                    detail={detail}
                    initialFeedback={initialFeedback}
                />
            ) : (
                <div className="u-card direction-empty">
                    <h1>{directionStatusLabel[detail.status]}</h1>
                    <p>
                        {detail.message ||
                            "互動內容還沒準備好，可以先閱讀草稿原文，並把想法帶回對話。"}
                    </p>
                </div>
            )}
            <details className="u-card direction-source">
                <summary>查看方向草稿原文與版本</summary>
                <p className="u-muted">
                    {detail.taskId} ·{" "}
                    {detail.revision
                        ? `版本 ${detail.revision}`
                        : "版本尚未確認"}
                </p>
                {detail.draftMarkdown !== null ? (
                    <pre>{detail.draftMarkdown}</pre>
                ) : (
                    <p>草稿原文目前無法讀取，請作者檢查來源。</p>
                )}
            </details>
        </>
    );
}
export function DirectionDetailPage({ taskId }: { taskId: string }) {
    const load = useMemo(
        () => (signal: AbortSignal) => fetchDirectionDetail(taskId, signal),
        [taskId],
    );
    const { state, retry } = useDirectionResource(taskId, load);
    return (
        <div className="u-page u-wide direction-page">
            <nav className="direction-back" aria-label="方向討論導覽">
                <a href="#directions">← 所有方向草稿</a>
                <a href="#studies">研究總覽</a>
            </nav>
            <p className="u-muted">
                這裡的選擇是討論提議；整理回饋後再帶回對話或
                PR，不會自動確認或開始計算。
            </p>
            {state.status === "loaded" ? (
                <DirectionDetailContent detail={state.data} />
            ) : (
                <LoadNotice state={state} retry={retry} />
            )}
        </div>
    );
}
