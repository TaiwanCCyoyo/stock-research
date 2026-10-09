import { useCallback, useMemo, useState } from "react";
import { useStudioRun } from "../../api/strategyStudio";
import type { StudioRun } from "../../domain/strategies/types";
import { AccountAuditDrawer, TradeAuditDrawer } from "./StrategyAuditDrawer";
import { LineChart, MonthlyHeatmap } from "./StrategyCharts";
import { StrategyWalkthrough } from "./StrategyWalkthrough";
import { HoldingTimeline, TradeCard, TradeTable } from "./StrategyTrades";
import { StrategyCapture } from "./StrategyCapture";
import { duration, gainClass, money, percentage, ratio } from "./format";
import { Metric, StatusBadge, StudioState } from "./shared";
import { strategyIdea, strategyTitle } from "./presentation";
import { savedReturnDistribution } from "./distributionModel";
import "./strategies.css";

function ProfitDistribution({ run }: { run: StudioRun }) {
    const { buckets, included, excluded, total } = savedReturnDistribution(
        run.positions,
    );
    const max = Math.max(1, ...buckets.map((bucket) => bucket.count));
    return (
        <div>
            <p className="ss-muted ss-small">
                看已結束的交易多數賺或賠多少；0% 表示不賺不賠。 已納入{" "}
                {included}／{total} 筆
                {excluded > 0 && `；另 ${excluded} 筆沒有可用報酬，未納入`}。
            </p>
            <div
                className="ss-distribution"
                role="list"
                aria-label="已結束交易報酬分布"
            >
                {buckets.map((bucket) => (
                    <div
                        className="ss-industry-row"
                        role="listitem"
                        key={bucket.label}
                    >
                        <b>
                            {bucket.label} · {bucket.count} 筆
                        </b>
                        <div className="ss-bar">
                            <span
                                style={{
                                    width: `${(bucket.count / max) * 100}%`,
                                    background:
                                        bucket.tone === "loss"
                                            ? "var(--ss-down)"
                                            : bucket.tone === "gain"
                                              ? "var(--ss-up)"
                                              : "var(--muted)",
                                }}
                            />
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
export function StrategyDetailPage({ runId }: { runId: string }) {
    const resource = useStudioRun(runId),
        run = resource.data;
    const [tradeId, setTradeId] = useState<string | null>(null),
        [accountDate, setAccountDate] = useState<string | null>(null);
    const closeTrade = useCallback(() => setTradeId(null), []),
        closeAccount = useCallback(() => setAccountDate(null), []);
    const closed = useMemo(
        () =>
            (run?.positions ?? [])
                .filter(
                    (trade) =>
                        trade.closeDate !== null && trade.realizedPnl !== null,
                )
                .sort((a, b) => b.realizedPnl! - a.realizedPnl!),
        [run],
    );
    const benchmarkFinal = run?.nav.at(-1)?.benchmarkEquity;
    return (
        <div className="ss-page">
            <a href="#strategies" className="ss-muted">
                ← 策略總覽
            </a>
            {!run ? (
                <StudioState {...resource} />
            ) : (
                <>
                    <div className="ss-head-row">
                        <div>
                            <h1>{strategyTitle(run)}</h1>
                            <small className="ss-muted">{run.name}</small>
                        </div>
                        <StatusBadge run={run} />
                    </div>
                    <p className="ss-muted">{strategyIdea(run)}</p>
                    <div className="ss-warning">
                        <strong>先看清楚</strong>
                        <ul>
                            <li>
                                這是 {run.from} 至 {run.through}{" "}
                                的回測，成交是模擬紀錄。
                            </li>
                            <li>
                                這段期間已被研究看過；回測報酬不代表未來成績。
                            </li>
                            <li>
                                {run.ownerAdopted === true
                                    ? "使用者已確認採用；仍須自行判斷是否適合實際執行。"
                                    : "尚未由使用者確認採用。"}
                                {run.studyStatus === "accepted"
                                    ? " 開發階段篩選通過，與最終採用分開記錄。"
                                    : run.studyStatus === "failed"
                                      ? " 研究結果未通過，保留作為歷史紀錄。"
                                      : " 仍在研究階段。"}
                            </li>
                        </ul>
                        <details>
                            <summary>資料與研究限制</summary>
                            <ul>
                                {run.limitations.map((limitation, index) => (
                                    <li key={index}>{limitation}</li>
                                ))}
                            </ul>
                        </details>
                    </div>
                    <StrategyWalkthrough
                        key={run.id}
                        run={run}
                        onAudit={setTradeId}
                    />
                    <section className="ss-card">
                        <h2>成績</h2>
                        <p className="ss-muted">
                            {run.from}—{run.through}，起始{" "}
                            {money(run.initialCapital)}。
                        </p>
                        <div className="ss-check">
                            {run.reconciliation.verified ? "✓" : "待核對"}{" "}
                            已結束交易損益{" "}
                            {money(run.reconciliation.closedPnl, true)} ＋
                            未結束交易損益{" "}
                            {money(run.reconciliation.openPnl, true)}
                            {(run.reconciliation.otherAssets ?? 0) !== 0
                                ? ` ＋ 其他認列資產 ${money(run.reconciliation.otherAssets, true)}`
                                : ""}{" "}
                            ＝ {money(run.reconciliation.totalPnl, true)}
                            <br />
                            帳戶增加{" "}
                            {money(run.reconciliation.accountIncrease, true)}
                            {!run.reconciliation.verified && (
                                <>
                                    ；差額{" "}
                                    {money(run.reconciliation.difference, true)}
                                </>
                            )}
                        </div>
                        <p className="ss-small ss-muted">
                            未結束交易可能含部分賣出或股息，不能全部視為未實現損益。
                        </p>
                        {!run.reconciliation.verified &&
                            run.reconciliation.reasons.length > 0 && (
                                <p className="ss-muted">
                                    {run.reconciliation.reasons.join("；")}
                                </p>
                            )}
                        <div className="ss-kpis">
                            <Metric
                                label="最後帳戶價值"
                                value={money(run.finalEquity)}
                                note={percentage(run.netReturn)}
                                className={gainClass(run.netReturn)}
                            />
                            <Metric
                                label="同期全買 0050"
                                value={money(benchmarkFinal)}
                                note="股價，不含配息"
                            />
                            <Metric
                                label="最大跌幅"
                                value={percentage(run.maxDrawdown)}
                                className="ss-loss"
                            />
                            <Metric
                                label="交易成本"
                                value={money(run.costs)}
                                note="依保存帳務，已從帳戶扣除"
                            />
                        </div>
                        <LineChart
                            dates={run.nav.map((point) => point.date)}
                            lines={[
                                {
                                    name: "策略帳戶",
                                    color: "var(--accent)",
                                    values: run.nav.map(
                                        (point) => point.equity,
                                    ),
                                },
                                {
                                    name: "0050 股價，不含配息",
                                    color: "var(--ss-bench)",
                                    values: run.nav.map(
                                        (point) => point.benchmarkEquity,
                                    ),
                                },
                            ]}
                            format={money}
                            label="策略帳戶與同期 0050"
                            onPick={setAccountDate}
                        />
                        <h3>從最高點跌下來多少</h3>
                        <LineChart
                            dates={run.nav.map((point) => point.date)}
                            lines={[
                                {
                                    name: "帳戶回落",
                                    color: "var(--ss-down)",
                                    values: run.nav.map(
                                        (point) => point.drawdown,
                                    ),
                                },
                            ]}
                            format={percentage}
                            label="每日帳戶回撤"
                        />
                    </section>
                    <StrategyCapture
                        run={run}
                        onAudit={setTradeId}
                        onAccount={setAccountDate}
                    />
                    <section className="ss-card">
                        <h2>抱著它會是什麼感覺</h2>
                        <p className="ss-muted">
                            報酬是結果，這些才是持有途中要面對的過程。
                        </p>
                        <div className="ss-kpis">
                            <Metric
                                label="最久沒有創新高"
                                value={duration(
                                    run.statistics.longestUnderwater.days,
                                )}
                                note={`${run.statistics.longestUnderwater.from ?? "起點未保存"} → ${run.statistics.longestUnderwater.until ?? "資料截止仍未創高"}`}
                            />
                            <Metric
                                label="最長連續賠錢"
                                value={`${run.statistics.longestLosingStreak.count} 筆`}
                                note={`合計 ${money(run.statistics.longestLosingStreak.pnl)}`}
                                className="ss-loss"
                            />
                        </div>
                        <h3>每個月賺賠</h3>
                        <MonthlyHeatmap
                            months={run.statistics.monthlyReturns}
                        />
                        <p className="ss-muted ss-small">
                            紅賺綠賠，顏色越深幅度越大；空白月份沒有保存資料。
                        </p>
                    </section>
                    <section className="ss-card">
                        <h2>錢是怎麼賺來的</h2>
                        <div className="ss-kpis">
                            <Metric
                                label="賺錢交易比例"
                                value={ratio(run.statistics.winRate)}
                                note={`${run.closedTradeCount} 筆已結束交易`}
                            />
                            <Metric
                                label="賺錢時平均賺"
                                value={money(run.statistics.meanGain)}
                                className="ss-gain"
                            />
                            <Metric
                                label="賠錢時平均賠"
                                value={money(run.statistics.meanLoss)}
                                className="ss-loss"
                            />
                            <Metric
                                label="最賺 5 筆占賺錢交易總額"
                                value={ratio(run.statistics.topFiveProfitShare)}
                                note="分母：已結束且賺錢交易的獲利加總"
                            />
                        </div>
                        <ProfitDistribution run={run} />
                        <div className="ss-grid">
                            <div>
                                <h3>最賺的幾筆</h3>
                                <div className="ss-trade-grid">
                                    {closed.slice(0, 5).map((trade) => (
                                        <TradeCard
                                            trade={trade}
                                            key={trade.id}
                                            onAudit={setTradeId}
                                        />
                                    ))}
                                </div>
                            </div>
                            <div>
                                <h3>最賠的幾筆</h3>
                                <div className="ss-trade-grid">
                                    {closed
                                        .slice(-5)
                                        .reverse()
                                        .map((trade) => (
                                            <TradeCard
                                                trade={trade}
                                                key={trade.id}
                                                onAudit={setTradeId}
                                            />
                                        ))}
                                </div>
                            </div>
                        </div>
                    </section>
                    <HoldingTimeline run={run} onAudit={setTradeId} />
                    <TradeTable trades={run.positions} onAudit={setTradeId} />
                    <section className="ss-card">
                        <h2>研究結論</h2>
                        <p>{run.method.conclusion}</p>
                        <p className="ss-muted">
                            這是保存研究的結論；開發期通過、最終驗證與使用者採用分開記錄。
                        </p>
                    </section>
                </>
            )}
            {tradeId && (
                <TradeAuditDrawer
                    runId={runId}
                    tradeId={tradeId}
                    onClose={closeTrade}
                />
            )}{" "}
            {accountDate && (
                <AccountAuditDrawer
                    runId={runId}
                    date={accountDate}
                    onClose={closeAccount}
                />
            )}
        </div>
    );
}
