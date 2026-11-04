import "../direction-discussion/adapter.ts";
import {
    interactiveModel,
    type DirectionDetail,
    type DirectionItem,
} from "../direction-discussion/model.ts";
import type { QuestionRequest } from "./model.ts";

/** The selected index revision is a pin, never an instruction to use latest. */
export function comparisonDiscussionFeedback(
    request: QuestionRequest,
    selected: DirectionItem,
    detail: DirectionDetail,
): unknown {
    if (
        selected.status !== "ready" ||
        !selected.revision ||
        !/^[a-f0-9]{40}$/i.test(selected.revision) ||
        selected.taskId !== detail.taskId ||
        selected.revision !== detail.revision
    )
        throw new Error(
            "方向草稿版本已改變或不可用；請重新選擇並核對，未交接問題。",
        );
    const model = interactiveModel(detail);
    if (
        request.intent !== "discussion-only" ||
        !request.question.trim() ||
        request.source.resultId !== request.selection.resultId
    )
        throw new Error("比較問題或來源不完整，未交接問題。");
    const session = globalThis.DirectionDiscussion.createSession(model);
    session.setNotes(
        [
            request.synthetic
                ? "【合成比較流程測試，非市場研究結果】"
                : "【保存比較結果的待議問題】",
            "僅供討論；未批准研究、未回寫草稿、未執行計算。",
            request.question,
            "",
            "比較來源與選取情境（原樣保留，不重算）：",
            JSON.stringify(
                {
                    source: request.source,
                    selection: request.selection,
                    synthetic: request.synthetic,
                },
                null,
                2,
            ),
        ].join("\n"),
    );
    return session.exportFeedback();
}
