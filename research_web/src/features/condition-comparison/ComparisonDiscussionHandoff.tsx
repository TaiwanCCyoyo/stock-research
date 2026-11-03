import { useMemo, useState } from "react";
import {
    fetchDirectionDetail,
    fetchDirectionIndex,
} from "../direction-discussion/api";
import { DirectionDetailContent } from "../direction-discussion/DirectionDiscussionPage";
import type { DirectionItem } from "../direction-discussion/model";
import { useDirectionResource } from "../direction-discussion/useDirectionResource";
import { comparisonDiscussionFeedback } from "./discussionHandoff";
import type { QuestionRequest } from "./model";

function SelectedDiscussion({
    request,
    selected,
}: {
    request: QuestionRequest;
    selected: DirectionItem;
}) {
    const load = useMemo(
        () => (signal: AbortSignal) =>
            fetchDirectionDetail(selected.taskId, signal),
        [selected.taskId],
    );
    const { state, retry } = useDirectionResource(
        `${selected.taskId}:${selected.revision}`,
        load,
    );
    const [opened, setOpened] = useState(false);
    const prepared = useMemo(() => {
        if (state.status !== "loaded") return null;
        try {
            return {
                feedback: comparisonDiscussionFeedback(
                    request,
                    selected,
                    state.data,
                ),
            };
        } catch (error) {
            return {
                error:
                    error instanceof Error ? error.message : "來源無法核對。",
            };
        }
    }, [request, selected, state]);
    if (state.status === "loading")
        return <p role="status">正在核對指定版本…</p>;
    if (state.status === "error")
        return (
            <div>
                <p role="alert">{state.message}</p>
                <button onClick={retry}>重試讀取</button>
            </div>
        );
    if (!prepared || "error" in prepared)
        return <p role="alert">{prepared?.error ?? "無法交接。"}</p>;
    return (
        <section aria-label="同版本方向討論交接">
            <p>
                {request.synthetic
                    ? "合成問題交接，非研究結論。"
                    : "待議問題交接。"}
                選取的草稿版本：
            </p>
            <p>{selected.taskId}</p>
            <p>
                <code>{`tasks/${selected.taskId}/direction-draft.md`}</code>
            </p>
            <p style={{ overflowWrap: "anywhere" }}>
                <code>{selected.revision}</code>
            </p>
            <p>
                問題與來源會放進此版本討論的備註。所有選項仍未選，不會保存或回寫；關閉或離開會清除未匯出的修改。
            </p>
            {!opened ? (
                <button onClick={() => setOpened(true)}>
                    把問題放入此版本討論
                </button>
            ) : (
                <DirectionDetailContent
                    detail={state.data}
                    initialFeedback={prepared.feedback}
                />
            )}
        </section>
    );
}

/** Explicit user entry; read-only API discovery. No target/revision is inferred. */
export function ComparisonDiscussionHandoff({
    request,
}: {
    request: QuestionRequest;
}) {
    const { state, retry } = useDirectionResource(
        "comparison-direction-index",
        fetchDirectionIndex,
    );
    const [selected, setSelected] = useState<DirectionItem>();
    if (state.status === "loading")
        return <p role="status">正在讀取可交接的方向草稿…</p>;
    if (state.status === "error")
        return (
            <div>
                <p role="alert">{state.message}</p>
                <button onClick={retry}>重新讀取草稿清單</button>
            </div>
        );
    const ready = state.data.items.filter(
        (item) => item.status === "ready" && item.revision,
    );
    return (
        <div>
            {!ready.length ? (
                <p role="status">
                    目前沒有可核對版本的方向草稿。保留問題匯出即可；不會自動建立草稿。
                </p>
            ) : (
                <label>
                    選擇要接續討論的草稿
                    <select
                        value={selected?.taskId ?? ""}
                        onChange={(event) =>
                            setSelected(
                                ready.find(
                                    (item) =>
                                        item.taskId === event.target.value,
                                ),
                            )
                        }
                    >
                        <option value="">請選擇，尚未交接</option>
                        {ready.map((item) => (
                            <option key={item.taskId} value={item.taskId}>
                                {item.title || item.taskId} · {item.taskId}
                            </option>
                        ))}
                    </select>
                </label>
            )}
            <button
                onClick={() => {
                    setSelected(undefined);
                    retry();
                }}
            >
                重新核對清單（清除未匯出的討論）
            </button>
            {selected && (
                <SelectedDiscussion
                    key={`${selected.taskId}:${selected.revision}`}
                    selected={selected}
                    request={request}
                />
            )}
        </div>
    );
}
