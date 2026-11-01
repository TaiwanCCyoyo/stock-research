import { useEffect, useMemo, useState } from "react";
import { SourceNotice } from "../../components/SourceNotice";
import { VERDICT_LABELS } from "../../components/ui/verdicts";
import { StudioState } from "../strategies/shared";
import { SkeletonCards } from "../../components/ui/primitives";
import { filterStudies, groupByMonth, type StudyFilter } from "./model";
import { StudiesRefreshNotice } from "./StudiesRefreshNotice";
import { StudyCardView } from "./StudyCardView";
import { useStudyCards } from "./useStudyCards";
import "./studies.css";
import {
    currentStudyHash,
    READING_LABELS,
    readingState,
    type ReadingState,
} from "./reading";

function selection() {
    const params = new URLSearchParams(currentStudyHash().split("?")[1] ?? "");
    const value = params.get("collection");
    return {
        collection: (value === "in_progress" || value === "history"
            ? value
            : "ready") as ReadingState,
        query: params.get("q") ?? "",
        filter: (params.get("outcome") === "report" ||
        Object.hasOwn(VERDICT_LABELS, params.get("outcome") ?? "")
            ? params.get("outcome")
            : "all") as StudyFilter,
    };
}

export function StudiesPage() {
    const studies = useStudyCards();
    const [selected, setSelected] = useState(selection);
    const { collection, filter, query } = selected;
    function update(next: Partial<typeof selected>) {
        const value = { ...selected, ...next };
        const params = new URLSearchParams();
        if (value.collection !== "ready")
            params.set("collection", value.collection);
        if (value.filter !== "all") params.set("outcome", value.filter);
        if (value.query) params.set("q", value.query);
        window.history.replaceState(
            null,
            "",
            `#studies${params.size ? `?${params}` : ""}`,
        );
        setSelected(value);
    }
    useEffect(() => {
        const change = () => setSelected(selection());
        window.addEventListener("hashchange", change);
        return () => window.removeEventListener("hashchange", change);
    }, []);
    const loaded = !!studies.cards;
    useEffect(() => {
        if (!loaded) return;
        try {
            const y = Number(
                sessionStorage.getItem(`study-scroll:${window.location.hash}`),
            );
            if (y > 0) requestAnimationFrame(() => window.scrollTo(0, y));
        } catch {
            /* Storage is optional. */
        }
    }, [loaded]);
    const all = useMemo(
        () =>
            (studies.cards ?? []).filter(
                (card) => readingState(card) === collection,
            ),
        [studies.cards, collection],
    );
    const filters = useMemo(() => {
        const options: { id: StudyFilter; label: string; count: number }[] = [
            { id: "all", label: "全部", count: all.length },
            {
                id: "report",
                label: "有閱讀入口",
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
        <div
            className="u-page st-page"
            onClickCapture={(event) => {
                if (
                    (event.target as HTMLElement).closest("a[href^='#report/']")
                ) {
                    try {
                        sessionStorage.setItem(
                            `study-scroll:${window.location.hash}`,
                            String(window.scrollY),
                        );
                    } catch {
                        /* Optional. */
                    }
                }
            }}
        >
            <div className="u-eyebrow">研究</div>
            <h1 className="u-title">研究總覽</h1>
            <p className="u-lede">查看研究問題、目前答案與尚未回答的部分。</p>
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
                            完整紀錄暫時無法讀取；備用紀錄列在歷史與待整理，不視為已核對報告。
                        </p>
                    )}
                    <div
                        className="u-segmented"
                        role="group"
                        aria-label="研究資料分類"
                    >
                        {(
                            Object.entries(READING_LABELS) as [
                                ReadingState,
                                string,
                            ][]
                        ).map(([key, label]) => (
                            <button
                                key={key}
                                aria-pressed={collection === key}
                                onClick={() =>
                                    update({ collection: key, filter: "all" })
                                }
                            >
                                {label}{" "}
                                <span className="u-count">
                                    {
                                        studies.cards?.filter(
                                            (card) =>
                                                readingState(card) === key,
                                        ).length
                                    }
                                </span>
                            </button>
                        ))}
                    </div>
                    <p className="u-muted">
                        {collection === "ready"
                            ? "已完成閱讀版核對，包含正面、負面與部分回答的研究。依閱讀版更新日期排列。"
                            : collection === "in_progress"
                              ? "規劃、執行或修訂中的研究，尚未視為完成報告。"
                              : "保留原始紀錄與來源缺口；整理或核對完成後，可回到報告列表。"}
                    </p>
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
                                    onClick={() =>
                                        update({ filter: option.id })
                                    }
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
                            placeholder="問題、關鍵字或任務代號"
                            value={query}
                            onChange={(event) =>
                                update({ query: event.target.value })
                            }
                        />
                    </div>
                    {groups.length === 0 && (
                        <div className="u-card" role="status">
                            <p>
                                {query || filter !== "all"
                                    ? "沒有符合篩選的研究。"
                                    : collection === "ready"
                                      ? "目前尚無完成閱讀版核對的報告。可先查看進行中或歷史與待整理。"
                                      : "這個分類目前沒有紀錄。"}
                            </p>
                            {(query || filter !== "all") && (
                                <button
                                    className="u-btn"
                                    onClick={() =>
                                        update({ query: "", filter: "all" })
                                    }
                                >
                                    清除篩選
                                </button>
                            )}
                        </div>
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
