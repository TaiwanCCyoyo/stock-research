import { useEffect, useRef, useState } from "react";
import { ConditionComparison } from "./ConditionComparison";
import { syntheticComparison } from "./fixture";
import {
    comparisonBack,
    comparisonSourceHref,
    restoreComparisonEntrance,
    comparisonEntryHref,
    comparisonHref,
    parseComparisonLocation,
    validateComparisonLocation,
} from "./journey";
import type { ComparisonLocation } from "./journey";
import type { ComparisonView, QuestionRequest, SavedCase } from "./model";
import { readRegisteredComparison } from "./registry";

export function ComparisonEntrance({ back }: { back: string }) {
    const entrance = useRef<HTMLAnchorElement>(null);
    const target = comparisonBack(back);
    useEffect(() => {
        restoreComparisonEntrance(location.hash, target, entrance.current);
    }, [target]);
    return (
        <a
            ref={entrance}
            className="u-card direction-entrance"
            href={comparisonEntryHref(syntheticComparison, back)}
            onClick={(event) => {
                if (
                    event.button !== 0 ||
                    event.metaKey ||
                    event.ctrlKey ||
                    event.shiftKey ||
                    event.altKey
                )
                    return;
                // Keep the original history entry focusable on every Back/Forward visit.
                history.replaceState(
                    history.state,
                    "",
                    comparisonSourceHref(target),
                );
            }}
        >
            <strong>試用條件比較流程（合成示例） →</strong>
            <span>只測試四格、個案與返回；不是本研究的真實比較結果。</span>
        </a>
    );
}

function resolve(
    hash: string,
):
    | { view: ComparisonView; route: ComparisonLocation; item?: SavedCase }
    | { error: string } {
    try {
        const route = parseComparisonLocation(hash);
        const state = readRegisteredComparison(route.resultId);
        if (state.status !== "ready")
            throw new Error(
                state.status === "error" ? state.message : "保存結果尚未讀取。",
            );
        return {
            route,
            view: state.value,
            item: validateComparisonLocation(state.value, route),
        };
    } catch (error) {
        return {
            error:
                error instanceof Error ? error.message : "比較網址無法讀取。",
        };
    }
}

export function ComparisonPage() {
    const [hash, setHash] = useState(() => location.hash);
    const [question, setQuestion] = useState<QuestionRequest>();
    const region = useRef<HTMLDivElement>(null);
    useEffect(() => {
        const change = () => {
            setHash(location.hash);
            setQuestion(undefined);
        };
        window.addEventListener("hashchange", change);
        return () => window.removeEventListener("hashchange", change);
    }, []);
    const result = resolve(hash);
    useEffect(() => {
        // DOM identities are compared as text rather than interpolated into selectors.
        const current = resolve(hash);
        if ("error" in current) return;
        const target = current.item
            ? region.current?.querySelector<HTMLElement>("[data-case-heading]")
            : Array.from(
                  region.current?.querySelectorAll<HTMLElement>(
                      "[data-comparison-event]",
                  ) ?? [],
              ).find(
                  (element) =>
                      element.dataset.comparisonEvent ===
                      current.route.selection.eventId,
              );
        target?.focus({ preventScroll: true });
        target?.scrollIntoView({ block: "center" });
    }, [hash]);
    if ("error" in result)
        return (
            <div className="u-page">
                <h1>無法開啟條件比較</h1>
                <p role="alert">{result.error}</p>
                <a className="u-btn" href="#studies">
                    返回研究頁重新選取
                </a>
            </div>
        );
    const { view, route, item } = result;
    const returnHref = comparisonHref(route.selection, route.back);
    const exportQuestion = () => {
        if (!question) return;
        const url = URL.createObjectURL(
            new Blob([JSON.stringify(question, null, 2)], {
                type: "application/json",
            }),
        );
        const link = document.createElement("a");
        link.href = url;
        link.download = "synthetic-comparison-question.json";
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    return (
        <div className="u-page" ref={region}>
            <a className="u-btn" href={comparisonSourceHref(route.back)}>
                返回來源研究頁
            </a>
            <p className="u-notice">
                合成操作示例：沒有載入私有資料，不是市場研究結果。本輪尚未連接正式
                L1 資料契約。
            </p>
            {item ? (
                <section className="condition-comparison">
                    <h1 tabIndex={-1} data-case-heading>
                        合成個案：{item.securityId}
                    </h1>
                    <p>這是保存示例的事件摘要，不是真實個股行情 reader。</p>
                    <dl>
                        <dt>事件／日期</dt>
                        <dd>
                            {item.eventId} · {item.date}
                        </dd>
                        <dt>視窗／結果</dt>
                        <dd>
                            H{route.selection.horizon} · {item.effectiveLabel}
                        </dd>
                        <dt>保存結果／設定版本</dt>
                        <dd>
                            {view.id} · {view.source.settingsVersion}
                        </dd>
                        <dt>輸入／價格基礎</dt>
                        <dd>
                            {view.source.inputVersion} ·{" "}
                            {view.source.priceBasis}
                        </dd>
                    </dl>
                    <p>來源：{view.source.source}</p>
                    <p>沒有對應真實資料版本，因此不提供個股或資料集假連結。</p>
                    <a className="u-btn" href={returnHref}>
                        返回同一格與個案
                    </a>
                </section>
            ) : (
                <ConditionComparison
                    state={{ status: "ready", value: view }}
                    selection={route.selection}
                    onSelectionChange={(next) => {
                        const href = comparisonHref(next, route.back);
                        // Opening a case first enriches the current history entry, then pushes
                        // exactly one reader entry. Back returns to the selected case.
                        if (next.eventId)
                            history.replaceState(history.state, "", href);
                        else location.hash = href;
                    }}
                    onOpenCase={(request) => {
                        location.hash = comparisonHref(
                            request.selection,
                            route.back,
                            request.item.eventId,
                        );
                    }}
                    onDiscuss={setQuestion}
                />
            )}
            {question && (
                <section
                    className="condition-comparison"
                    aria-label="帶來源的問題草稿"
                >
                    <h2>問題草稿（合成來源、尚未批准）</h2>
                    <p>{question.question}</p>
                    <p>
                        {question.source.resultId} ·{" "}
                        {question.source.settingsVersion} · H
                        {question.selection.horizon}
                    </p>
                    <p>
                        匯出供下一輪討論核對；尚未綁定方向草稿
                        revision，不會建立、批准或執行研究。
                    </p>
                    <button onClick={exportQuestion}>
                        匯出問題與來源 JSON
                    </button>
                    <button onClick={() => setQuestion(undefined)}>
                        關閉草稿
                    </button>
                </section>
            )}
        </div>
    );
}
