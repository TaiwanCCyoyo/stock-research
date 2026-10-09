import { useMemo, useState } from "react";
import { useStudioHistory } from "../../api/strategyStudio";
import { StudioState } from "../strategies/shared";
import { ResearchMarkdown } from "./ResearchMarkdown";
import {
    filterHistoryItems,
    HISTORY_SECTIONS,
    historyConclusion,
    historyOutcome,
    type HistorySection,
} from "./historyModel";
import "../strategies/strategies.css";

function historyStatus(value: string) {
    const normalized = value.toLocaleLowerCase();
    if (/[\u4e00-\u9fff]/.test(value)) return value;
    return normalized.includes("fail") ||
        normalized === "negative" ||
        normalized === "no-go"
        ? "行不通"
        : normalized === "mixed"
          ? "結果不一"
          : normalized === "closed" || normalized === "completed"
            ? "已結案"
            : "研究中";
}
export function ResearchHistoryPage() {
    const resource = useStudioHistory(),
        [query, setQuery] = useState(""),
        [section, setSection] = useState<HistorySection>("method");
    const items = useMemo(
        () =>
            filterHistoryItems(resource.data?.items ?? [], section, query).sort(
                (a, b) =>
                    b.date.localeCompare(a.date) || a.id.localeCompare(b.id),
            ),
        [resource.data, query, section],
    );
    return (
        <div className="ss-page">
            <div className="ss-head-row">
                <div>
                    <h1>研究歷程</h1>
                    <p className="ss-muted">
                        做過的嘗試與保存的結論，包含行不通的方法。
                    </p>
                </div>
                <input
                    className="ss-query"
                    aria-label="搜尋研究歷程"
                    placeholder="搜尋方法或研究結論"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                />
            </div>
            <p className="ss-warning">
                這裡只列已登錄且仍可取得的研究證據，不能宣稱涵蓋全部歷史；白話摘要仍需研究端核對，以保存原文與正式判定為準。研究結案不等於批准採用。
            </p>
            <div className="ss-head-row" role="group" aria-label="研究類別">
                {HISTORY_SECTIONS.map((option) => (
                    <button
                        key={option.value}
                        className="ss-button"
                        aria-pressed={section === option.value}
                        onClick={() => setSection(option.value)}
                    >
                        {option.label}
                    </button>
                ))}
            </div>
            {query.trim() && (
                <p className="ss-small ss-muted">搜尋結果包含所有研究類別。</p>
            )}
            {!resource.data ? (
                <StudioState {...resource} />
            ) : !items.length ? (
                <StudioState {...resource} empty />
            ) : (
                <div className="ss-history">
                    {items.map((item) => (
                        <article className="ss-history-item" key={item.id}>
                            <div className="ss-head-row">
                                <small className="ss-muted">{item.date}</small>
                                <span
                                    className={`ss-status ${item.outcome === "candidate_failed" ? "ss-status-failed" : "ss-status-research"}`}
                                >
                                    {historyOutcome(item)}
                                </span>
                            </div>
                            <h2>{item.title}</h2>
                            <ResearchMarkdown text={historyConclusion(item)} />
                            <details>
                                <summary>查看原文摘要與研究證據</summary>
                                {item.summarySource ===
                                    "presentation-metadata" &&
                                    !item.reviewConfirmed && (
                                        <p className="ss-small ss-muted">
                                            白話摘要待研究端核對
                                        </p>
                                    )}
                                {item.savedTitle &&
                                    !item.originalTitleUnavailable && (
                                        <p className="ss-muted">
                                            報告版本的標題：{item.savedTitle}
                                        </p>
                                    )}
                                {item.originalTitleUnavailable && (
                                    <p className="ss-muted">
                                        較早的展示包未保存原報告標題。
                                    </p>
                                )}
                                {item.draftStatus && (
                                    <p className="ss-small ss-muted">
                                        示範判讀：
                                        {historyStatus(item.draftStatus)}
                                        （待核對；不覆蓋正式研究結果）
                                    </p>
                                )}
                                <ResearchMarkdown
                                    text={
                                        item.originalSummary ||
                                        "沒有保存原文摘要。"
                                    }
                                />
                                {item.summarySource ===
                                    "presentation-metadata" && (
                                    <p className="ss-muted">
                                        {item.reviewConfirmed
                                            ? "已核對摘要措辭；不代表最終採用。"
                                            : item.sourceNote ||
                                              "摘要尚未核對；不代表正式研究判定。"}
                                    </p>
                                )}
                                {item.reportPath && (
                                    <>
                                        <b>報告位置</b>
                                        <p className="ss-report-path">
                                            {item.reportPath}
                                        </p>
                                    </>
                                )}
                            </details>
                        </article>
                    ))}
                </div>
            )}
        </div>
    );
}
