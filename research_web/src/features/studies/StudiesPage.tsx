import { useEffect, useMemo, useState } from "react";
import { SourceNotice } from "../../components/SourceNotice";
import { VERDICT_LABELS } from "../../components/ui/verdicts";
import { StudioState } from "../strategies/shared";
import { SkeletonCards } from "../../components/ui/primitives";
import { filterStudies, groupByMonth, type StudyFilter } from "./model";
import { StudiesRefreshNotice } from "./StudiesRefreshNotice";
import { StudyCardView } from "./StudyCardView";
import { useStudyCards } from "./useStudyCards";
import { DirectionEntrance } from "../direction-discussion/DirectionDiscussionPage";
import { ComparisonEntrance } from "../condition-comparison/ComparisonPage";
import { comparisonRequestsSourceFocus } from "../condition-comparison/journey";
import "./studies.css";
import {
    currentStudyHash,
    READING_LABELS,
    studyCollection,
    type ReadingState,
} from "./reading";

function selection() {
    const params = new URLSearchParams(currentStudyHash().split("?")[1] ?? "");
    const value = params.get("collection");
    const outcome = params.get("filter") ?? params.get("outcome");
    return {
        collection: (value === "in_progress" || value === "history"
            ? value
            : "ready") as ReadingState,
        query: params.get("q") ?? "",
        filter: (Object.hasOwn(VERDICT_LABELS, outcome ?? "")
            ? outcome
            : "all") as StudyFilter,
    };
}

export function StudiesPage() {
    const studies = useStudyCards();
    const [selected, setSelected] = useState(selection);
    const { filter, query } = selected;
    const params = new URLSearchParams(currentStudyHash().split("?")[1] ?? "");
    const study = params.get("study");
    const focusedCard = studies.cards?.find((card) => card.id === study);
    const collection =
        focusedCard && !params.has("collection")
            ? studyCollection(focusedCard)
            : selected.collection;
    const comparisonFocus = comparisonRequestsSourceFocus(currentStudyHash());
    const [searchDraft, setSearchDraft] = useState(query);
    useEffect(() => setSearchDraft(query), [query]);
    const setQuery = (value: string) => update({ query: value });
    useEffect(() => {
        if (comparisonFocus || !study || !studies.cards) return;
        const element = document.getElementById("study-" + study);
        if (element) {
            element.focus({ preventScroll: true });
            element.scrollIntoView({ block: "center" });
        }
    }, [comparisonFocus, study, studies.cards]);
    function update(next: Partial<typeof selected>) {
        const value = { ...selected, collection, ...next };
        const params = new URLSearchParams(
            currentStudyHash().split("?")[1] ?? "",
        );
        for (const key of [
            "study",
            "focus",
            "collection",
            "outcome",
            "filter",
            "q",
        ])
            params.delete(key);
        if (value.collection !== "ready")
            params.set("collection", value.collection);
        if (value.filter !== "all") params.set("filter", value.filter);
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
        if (!loaded || study || comparisonFocus) return;
        try {
            const y = Number(
                sessionStorage.getItem(`study-scroll:${window.location.hash}`),
            );
            if (y > 0) requestAnimationFrame(() => window.scrollTo(0, y));
        } catch {
            /* Storage is optional. */
        }
    }, [loaded, study, comparisonFocus]);
    const all = useMemo(
        () =>
            (studies.cards ?? []).filter(
                (card) => studyCollection(card) === collection,
            ),
        [studies.cards, collection],
    );
    const filters = useMemo(() => {
        const options: { id: StudyFilter; label: string; count: number }[] = [
            { id: "all", label: "全部", count: all.length },
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
            <h1 className="u-title">股票研究報告</h1>
            <p className="u-lede">
                查看選股與交易方法的研究結果、比較依據與限制。
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
                            完整紀錄暫時無法讀取，目前顯示備用紀錄；來源與核對狀態會列在各份報告。
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
                                                studyCollection(card) === key,
                                        ).length
                                    }
                                </span>
                            </button>
                        ))}
                    </div>
                    <p className="u-muted">
                        {collection === "ready"
                            ? "每份報告列出研究問題、發現與限制。依內容更新日期排列。"
                            : collection === "in_progress"
                              ? "查看正在規劃、執行或修訂的研究；各頁標示目前進度與已有發現。"
                              : "已封存的研究與模擬紀錄；部分只保留原始資料，未提供網頁報告。"}
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
                        <form
                            role="search"
                            onSubmit={(event) => {
                                event.preventDefault();
                                setQuery(searchDraft.trim());
                            }}
                        >
                            <input
                                className="st-search"
                                type="search"
                                aria-label="搜尋研究"
                                placeholder="問題、關鍵字或任務代號"
                                value={searchDraft}
                                onChange={(event) =>
                                    setSearchDraft(event.target.value)
                                }
                            />
                            <button className="u-btn" type="submit">
                                搜尋
                            </button>
                        </form>
                    </div>
                    {groups.length === 0 && (
                        <div className="u-card" role="status">
                            <p>
                                {query || filter !== "all"
                                    ? "沒有符合篩選的研究。"
                                    : collection === "ready"
                                      ? "目前沒有研究報告。可先查看進行中的研究。"
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
            <section className="st-research-tools" aria-label="研究規劃與工具">
                <h2>研究規劃與工具</h2>
                <DirectionEntrance />
                <ComparisonEntrance back={currentStudyHash() || "#studies"} />
            </section>
        </div>
    );
}
