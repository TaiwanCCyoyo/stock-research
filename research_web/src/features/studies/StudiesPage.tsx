import { useMemo, useState } from "react";
import { SourceNotice } from "../../components/SourceNotice";
import { VERDICT_LABELS } from "../../components/ui/verdicts";
import { StudioState } from "../strategies/shared";
import { SkeletonCards } from "../../components/ui/primitives";
import { filterStudies, groupByMonth, type StudyFilter } from "./model";
import { StudiesRefreshNotice } from "./StudiesRefreshNotice";
import { StudyCardView } from "./StudyCardView";
import { useStudyCards } from "./useStudyCards";
import "./studies.css";

export function StudiesPage() {
    const studies = useStudyCards();
    const [filter, setFilter] = useState<StudyFilter>("all");
    const [query, setQuery] = useState("");
    const all = useMemo(() => studies.cards ?? [], [studies.cards]);
    const filters = useMemo(() => {
        const options: { id: StudyFilter; label: string; count: number }[] = [
            { id: "all", label: "全部", count: all.length },
            {
                id: "report",
                label: "有網頁報告",
                count: all.filter((card) => card.reportHref).length,
            },
        ];
        for (const [id, label] of Object.entries(VERDICT_LABELS)) {
            const count = all.filter((card) => card.verdict === id).length;
            if (count) options.push({ id: id as StudyFilter, label, count });
        }
        return options;
    }, [all]);
    const groups = groupByMonth(filterStudies(all, filter, query));
    return (
        <div className="u-page st-page">
            <h1 className="u-title">研究報告</h1>
            <p className="u-lede">
                查看各項研究的問題、結果與限制，也保留未通過或尚未有結論的研究。
            </p>
            <p className="u-muted">
                依研究紀錄日期由新到舊排列。選擇「查看報告」閱讀完整內容。
            </p>
            {!studies.cards ? (
                studies.error ? (
                    <StudioState
                        loading={false}
                        error={studies.error}
                        retry={studies.retry}
                    />
                ) : (
                    <SkeletonCards
                        count={4}
                        className="st-skeleton"
                        label="正在讀取研究"
                    />
                )
            ) : (
                <>
                    {studies.stale && (
                        <StudiesRefreshNotice onRetry={studies.retry} />
                    )}
                    {studies.partial && (
                        <p className="u-notice st-partial">
                            完整研究紀錄暫時讀不到，下面先列出網頁報告。
                        </p>
                    )}
                    <div className="st-toolbar">
                        <div
                            className="u-chips"
                            role="group"
                            aria-label="篩選研究"
                        >
                            {filters.map((option) => (
                                <button
                                    key={option.id}
                                    className="u-chip"
                                    aria-pressed={filter === option.id}
                                    onClick={() => setFilter(option.id)}
                                >
                                    {option.label}
                                    <span className="u-count">
                                        {option.count}
                                    </span>
                                </button>
                            ))}
                        </div>
                        <input
                            className="st-search"
                            type="search"
                            aria-label="搜尋研究"
                            placeholder="搜尋研究主題或結論"
                            value={query}
                            onChange={(event) => setQuery(event.target.value)}
                        />
                    </div>
                    {groups.length === 0 && (
                        <p className="u-skeleton">
                            沒有符合的研究，請更換關鍵字或選擇「全部」。
                        </p>
                    )}
                    {groups.map((group) => (
                        <section key={group.month} className="st-month">
                            <h2 className="st-month-label">{group.label}</h2>
                            <div className="st-timeline">
                                {group.items.map((card) => (
                                    <div
                                        key={card.id}
                                        className="st-node"
                                        data-verdict={card.verdict ?? "none"}
                                    >
                                        <StudyCardView card={card} />
                                    </div>
                                ))}
                            </div>
                        </section>
                    ))}
                    {studies.hidden > 0 && (
                        <p className="u-muted st-hidden">
                            另有 {studies.hidden}{" "}
                            個任務的紀錄暫時無法核對，先不顯示。
                        </p>
                    )}
                    {studies.source && (
                        <div className="st-footnote">
                            <SourceNotice source={studies.source} history />
                        </div>
                    )}
                </>
            )}
        </div>
    );
}
