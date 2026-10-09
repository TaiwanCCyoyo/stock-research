import { useEffect, useMemo, useState } from "react";
import { fetchTradeDetail } from "../api/client";
import type { TradeDetail, TradeListRow } from "../api/types";
import {
    actionBadge,
    dateOnly,
    fmtNum,
    stockLabel,
    tdSignClass,
    translateSignal,
} from "../lib/format";

interface TradesViewProps {
    task: string;
    trades: TradeListRow[];
    summaryFile?: string;
    stockNames: Record<string, string>;
}

function DetailRows({ data }: { data: Record<string, unknown> }) {
    const entries = Object.entries(data).filter(
        ([, value]) => value !== null && typeof value !== "object",
    );
    if (entries.length === 0) return <div className="empty-state">無資料</div>;
    return (
        <table className="data-table">
            <tbody>
                {entries.map(([key, value]) => (
                    <tr key={key}>
                        <td style={{ color: "var(--text-muted)" }}>{key}</td>
                        <td>
                            {typeof value === "number"
                                ? fmtNum(value, Number.isInteger(value) ? 0 : 2)
                                : String(value)}
                        </td>
                    </tr>
                ))}
            </tbody>
        </table>
    );
}

export function TradesView({
    task,
    trades,
    summaryFile,
    stockNames,
}: TradesViewProps) {
    const [codeFilter, setCodeFilter] = useState("");
    const [actionFilter, setActionFilter] = useState("");
    const [selectedId, setSelectedId] = useState<string | null>(null);
    const [detail, setDetail] = useState<TradeDetail | null>(null);
    const [detailError, setDetailError] = useState<string | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);

    const codes = useMemo(
        () => [...new Set(trades.map((t) => String(t.code)))],
        [trades],
    );

    const filtered = useMemo(
        () =>
            trades.filter(
                (t) =>
                    (!codeFilter || String(t.code) === codeFilter) &&
                    (!actionFilter || t.action.toUpperCase() === actionFilter),
            ),
        [trades, codeFilter, actionFilter],
    );

    useEffect(() => {
        setSelectedId(null);
        setDetail(null);
    }, [task, summaryFile]);

    useEffect(() => {
        if (!selectedId) return;
        let cancelled = false;
        setDetailLoading(true);
        setDetailError(null);
        fetchTradeDetail(task, selectedId, summaryFile)
            .then((data) => {
                if (!cancelled) setDetail(data);
            })
            .catch((err: Error) => {
                if (!cancelled) setDetailError(err.message);
            })
            .finally(() => {
                if (!cancelled) setDetailLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [task, selectedId, summaryFile]);

    return (
        <div
            style={{
                display: "grid",
                gridTemplateColumns:
                    detail || detailLoading ? "3fr 2fr" : "1fr",
                gap: 16,
                alignItems: "start",
            }}
        >
            <section className="panel">
                <div className="toolbar">
                    <select
                        className="select"
                        value={codeFilter}
                        onChange={(e) => setCodeFilter(e.target.value)}
                        aria-label="篩選股票"
                    >
                        <option value="">全部股票</option>
                        {codes.map((code) => (
                            <option key={code} value={code}>
                                {stockLabel(code, stockNames)}
                            </option>
                        ))}
                    </select>
                    <select
                        className="select"
                        value={actionFilter}
                        onChange={(e) => setActionFilter(e.target.value)}
                        aria-label="篩選動作"
                    >
                        <option value="">全部動作</option>
                        <option value="BUY">買進</option>
                        <option value="SELL">賣出</option>
                    </select>
                    <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                        {filtered.length} 筆
                    </span>
                </div>
                <div className="table-scroll">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>ID</th>
                                <th>日期</th>
                                <th>代號</th>
                                <th>動作</th>
                                <th>價格</th>
                                <th>股數</th>
                                <th>已實現損益</th>
                                <th>累計損益</th>
                                <th>觸發原因</th>
                            </tr>
                        </thead>
                        <tbody>
                            {filtered.map((trade) => (
                                <tr
                                    key={trade.trade_id}
                                    className={`clickable${trade.trade_id === selectedId ? " selected" : ""}`}
                                    onClick={() =>
                                        setSelectedId(trade.trade_id)
                                    }
                                >
                                    <td>{trade.trade_id}</td>
                                    <td>{dateOnly(trade.date)}</td>
                                    <td>
                                        {stockLabel(trade.code, stockNames)}
                                    </td>
                                    <td>
                                        {(() => {
                                            const badge = actionBadge(
                                                trade.action,
                                                trade.is_add_on,
                                            );
                                            return (
                                                <span
                                                    className={`badge ${badge.cls}`}
                                                >
                                                    {badge.label}
                                                </span>
                                            );
                                        })()}
                                    </td>
                                    <td>{fmtNum(trade.price, 2)}</td>
                                    <td>{fmtNum(trade.qty)}</td>
                                    <td
                                        className={tdSignClass(
                                            trade.realized_pnl,
                                        )}
                                    >
                                        {fmtNum(trade.realized_pnl)}
                                    </td>
                                    <td
                                        className={tdSignClass(
                                            trade.cumulative_realized_pnl,
                                        )}
                                    >
                                        {fmtNum(trade.cumulative_realized_pnl)}
                                    </td>
                                    <td
                                        style={{
                                            maxWidth: 260,
                                            overflow: "hidden",
                                            textOverflow: "ellipsis",
                                        }}
                                    >
                                        {translateSignal(trade.signal_reason)}
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
                {filtered.length === 0 && (
                    <div className="empty-state">沒有符合條件的交易</div>
                )}
            </section>

            {(detail || detailLoading || detailError) && (
                <section className="panel">
                    <h3 className="panel-title">
                        交易細節{" "}
                        {detail
                            ? `— ${detail.trade_id} ${stockLabel(detail.trade.code, stockNames)}`
                            : ""}
                    </h3>
                    {detailLoading && (
                        <div className="loading-row">
                            <div className="spinner" />
                            載入中…
                        </div>
                    )}
                    {detailError && (
                        <div className="error-banner">{detailError}</div>
                    )}
                    {detail && !detailLoading && (
                        <>
                            {detail.signal_events.length > 0 && (
                                <>
                                    <h3 className="panel-title">觸發訊號</h3>
                                    {detail.signal_events.map((event, i) => (
                                        <div
                                            key={i}
                                            style={{
                                                fontSize: 13,
                                                marginBottom: 6,
                                            }}
                                        >
                                            <span className="badge event">
                                                {translateSignal(
                                                    String(event.event ?? ""),
                                                )}
                                            </span>{" "}
                                            <span
                                                style={{
                                                    color: "var(--text-secondary)",
                                                }}
                                            >
                                                {translateSignal(
                                                    String(event.reason ?? ""),
                                                )}
                                            </span>
                                        </div>
                                    ))}
                                </>
                            )}
                            <h3
                                className="panel-title"
                                style={{ marginTop: 14 }}
                            >
                                價格情境
                            </h3>
                            <DetailRows data={detail.price_context} />
                            <h3
                                className="panel-title"
                                style={{ marginTop: 14 }}
                            >
                                資金情境
                            </h3>
                            <DetailRows data={detail.cash_context} />
                        </>
                    )}
                </section>
            )}
        </div>
    );
}
