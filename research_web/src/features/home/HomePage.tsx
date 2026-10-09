import { useEffect, useState } from "react";
import { useStudioHistory, useStudioIndex } from "../../api/strategyStudio";
import { readHistoryWhenReady, type HistoryStatus } from "../full-history/api";
import {
    HISTORY_SCHEMA,
    type HistoryFrame,
    type HistoryMetadata,
} from "../full-history/types";
import { historyConclusion } from "../research-history/historyModel";
import { strategyTitle } from "../strategies/presentation";
import { money, percentage } from "../strategies/format";
import { strategyStatus } from "../strategies/model";
import { StudioState } from "../strategies/shared";
import { latestMarketSummary } from "./model";
import { ResearchMarkdown } from "../research-history/ResearchMarkdown";
import { marketCaptureLink } from "../full-history/navigation.ts";
import "../strategies/strategies.css";

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
        strategies = useStudioIndex(),
        history = useStudioHistory();
    const summary = market.frame ? latestMarketSummary(market.frame) : null;
    const runs = strategies.data?.runs ?? [],
        adopted = runs.filter(
            (run) => strategyStatus(run) === "adopted",
        ).length,
        research = runs.filter(
            (run) => strategyStatus(run) === "research",
        ).length,
        failed = runs.filter((run) => strategyStatus(run) === "failed").length;
    const recent = [...(history.data?.items ?? [])]
        .sort(
            (a, b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id),
        )
        .slice(0, 3);
    const maxIndustry = summary?.industries[0]?.rows.length ?? 1;
    return (
        <div className="ss-page">
            <h1>研究與發現</h1>
            <p className="ss-muted">
                先看市場正在發生什麼，再看研究過的策略有沒有跟上。
            </p>
            <div className="ss-links ss-grid">
                <a href="#market">
                    <b>飆股地圖 →</b>
                    <span>拖曳時間，看哪些產業和股票正在大漲</span>
                </a>
                <a href="#strategies">
                    <b>策略總覽 →</b>
                    <span>成績、代價與可以逐筆核對的買賣</span>
                </a>
                <a href="#history">
                    <b>研究歷程 →</b>
                    <span>做過哪些研究、哪些方法沒有通過</span>
                </a>
                <a href="#funds">
                    <b>ETF 圖鑑 →</b>
                    <span>選股方法、持股與資料覆蓋限制</span>
                </a>
            </div>
            <section className="ss-card">
                <div className="ss-head-row">
                    <h2>最新市場</h2>
                    <span className="ss-muted">
                        {market.frame?.date ?? "正在取得最新資料日"}
                    </span>
                </div>
                <p className="ss-muted">
                    已開始大漲，時間指標達
                    100%；滿一年看年化、未滿一年看實際漲幅。
                </p>
                {!summary ? (
                    market.error ? (
                        <div className="ss-error">
                            <p>{market.error}</p>
                            <button
                                className="ss-button"
                                onClick={market.retry}
                            >
                                重新讀取市場
                            </button>
                        </div>
                    ) : (
                        <p className="ss-loading">
                            {market.startup?.state === "loading"
                                ? `歷史資料正在背景核對${market.startup.total > 0 ? `（${market.startup.completed}／${market.startup.total}）` : ""}，完成後會自動更新。`
                                : "正在讀取與飆股地圖相同的資料…"}
                        </p>
                    )
                ) : (
                    <>
                        <div className="ss-kpis">
                            <div className="ss-kpi">
                                <span>當天在版圖上的股票</span>
                                <strong>{summary.count} 檔</strong>
                                <small>與地圖同一日期、同一門檻</small>
                            </div>
                            <div className="ss-kpi">
                                <span>涵蓋產業</span>
                                <strong>{summary.industries.length} 個</strong>
                                <small>分類未知仍保留</small>
                            </div>
                        </div>
                        <div className="ss-grid">
                            <div>
                                <h3>產業分布</h3>
                                <div className="ss-distribution">
                                    {summary.industries
                                        .slice(0, 10)
                                        .map((group) => (
                                            <div
                                                className="ss-industry-row"
                                                key={group.id}
                                            >
                                                <div>
                                                    <b>
                                                        {group.label} ·{" "}
                                                        {group.rows.length} 檔
                                                    </b>
                                                    <small className="ss-muted">
                                                        最強 {group.best.name} ·{" "}
                                                        {percentage(
                                                            (group.best.growth
                                                                ?.sizingGainPct ??
                                                                0) / 100,
                                                        )}
                                                        {group.best.growth
                                                            ?.basis ===
                                                        "annualized"
                                                            ? " 年化"
                                                            : " 實際"}
                                                    </small>
                                                </div>
                                                <div className="ss-bar">
                                                    <span
                                                        style={{
                                                            width: `${(group.rows.length / maxIndustry) * 100}%`,
                                                        }}
                                                    />
                                                </div>
                                            </div>
                                        ))}
                                </div>
                                <a
                                    className="ss-button"
                                    href={marketCaptureLink(market.frame!.date)}
                                >
                                    探索完整版圖 →
                                </a>
                            </div>
                            <div>
                                <h3>漲最兇的幾檔</h3>
                                <div className="ss-table-wrap">
                                    <table className="ss-table">
                                        <thead>
                                            <tr>
                                                <th>股票</th>
                                                <th>時間指標</th>
                                                <th>本波起點</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {summary.strongest.map((row) => (
                                                <tr key={row.securityId}>
                                                    <td>
                                                        <a
                                                            href={marketCaptureLink(
                                                                market.frame!
                                                                    .date,
                                                                row.code,
                                                            )}
                                                        >
                                                            {row.code}{" "}
                                                            {row.name}
                                                        </a>
                                                    </td>
                                                    <td className="ss-gain">
                                                        {percentage(
                                                            (row.growth
                                                                ?.sizingGainPct ??
                                                                0) / 100,
                                                        )}
                                                        <small className="ss-muted">
                                                            <br />
                                                            {row.growth
                                                                ?.basis ===
                                                            "annualized"
                                                                ? "年化報酬"
                                                                : "實際漲幅"}
                                                        </small>
                                                    </td>
                                                    <td>{row.start}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                            </div>
                        </div>
                    </>
                )}
            </section>
            <div className="ss-grid">
                <section className="ss-card">
                    <h2>策略狀態</h2>
                    {!strategies.data ? (
                        <StudioState {...strategies} />
                    ) : (
                        <>
                            <div className="ss-kpis">
                                <div className="ss-kpi">
                                    <span>研究中</span>
                                    <strong>{research}</strong>
                                </div>
                                <div className="ss-kpi">
                                    <span>已採用</span>
                                    <strong>{adopted}</strong>
                                </div>
                                <div className="ss-kpi">
                                    <span>已淘汰</span>
                                    <strong>{failed}</strong>
                                </div>
                            </div>
                            <p className="ss-muted">
                                {adopted
                                    ? "採用狀態以使用者確認紀錄為準。"
                                    : "目前沒有已確認採用的策略；研究通過開發篩選與採用分開記錄。"}
                            </p>
                            {runs.slice(0, 2).map((run) => (
                                <p key={run.id}>
                                    <a
                                        href={`#strategy/${encodeURIComponent(run.id)}`}
                                    >
                                        {strategyTitle(run)}
                                    </a>
                                    <br />
                                    <small className="ss-muted">
                                        {run.name}
                                        <br />
                                        {money(run.initialCapital)} →{" "}
                                        {money(run.finalEquity)}，{run.from}—
                                        {run.through}
                                    </small>
                                </p>
                            ))}
                            <a className="ss-button" href="#strategies">
                                看策略細節 →
                            </a>
                        </>
                    )}
                </section>
                <section className="ss-card">
                    <h2>最近研究</h2>
                    {!history.data ? (
                        <StudioState {...history} />
                    ) : recent.length ? (
                        <>
                            <p className="ss-small ss-muted">
                                研究摘要用於閱讀，未確認的白話摘要與原文證據列在各篇展開內容。
                            </p>
                            {recent.map((item) => (
                                <article key={item.id}>
                                    <small className="ss-muted">
                                        {item.date}
                                    </small>
                                    <h3 style={{ marginTop: 3 }}>
                                        {item.title}
                                    </h3>
                                    <ResearchMarkdown
                                        text={historyConclusion(item)}
                                        preview
                                    />
                                    <details>
                                        <summary>
                                            查看原文摘要與核對狀態
                                        </summary>
                                        {item.summarySource ===
                                            "presentation-metadata" &&
                                            !item.reviewConfirmed && (
                                                <p className="ss-small ss-muted">
                                                    白話摘要待研究端核對
                                                </p>
                                            )}
                                        <ResearchMarkdown
                                            text={
                                                item.originalSummary ||
                                                item.conclusion
                                            }
                                        />
                                    </details>
                                </article>
                            ))}
                            <a className="ss-button" href="#history">
                                完整研究歷程 →
                            </a>
                        </>
                    ) : (
                        <p className="ss-muted">沒有可讀取的研究摘要。</p>
                    )}
                </section>
            </div>
        </div>
    );
}
