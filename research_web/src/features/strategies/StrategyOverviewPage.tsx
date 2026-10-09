import { useState } from "react";
import { useStudioIndex } from "../../api/strategyStudio";
import { LineChart } from "./StrategyCharts";
import { duration, gainClass, money, percentage } from "./format";
import { filterStrategies, type StrategyStatus } from "./model";
import { StatusBadge, StudioState } from "./shared";
import { strategyIdea, strategyTitle } from "./presentation";
import { capturedTradeLabel, capturedTradeNote } from "./captureModel";
import "./strategies.css";

export function StrategyOverviewPage() {
    const resource = useStudioIndex(),
        [filter, setFilter] = useState<StrategyStatus | "all">("all");
    const runs = filterStrategies(resource.data?.runs ?? [], filter);
    return (
        <div className="ss-page">
            {resource.data?.synthetic && (
                <p className="ss-muted">
                    合成示範：帳戶、價格與交易均為虛構，不代表真實研究結果。
                </p>
            )}
            <div className="ss-head-row">
                <div>
                    <h1>策略總覽</h1>
                    <p className="ss-muted">
                        研究過的做法、成果與代價。點進一張卡，逐筆確認它怎麼買賣。
                    </p>
                </div>
                <a className="ss-button" href="#compare">
                    比較策略 →
                </a>
            </div>
            <div className="ss-pills" role="group" aria-label="策略研究狀態">
                {(
                    [
                        ["all", "全部"],
                        ["research", "研究中"],
                        ["adopted", "已採用"],
                        ["failed", "已淘汰"],
                    ] as const
                ).map(([id, label]) => (
                    <button
                        className="ss-chip"
                        key={id}
                        aria-pressed={filter === id}
                        onClick={() => setFilter(id)}
                    >
                        {label}
                    </button>
                ))}
            </div>
            {!resource.data ? (
                <StudioState {...resource} />
            ) : !runs.length ? (
                <StudioState {...resource} empty />
            ) : (
                <div className="ss-card-grid">
                    {runs.map((run) => (
                        <a
                            className="ss-card ss-card-link"
                            href={`#strategy/${encodeURIComponent(run.id)}`}
                            key={run.id}
                        >
                            <div className="ss-head-row">
                                <div>
                                    <h2>{strategyTitle(run)}</h2>
                                    <small className="ss-muted">
                                        {run.name}
                                    </small>
                                </div>
                                <StatusBadge run={run} />
                            </div>
                            <p className="ss-muted">{strategyIdea(run)}</p>
                            <LineChart
                                dates={run.nav.map((point) => point.date)}
                                lines={[
                                    {
                                        name: "策略",
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
                                compact
                                label={`${strategyTitle(run)} 帳戶與 0050 比較`}
                            />
                            <div className="ss-muted">
                                {money(run.initialCapital)} →{" "}
                                <strong
                                    className={`ss-big ${gainClass(run.netReturn)}`}
                                >
                                    {money(run.finalEquity)}
                                </strong>
                            </div>
                            <p className="ss-muted ss-small">
                                {run.from}—{run.through} · 同期 0050
                                股價，不含配息
                            </p>
                            <div className="ss-stat-list">
                                <div>
                                    <small>最大跌幅</small>
                                    <strong className="ss-loss">
                                        {percentage(run.maxDrawdown)}
                                    </strong>
                                </div>
                                <div>
                                    <small>最久沒創新高</small>
                                    <strong>
                                        {duration(run.longestUnderwater.days)}
                                    </strong>
                                </div>
                                <div>
                                    <small>持有時是飆股</small>
                                    <strong>{capturedTradeLabel(run)}</strong>
                                    <small>{capturedTradeNote(run)}</small>
                                </div>
                            </div>
                        </a>
                    ))}
                </div>
            )}
            <p className="ss-muted ss-small">
                開發篩選通過與「已採用」分開記錄；只有使用者確認採用，才會列在已採用。
            </p>
        </div>
    );
}
