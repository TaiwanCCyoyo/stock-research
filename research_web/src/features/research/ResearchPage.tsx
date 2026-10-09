import { useEffect, useMemo, useRef, useState } from "react";
import {
    fetchTaskBundle,
    fetchTasks,
    fetchTradeDetail,
    fetchTrades,
} from "../../api/client";
import type {
    TaskBundle,
    TaskIndexRow,
    TradeDetail,
    TradeListRow,
} from "../../api/types";
import "./ResearchPage.css";

const message = (error: unknown) =>
    error instanceof Error ? error.message : "發生未預期錯誤";
const show = (value: unknown) => JSON.stringify(value, null, 2);
const actionLabel = (action: string) =>
    ({ BUY: "買進", SELL: "賣出", DIVIDEND: "股利" })[action.toUpperCase()] ??
    action;
const numberText = (value: number | null | undefined, suffix = "") =>
    value == null
        ? "未知"
        : `${value.toLocaleString("zh-TW", { maximumFractionDigits: 2 })}${suffix}`;

function EquityCurve({
    points,
}: {
    points: { date: string; equity: number }[] | undefined;
}) {
    if (!points?.length)
        return <p className="rs-muted">研究產物未提供權益曲線。</p>;
    const values = points.map((point) => point.equity);
    const low = Math.min(...values);
    const high = Math.max(...values);
    const span = high - low || 1;
    const path = points
        .map(
            (point, index) =>
                `${index ? "L" : "M"}${(index / Math.max(points.length - 1, 1)) * 100},${100 - ((point.equity - low) / span) * 100}`,
        )
        .join(" ");
    return (
        <figure className="rs-curve">
            <svg
                viewBox="0 0 100 100"
                preserveAspectRatio="none"
                role="img"
                aria-label={`權益曲線，${points[0].date} 至 ${points.at(-1)?.date}`}
            >
                <path d={path} />
            </svg>
            <figcaption>
                <span>{points[0].date}</span>
                <span>TWD {numberText(high)}</span>
                <span>{points.at(-1)?.date}</span>
            </figcaption>
        </figure>
    );
}

export function ResearchPage() {
    const [tasks, setTasks] = useState<TaskIndexRow[]>([]);
    const [taskId, setTaskId] = useState("");
    const [bundle, setBundle] = useState<TaskBundle | null>(null);
    const [trades, setTrades] = useState<TradeListRow[]>([]);
    const [selectedTrade, setSelectedTrade] = useState<TradeListRow | null>(
        null,
    );
    const [detail, setDetail] = useState<TradeDetail | null>(null);
    const [loading, setLoading] = useState<"tasks" | "task" | "detail" | null>(
        null,
    );
    const [error, setError] = useState<string | null>(null);
    const [detailError, setDetailError] = useState<string | null>(null);
    const [codeQuery, setCodeQuery] = useState("");
    const [dateQuery, setDateQuery] = useState("");
    const [page, setPage] = useState(0);
    const taskSequence = useRef(0);
    const detailSequence = useRef(0);
    const filteredTrades = useMemo(
        () =>
            trades.filter(
                (trade) =>
                    trade.code.includes(codeQuery) &&
                    trade.date.includes(dateQuery),
            ),
        [trades, codeQuery, dateQuery],
    );
    const pageTrades = filteredTrades.slice(page * 20, page * 20 + 20);
    const pageCount = Math.max(1, Math.ceil(filteredTrades.length / 20));

    useEffect(() => {
        setPage(0);
    }, [codeQuery, dateQuery, trades]);
    useEffect(() => {
        if (!selectedTrade) return;
        const close = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                ++detailSequence.current;
                setSelectedTrade(null);
                setDetail(null);
                setDetailError(null);
                setLoading(null);
            }
        };
        window.addEventListener("keydown", close);
        return () => window.removeEventListener("keydown", close);
    }, [selectedTrade]);

    async function loadTasks() {
        setLoading("tasks");
        setError(null);
        try {
            const data = await fetchTasks();
            setTasks(data.tasks);
            if (!taskId && data.tasks[0]) setTaskId(data.tasks[0].task);
        } catch (error) {
            setError(`任務清單載入失敗：${message(error)}`);
        } finally {
            setLoading(null);
        }
    }
    async function loadTask() {
        if (!taskId) return;
        const id = ++taskSequence.current;
        ++detailSequence.current;
        setLoading("task");
        setError(null);
        setDetail(null);
        setSelectedTrade(null);
        setBundle(null);
        setTrades([]);
        try {
            const [nextBundle, nextTrades] = await Promise.all([
                fetchTaskBundle(taskId),
                fetchTrades(taskId, { limit: 2000 }),
            ]);
            if (id === taskSequence.current) {
                setBundle(nextBundle);
                setTrades(nextTrades.trades);
            }
        } catch (error) {
            if (id === taskSequence.current)
                setError(`研究任務載入失敗：${message(error)}`);
        } finally {
            if (id === taskSequence.current) setLoading(null);
        }
    }
    async function loadDetail(trade: TradeListRow) {
        if (!bundle) return;
        const id = ++detailSequence.current;
        setSelectedTrade(trade);
        setDetail(null);
        setDetailError(null);
        setLoading("detail");
        try {
            const data = await fetchTradeDetail(bundle.task, trade.trade_id);
            if (id === detailSequence.current) setDetail(data);
        } catch (error) {
            if (id === detailSequence.current)
                setDetailError(`原始證據載入失敗：${message(error)}`);
        } finally {
            if (id === detailSequence.current) setLoading(null);
        }
    }
    return (
        <section className="rs-page">
            <header className="rs-hero">
                <p>RESEARCH STUDIO</p>
                <h1>研究工作台</h1>
                <span>
                    明確選擇已保存的研究任務後，才讀取規則、結果與交易證據。
                </span>
            </header>
            <section className="rs-card rs-loader">
                <div>
                    <p>STEP 01</p>
                    <h2>載入已保存任務</h2>
                    <span>
                        讀取相容 API 已保存的任務；尚未串接其他 worktree
                        的研究。
                    </span>
                </div>
                <div className="rs-controls">
                    <button
                        className="rs-primary"
                        type="button"
                        onClick={loadTasks}
                        disabled={loading !== null}
                    >
                        {loading === "tasks" ? "讀取清單中…" : "取得任務清單"}
                    </button>
                    {tasks.length > 0 && (
                        <>
                            <label htmlFor="rs-task">任務</label>
                            <select
                                id="rs-task"
                                value={taskId}
                                onChange={(event) =>
                                    setTaskId(event.target.value)
                                }
                            >
                                {tasks.map((task) => (
                                    <option key={task.task} value={task.task}>
                                        {task.title || task.task}
                                    </option>
                                ))}
                            </select>
                            <button
                                type="button"
                                onClick={loadTask}
                                disabled={!taskId || loading !== null}
                            >
                                {loading === "task"
                                    ? "載入中…"
                                    : "載入選定任務"}
                            </button>
                        </>
                    )}
                </div>
            </section>
            {error && (
                <div className="rs-error" role="alert">
                    {error}
                    <button
                        type="button"
                        onClick={tasks.length ? loadTask : loadTasks}
                    >
                        重試
                    </button>
                </div>
            )}
            {!bundle && loading !== "task" && !error && (
                <section className="rs-empty">
                    <h2>尚未載入研究</h2>
                    <span>先取得任務清單，再明確載入選定項目。</span>
                </section>
            )}
            {loading === "task" && (
                <p className="rs-status" aria-live="polite">
                    正在讀取研究產物…
                </p>
            )}
            {bundle && loading !== "task" && (
                <div className="rs-layout">
                    <section className="rs-card rs-summary">
                        <div>
                            <p>已載入研究</p>
                            <h2 title={bundle.title}>
                                {bundle.title || bundle.task}
                            </h2>
                            <span>任務識別：{bundle.task}</span>
                        </div>
                        <dl>
                            {bundle.summary.run?.start && (
                                <>
                                    <dt>研究起點</dt>
                                    <dd>{bundle.summary.run.start}</dd>
                                </>
                            )}
                            {bundle.summary.run?.end && (
                                <>
                                    <dt>研究終點</dt>
                                    <dd>{bundle.summary.run.end}</dd>
                                </>
                            )}
                            {bundle.summary.run?.codes && (
                                <>
                                    <dt>標的數</dt>
                                    <dd>{bundle.summary.run.codes.length}</dd>
                                </>
                            )}
                        </dl>
                        {bundle.summary.warnings?.length ? (
                            <aside>
                                <strong>資料限制</strong>
                                <ul>
                                    {bundle.summary.warnings.map((warning) => (
                                        <li key={warning}>{warning}</li>
                                    ))}
                                </ul>
                            </aside>
                        ) : null}
                    </section>
                    <section className="rs-card">
                        <p>規則與結果</p>
                        <h2>
                            {bundle.summary.strategy?.name || "未提供策略名稱"}
                        </h2>
                        <div className="rs-metrics">
                            <div>
                                <span>總損益</span>
                                <strong>
                                    {numberText(
                                        bundle.summary.metrics?.total_pnl,
                                        " TWD",
                                    )}
                                </strong>
                            </div>
                            <div>
                                <span>報酬率</span>
                                <strong>
                                    {numberText(
                                        bundle.summary.metrics?.return_rate,
                                        "%",
                                    )}
                                </strong>
                            </div>
                            <div>
                                <span>最大回撤</span>
                                <strong>
                                    {numberText(
                                        bundle.summary.metrics
                                            ?.max_drawdown_rate,
                                        "%",
                                    )}
                                </strong>
                            </div>
                            <div>
                                <span>交易次數</span>
                                <strong>
                                    {numberText(
                                        bundle.summary.metrics?.trade_count,
                                    )}
                                </strong>
                            </div>
                        </div>
                        <h3>權益曲線</h3>
                        <EquityCurve
                            points={bundle.summary.portfolio?.equity_curve}
                        />
                        <details>
                            <summary>策略參數與原始摘要</summary>
                            <p>
                                參數不是完整規則；未寫入研究產物的入場、出場或資料處理規則不會由本頁補推。
                            </p>
                            <table className="rs-param-table">
                                <tbody>
                                    {Object.entries(
                                        bundle.summary.strategy?.params ?? {},
                                    ).map(([key, value]) => (
                                        <tr key={key}>
                                            <th>{key}</th>
                                            <td>{show(value)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                            <pre>{show(bundle.summary.metrics ?? {})}</pre>
                        </details>
                        {bundle.diagnosis && (
                            <details>
                                <summary>研究診斷</summary>
                                <p>{bundle.diagnosis}</p>
                            </details>
                        )}
                    </section>
                    <section className="rs-card">
                        <div className="rs-heading">
                            <div>
                                <p>可追溯交易</p>
                                <h2>交易列表</h2>
                            </div>
                            <span>{filteredTrades.length} 筆符合</span>
                        </div>
                        {trades.length ? (
                            <>
                                <div className="rs-filters">
                                    <label>
                                        代號
                                        <input
                                            value={codeQuery}
                                            onChange={(event) =>
                                                setCodeQuery(event.target.value)
                                            }
                                            placeholder="例如 2330"
                                        />
                                    </label>
                                    <label>
                                        日期
                                        <input
                                            value={dateQuery}
                                            onChange={(event) =>
                                                setDateQuery(event.target.value)
                                            }
                                            placeholder="YYYY-MM-DD"
                                        />
                                    </label>
                                </div>
                                <div className="rs-table">
                                    <table>
                                        <thead>
                                            <tr>
                                                <th>日期</th>
                                                <th>代號</th>
                                                <th>動作</th>
                                                <th>價格</th>
                                                <th>數量</th>
                                                <th>訊號原因</th>
                                                <th>證據</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {pageTrades.map((trade) => (
                                                <tr key={trade.trade_id}>
                                                    <td>{trade.date}</td>
                                                    <td>{trade.code}</td>
                                                    <td>
                                                        {actionLabel(
                                                            trade.action,
                                                        )}{" "}
                                                        <small>
                                                            ({trade.action})
                                                        </small>
                                                    </td>
                                                    <td>{trade.price}</td>
                                                    <td>{trade.qty}</td>
                                                    <td
                                                        className="rs-cut"
                                                        title={
                                                            trade.signal_reason ??
                                                            ""
                                                        }
                                                    >
                                                        {trade.signal_reason ||
                                                            "未提供"}
                                                    </td>
                                                    <td>
                                                        <button
                                                            className="rs-link"
                                                            type="button"
                                                            onClick={() =>
                                                                loadDetail(
                                                                    trade,
                                                                )
                                                            }
                                                            disabled={
                                                                loading ===
                                                                "detail"
                                                            }
                                                        >
                                                            查看原始證據
                                                        </button>
                                                    </td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                </div>
                                <div className="rs-pager">
                                    <button
                                        type="button"
                                        onClick={() =>
                                            setPage((value) => value - 1)
                                        }
                                        disabled={page === 0}
                                    >
                                        上一頁
                                    </button>
                                    <span>
                                        {page + 1} / {pageCount}
                                    </span>
                                    <button
                                        type="button"
                                        onClick={() =>
                                            setPage((value) => value + 1)
                                        }
                                        disabled={page + 1 >= pageCount}
                                    >
                                        下一頁
                                    </button>
                                </div>
                            </>
                        ) : (
                            <span>這個研究任務沒有可顯示的成交紀錄。</span>
                        )}
                        {trades.length === 2000 && (
                            <p className="rs-limit">
                                為避免過量載入，畫面最多顯示 2,000
                                筆交易；完整數量請以研究產物為準。
                            </p>
                        )}
                    </section>
                    {selectedTrade && (
                        <aside
                            className="rs-drawer"
                            role="region"
                            aria-label="交易原始證據"
                        >
                            <div className="rs-drawer-head">
                                <div>
                                    <p>原始證據</p>
                                    <h2>{selectedTrade.trade_id}</h2>
                                    <span>
                                        {selectedTrade.date} ·{" "}
                                        {selectedTrade.code} ·{" "}
                                        {selectedTrade.qty} 股 ·{" "}
                                        {selectedTrade.price}
                                    </span>
                                </div>
                                <button
                                    type="button"
                                    aria-label="關閉原始證據"
                                    onClick={() => {
                                        ++detailSequence.current;
                                        setSelectedTrade(null);
                                        setDetail(null);
                                        setDetailError(null);
                                        setLoading(null);
                                    }}
                                >
                                    關閉
                                </button>
                            </div>
                            <h3>已保存的成交記錄</h3>
                            <dl className="price-facts">
                                <div>
                                    <dt>動作</dt>
                                    <dd>{actionLabel(selectedTrade.action)}</dd>
                                </div>
                                <div>
                                    <dt>成交價格</dt>
                                    <dd>
                                        {numberText(selectedTrade.price, " 元")}
                                    </dd>
                                </div>
                                <div>
                                    <dt>數量</dt>
                                    <dd>
                                        {numberText(selectedTrade.qty, " 股")}
                                    </dd>
                                </div>
                                <div>
                                    <dt>記錄總額</dt>
                                    <dd>
                                        {numberText(selectedTrade.total, " 元")}
                                    </dd>
                                </div>
                                <div>
                                    <dt>訊號原因</dt>
                                    <dd>
                                        {selectedTrade.signal_reason ??
                                            "原產物未記錄"}
                                    </dd>
                                </div>
                            </dl>
                            {loading === "detail" && (
                                <span aria-live="polite">讀取中…</span>
                            )}
                            {detailError && (
                                <div className="rs-error" role="alert">
                                    <div>
                                        延伸行情證據暫不可用；上方保留原成交記錄，未以其他行情代替。
                                        <details>
                                            <summary>查看原因</summary>
                                            {detailError}
                                        </details>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={() =>
                                            loadDetail(selectedTrade)
                                        }
                                    >
                                        重試
                                    </button>
                                </div>
                            )}
                            {detail && loading !== "detail" && (
                                <details open>
                                    <summary>
                                        完整 API 證據（含資料來源欄位）
                                    </summary>
                                    <pre>{show(detail)}</pre>
                                </details>
                            )}
                        </aside>
                    )}
                </div>
            )}
        </section>
    );
}
