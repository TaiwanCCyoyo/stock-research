import { useEffect, useState } from "react";
import { readHistoryWhenReady, type HistoryStatus } from "../full-history/api";
import {
    HISTORY_SCHEMA,
    type HistoryFrame,
    type HistoryMetadata,
} from "../full-history/types";
import { latestMarketSummary } from "./model";
import { MarketOverview } from "./HomeView";
import { ProgressLine, SkeletonCards } from "../../components/ui/primitives";
import { StudyCardView } from "../studies/StudyCardView";
import { StudiesRefreshNotice } from "../studies/StudiesRefreshNotice";
import { useStudyCards } from "../studies/useStudyCards";
import "../studies/studies.css";
import "./home.css";
import { readingDate, readingState } from "../studies/reading";

function useLatestMarket() {
    const [frame, setFrame] = useState<HistoryFrame | null>(null),
        [error, setError] = useState(""),
        [startup, setStartup] = useState<HistoryStatus | null>(null),
        [retryCount, setRetryCount] = useState(0);
    useEffect(() => {
        const controller = new AbortController();
        setError("");
        setStartup(null);
        const onStatus = (status: HistoryStatus) => {
            if (!controller.signal.aborted) setStartup(status);
        };
        readHistoryWhenReady<HistoryMetadata>(
            "/metadata",
            controller.signal,
            onStatus,
        )
            .then((metadata) => {
                const latest = metadata.dates.at(-1);
                if (metadata.schema !== HISTORY_SCHEMA || !latest)
                    throw new Error("歷史資料尚未提供最新日期。");
                return readHistoryWhenReady<HistoryFrame>(
                    `/frame?date=${encodeURIComponent(latest)}`,
                    controller.signal,
                    onStatus,
                ).then((value) => {
                    if (
                        value.schema !== HISTORY_SCHEMA ||
                        value.catalogId !== metadata.catalogId ||
                        value.date !== latest
                    )
                        throw new Error("首頁與地圖的資料版本尚未一致。");
                    if (!controller.signal.aborted) setFrame(value);
                });
            })
            .catch((cause) => {
                if (!controller.signal.aborted)
                    setError(
                        cause instanceof Error
                            ? cause.message
                            : "市場資料無法讀取。",
                    );
            });
        return () => controller.abort();
    }, [retryCount]);
    return {
        frame,
        error,
        startup,
        retry: () => setRetryCount((value) => value + 1),
    };
}

export function HomePage() {
    const market = useLatestMarket(),
        studies = useStudyCards();
    const summary = market.frame ? latestMarketSummary(market.frame) : null;
    const recent = [...(studies.cards ?? [])]
        .filter((card) => !card.accountRun && readingState(card) === "ready")
        .sort(
            (a, b) =>
                readingDate(b).localeCompare(readingDate(a)) ||
                a.id.localeCompare(b.id),
        )
        .slice(0, 3);
    const date = market.frame?.date;
    return (
        <div className="u-page hm-page">
            {studies.synthetic && (
                <p className="u-notice">示範資料，不是真實研究結果。</p>
            )}
            <div className="u-eyebrow">
                歷史回看{date ? ` · 截至 ${date.replaceAll("-", "/")}` : ""}
            </div>
            <h1 className="u-title">歷史行情總覽</h1>
            <p className="u-lede">
                回看歷史辨識的波段，不是當時已知的選股訊號。
                首頁列出已出現起漲候選、尚未確認結束且漲幅指標達 100% 的股票；
                滿一年採年化，未滿一年採實際漲幅。
            </p>
            {summary && date ? (
                <MarketOverview summary={summary} date={date} />
            ) : market.error ? (
                <div className="u-card hm-state" role="alert">
                    <p>市場資料暫時讀不到。</p>
                    <button
                        className="u-btn u-btn-primary"
                        onClick={market.retry}
                    >
                        重新讀取
                    </button>
                </div>
            ) : (
                <div className="hm-loading">
                    {market.startup?.state === "loading" &&
                        market.startup.total > 0 && (
                            <ProgressLine
                                label="市場資料準備中"
                                done={market.startup.completed}
                                total={market.startup.total}
                            />
                        )}
                    <SkeletonCards
                        count={2}
                        className="u-grid-2"
                        label="正在讀取市場資料"
                    />
                </div>
            )}
            <h2 className="u-section-title">
                最近的研究 <a href="#studies">全部研究 →</a>
            </h2>
            {studies.cards ? (
                <>
                    {studies.stale && (
                        <StudiesRefreshNotice onRetry={studies.retry} />
                    )}
                    <div className="hm-studies">
                        {recent.length === 0 && (
                            <div className="u-card hm-state" role="status">
                                <p>目前尚無完成閱讀版核對的報告。</p>
                                <a
                                    className="u-btn"
                                    href="#studies?collection=in_progress"
                                >
                                    查看進行中的研究
                                </a>
                                <a
                                    className="u-btn"
                                    href="#studies?collection=history"
                                >
                                    查看歷史與待整理
                                </a>
                            </div>
                        )}
                        {recent.map((card) => (
                            <StudyCardView key={card.id} card={card} compact />
                        ))}
                    </div>
                </>
            ) : studies.error ? (
                <div className="u-card hm-state" role="alert">
                    <p>研究資料暫時讀不到。</p>
                    <button
                        className="u-btn u-btn-primary"
                        onClick={studies.retry}
                    >
                        重新讀取
                    </button>
                </div>
            ) : (
                <SkeletonCards
                    count={3}
                    className="hm-studies"
                    label="正在讀取研究"
                />
            )}
            <h2 className="u-section-title">其他工具</h2>
            <div className="hm-doors">
                <a className="u-card" href="#overview/stocks">
                    <b>個股</b>
                    <span className="u-muted">任一檔股票的價格與指標</span>
                </a>
                <a className="u-card" href="#funds">
                    <b>ETF 圖鑑</b>
                    <span className="u-muted">ETF 怎麼選股、持有什麼</span>
                </a>
            </div>
        </div>
    );
}
