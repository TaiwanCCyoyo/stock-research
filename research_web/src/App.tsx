import { useCallback, useEffect, useState } from "react";
import {
    fetchDataQuality,
    fetchTaskBundle,
    fetchTasks,
    fetchTrades,
    sendHeartbeat,
} from "./api/client";
import type {
    CapitalMode,
    DataQualityResponse,
    HealthRows,
    Summary,
    TaskBundle,
    TaskIndexRow,
    TradeListRow,
} from "./api/types";
import { ClosedState } from "./components/ClosedState";
import { ComparisonView } from "./components/ComparisonView";
import { DataQuality } from "./components/DataQuality";
import { DiagnosisView } from "./components/DiagnosisView";
import { HelpView } from "./components/HelpView";
import { MetricChips } from "./components/MetricChips";
import { RankingTable } from "./components/RankingTable";
import { ShutdownControl } from "./components/ShutdownControl";
import { Sidebar } from "./components/Sidebar";
import { StrategyHealth } from "./components/StrategyHealth";
import { TradesView } from "./components/TradesView";
import { Workbench } from "./components/Workbench";
import { dateOnly } from "./lib/format";
import { MODE_LABELS, modeSummaryFile } from "./lib/capitalModes";

// Sent to POST /heartbeat on this interval; the launcher's monitor treats the
// browser tab as closed once heartbeats stop arriving for HEARTBEAT_GRACE_SECONDS
// (research_api/main.py), which is well above this interval to tolerate jitter.
const HEARTBEAT_INTERVAL_MS = 5000;

type TabKey =
    "workbench" | "trades" | "ranking" | "comparison" | "diagnosis" | "help";

function summaryForMode(bundle: TaskBundle, mode: CapitalMode | null): Summary {
    return mode
        ? (bundle.mode_summaries[mode] ?? bundle.summary)
        : bundle.summary;
}

function healthForMode(
    bundle: TaskBundle,
    mode: CapitalMode | null,
): HealthRows {
    return mode ? (bundle.mode_health?.[mode] ?? bundle.health) : bundle.health;
}

const TABS: { key: TabKey; label: string }[] = [
    { key: "workbench", label: "K 線工作台" },
    { key: "trades", label: "交易明細" },
    { key: "ranking", label: "個股排名" },
    { key: "comparison", label: "資金池比較" },
    { key: "diagnosis", label: "策略診斷" },
    { key: "help", label: "使用說明" },
];

export default function App() {
    const [tasks, setTasks] = useState<TaskIndexRow[]>([]);
    const [selectedTask, setSelectedTask] = useState<string | null>(null);
    const [bundle, setBundle] = useState<TaskBundle | null>(null);
    const [trades, setTrades] = useState<TradeListRow[]>([]);
    const [tab, setTab] = useState<TabKey>("workbench");
    const [loading, setLoading] = useState(false);
    const [tradesLoading, setTradesLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [capitalMode, setCapitalMode] = useState<CapitalMode | null>(null);
    const [closed, setClosed] = useState(false);
    const [dataQuality, setDataQuality] = useState<DataQualityResponse | null>(
        null,
    );

    // Tells the server this tab is still open; the launcher auto-shuts-down once
    // heartbeats stop (e.g. the tab was closed). Runs independently of any loaded
    // task, and stops once the user has explicitly shut the dashboard down.
    useEffect(() => {
        if (closed) return;
        sendHeartbeat();
        const timer = setInterval(sendHeartbeat, HEARTBEAT_INTERVAL_MS);
        return () => clearInterval(timer);
    }, [closed]);

    useEffect(() => {
        fetchTasks()
            .then((response) => {
                setTasks(response.tasks);
                if (response.tasks.length > 0)
                    setSelectedTask(response.tasks[0].task);
            })
            .catch((err: Error) =>
                setError(`任務清單載入失敗：${err.message}`),
            );
    }, []);

    // Data quality is a global view over the local price archive, independent of the
    // selected task; fetched once so a slow/missing report never blocks task loading.
    useEffect(() => {
        fetchDataQuality()
            .then(setDataQuality)
            .catch(() => setDataQuality(null));
    }, []);

    const loadTask = useCallback((taskId: string) => {
        setLoading(true);
        setError(null);
        setCapitalMode(null);
        Promise.all([
            fetchTaskBundle(taskId),
            fetchTrades(taskId, { limit: 2000 }),
        ])
            .then(([bundleData, tradesData]) => {
                setBundle(bundleData);
                setTrades(tradesData.trades);
            })
            .catch((err: Error) => setError(`任務載入失敗：${err.message}`))
            .finally(() => setLoading(false));
    }, []);

    const changeMode = useCallback(
        (next: CapitalMode | null) => {
            if (!selectedTask) return;
            setCapitalMode(next);
            setTradesLoading(true);
            setError(null);
            fetchTrades(selectedTask, {
                limit: 2000,
                summaryFile: next ? modeSummaryFile(next) : undefined,
            })
                .then((tradesData) => setTrades(tradesData.trades))
                .catch((err: Error) =>
                    setError(`資金模式切換失敗：${err.message}`),
                )
                .finally(() => setTradesLoading(false));
        },
        [selectedTask],
    );

    useEffect(() => {
        if (selectedTask) loadTask(selectedTask);
    }, [selectedTask, loadTask]);

    const run = bundle?.summary.run;

    if (closed) return <ClosedState />;

    return (
        <div className="app-shell">
            <ShutdownControl onShutdown={() => setClosed(true)} />
            <Sidebar
                tasks={tasks}
                selected={selectedTask}
                onSelect={setSelectedTask}
            />
            <main className="main">
                {bundle && (
                    <>
                        <div className="topbar">
                            <h1 title={bundle.task}>{bundle.title}</h1>
                            {run && (
                                <span className="topbar-sub num">
                                    {dateOnly(run.start)} ～ {dateOnly(run.end)}{" "}
                                    · 股票池 {run.codes?.length ?? 0} 檔
                                    {run.capital_mode
                                        ? ` · ${MODE_LABELS[run.capital_mode] ?? run.capital_mode}`
                                        : ""}
                                    {run.universe
                                        ? ` · 股票池：${run.universe}`
                                        : ""}
                                </span>
                            )}
                            {Object.keys(bundle.mode_summaries ?? {}).length >
                                0 && (
                                <div className="mode-switch">
                                    <span className="mode-switch-label">
                                        資金模式
                                    </span>
                                    {(
                                        Object.keys(
                                            bundle.mode_summaries,
                                        ) as CapitalMode[]
                                    ).map((mode) => (
                                        <button
                                            key={mode}
                                            type="button"
                                            className={`chip-toggle${(capitalMode ?? run?.capital_mode) === mode ? " on" : ""}`}
                                            onClick={() =>
                                                changeMode(
                                                    mode === run?.capital_mode
                                                        ? null
                                                        : mode,
                                                )
                                            }
                                        >
                                            {MODE_LABELS[mode]}
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                        <MetricChips
                            summary={summaryForMode(bundle, capitalMode)}
                        />
                        <div className="tab-strip">
                            {TABS.map((item) => (
                                <button
                                    key={item.key}
                                    type="button"
                                    className={`tab${tab === item.key ? " active" : ""}`}
                                    onClick={() => setTab(item.key)}
                                >
                                    {item.label}
                                </button>
                            ))}
                        </div>
                    </>
                )}
                <div className="content">
                    {error && <div className="error-banner">{error}</div>}
                    {loading && (
                        <div className="loading-row">
                            <div className="spinner" />
                            任務載入中…
                        </div>
                    )}
                    {!bundle && !loading && !error && (
                        <div className="empty-state">選擇左側任務開始研究</div>
                    )}
                    {bundle && !loading && (
                        <>
                            {tradesLoading && (
                                <div className="loading-row">
                                    <div className="spinner" />
                                    資金模式切換中…
                                </div>
                            )}
                            {!tradesLoading &&
                                capitalMode &&
                                trades.length === 0 &&
                                (tab === "workbench" || tab === "trades") && (
                                    <div className="empty-state">
                                        此資金模式下沒有任何成交
                                        {typeof summaryForMode(
                                            bundle,
                                            capitalMode,
                                        ).metrics?.cash_blocked_entry_count ===
                                        "number"
                                            ? ` — 資金不足擋單 ${summaryForMode(bundle, capitalMode).metrics?.cash_blocked_entry_count} 筆`
                                            : ""}
                                    </div>
                                )}
                            {!tradesLoading &&
                                !(capitalMode && trades.length === 0) &&
                                tab === "workbench" && (
                                    <>
                                        <DataQuality data={dataQuality} />
                                        <div style={{ height: 16 }} />
                                        <StrategyHealth
                                            health={healthForMode(
                                                bundle,
                                                capitalMode,
                                            )}
                                        />
                                        <div style={{ height: 16 }} />
                                        <Workbench
                                            bundle={bundle}
                                            trades={trades}
                                        />
                                    </>
                                )}
                            {!tradesLoading &&
                                !(capitalMode && trades.length === 0) &&
                                tab === "trades" && (
                                    <TradesView
                                        task={bundle.task}
                                        trades={trades}
                                        summaryFile={
                                            capitalMode
                                                ? modeSummaryFile(capitalMode)
                                                : undefined
                                        }
                                        stockNames={bundle.stock_names}
                                    />
                                )}
                            {tab === "ranking" && (
                                <RankingTable bundle={bundle} />
                            )}
                            {tab === "comparison" && (
                                <ComparisonView bundle={bundle} />
                            )}
                            {tab === "diagnosis" &&
                                (bundle.diagnosis ? (
                                    <DiagnosisView
                                        markdown={bundle.diagnosis}
                                    />
                                ) : (
                                    <div className="empty-state">
                                        此任務沒有策略診斷（可用
                                        /diagnose-strategy 產生）
                                    </div>
                                ))}
                            {tab === "help" && <HelpView />}
                        </>
                    )}
                </div>
            </main>
        </div>
    );
}
