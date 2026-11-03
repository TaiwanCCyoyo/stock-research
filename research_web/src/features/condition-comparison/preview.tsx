import { useState } from "react";
import { createRoot } from "react-dom/client";
import { ConditionComparison } from "./ConditionComparison.tsx";
import { syntheticComparison } from "./fixture.ts";
import type { CaseRequest, QuestionRequest, Selection } from "./model.ts";

export function Preview() {
    const [selection, setSelection] = useState<Selection>();
    const [opened, setOpened] = useState<CaseRequest>();
    const [discussion, setDiscussion] = useState<QuestionRequest>();
    return (
        <main>
            <h1>條件比較元件 · 本地合成預覽</h1>
            <p>
                本預覽沒有市場資料、路由或研究計算。個案 reader
                是合成展示，非真正個股頁。
            </p>
            {opened ? (
                <section>
                    <h2>合成 reader：{opened.item.securityId}</h2>
                    <p>
                        來源 {opened.source.resultId} · H
                        {opened.selection.horizon} · {opened.item.date}
                    </p>
                    <button onClick={() => setOpened(undefined)}>
                        返回原比較
                    </button>
                </section>
            ) : (
                <ConditionComparison
                    state={{ status: "ready", value: syntheticComparison }}
                    selection={selection}
                    onSelectionChange={setSelection}
                    onOpenCase={setOpened}
                    onDiscuss={setDiscussion}
                />
            )}
            {discussion && (
                <section role="status">
                    <h2>討論 callback（未批准、未送出研究）</h2>
                    <pre
                        style={{
                            whiteSpace: "pre-wrap",
                            overflowWrap: "anywhere",
                        }}
                    >
                        {JSON.stringify(discussion, null, 2)}
                    </pre>
                    <button onClick={() => setDiscussion(undefined)}>
                        關閉
                    </button>
                </section>
            )}
        </main>
    );
}
createRoot(document.getElementById("root")!).render(<Preview />);
