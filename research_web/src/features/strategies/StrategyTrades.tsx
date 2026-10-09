import { useMemo, useState } from "react";
import type { StudioRun, StudioTrade } from "../../domain/strategies/types";
import { duration, gainClass, money, percentage } from "./format";
import { selectTrades, type TradeFilter, type TradeSort } from "./model";

export function TradeCard({
    trade,
    onAudit,
    extra,
}: {
    trade: StudioTrade;
    onAudit: (id: string) => void;
    extra?: string;
}) {
    return (
        <button
            className={`ss-trade ${(trade.capture.days ?? 0) > 0 ? "ss-capture" : ""}`}
            onClick={() => onAudit(trade.id)}
        >
            <b>
                {trade.code} {trade.name}
            </b>
            <div className={`ss-big ${gainClass(trade.pnl)}`}>
                {money(trade.pnl)}
            </div>
            <small>
                {trade.openDate} → {trade.closeDate ?? "仍持有"}
            </small>
            <span className={gainClass(trade.return)}>
                {percentage(trade.return)}
            </span>{" "}
            · {duration(trade.days)}
            {!trade.closeDate && <small>含未實現損益</small>}
            {extra && <small className="ss-gold">{extra}</small>}
        </button>
    );
}
export function TradeTable({
    trades,
    onAudit,
}: {
    trades: StudioTrade[];
    onAudit: (id: string) => void;
}) {
    const [filter, setFilter] = useState<TradeFilter>("all"),
        [sort, setSort] = useState<TradeSort>("openDate"),
        [direction, setDirection] = useState<1 | -1>(-1),
        [query, setQuery] = useState("");
    const rows = useMemo(
        () => selectTrades(trades, filter, query, sort, direction),
        [trades, filter, query, sort, direction],
    );
    const columns: [TradeSort, string][] = [
        ["code", "股票"],
        ["openDate", "買進"],
        ["closeDate", "賣出"],
        ["days", "持有"],
        ["cost", "成本"],
        ["pnl", "損益"],
        ["return", "報酬"],
        ["captured", "飆股天數"],
    ];
    return (
        <section className="ss-card">
            <h2>全部交易</h2>
            <p className="ss-muted">
                點股票看日 K 線、成交成本與買賣理由。未結束的交易另外標明。
            </p>
            <div className="ss-head-row">
                <div className="ss-pills">
                    {(
                        [
                            ["all", "全部"],
                            ["gain", "賺錢"],
                            ["loss", "賠錢"],
                            ["captured", "持有時是飆股"],
                            ["open", "仍持有"],
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
                <input
                    className="ss-query"
                    aria-label="搜尋交易股票"
                    placeholder="股票代碼或名稱"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                />
            </div>
            <p className="ss-muted ss-small">
                篩選後 {rows.length}／{trades.length} 筆
            </p>
            <div className="ss-table-wrap">
                <table className="ss-table">
                    <thead>
                        <tr>
                            {columns.map(([id, label]) => (
                                <th
                                    key={id}
                                    aria-sort={
                                        sort === id
                                            ? direction === 1
                                                ? "ascending"
                                                : "descending"
                                            : "none"
                                    }
                                >
                                    <button
                                        onClick={() => {
                                            setSort(id);
                                            setDirection(
                                                sort === id && direction === -1
                                                    ? 1
                                                    : -1,
                                            );
                                        }}
                                    >
                                        {label}
                                        {sort === id
                                            ? direction === 1
                                                ? " ↑"
                                                : " ↓"
                                            : ""}
                                    </button>
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((trade) => (
                            <tr key={trade.id}>
                                <td>
                                    <button
                                        className="ss-text-button"
                                        onClick={() => onAudit(trade.id)}
                                    >
                                        {trade.code} {trade.name}
                                    </button>
                                </td>
                                <td>{trade.openDate}</td>
                                <td>{trade.closeDate ?? "仍持有"}</td>
                                <td>{trade.days} 天</td>
                                <td>{money(trade.cost)}</td>
                                <td className={gainClass(trade.pnl)}>
                                    {money(trade.pnl)}
                                    {!trade.closeDate && (
                                        <small>
                                            <br />
                                            含未實現
                                        </small>
                                    )}
                                </td>
                                <td className={gainClass(trade.return)}>
                                    {percentage(trade.return)}
                                </td>
                                <td>
                                    {trade.capture.days === null ? (
                                        "待核對"
                                    ) : trade.capture.days > 0 ? (
                                        <span className="ss-gold">
                                            {trade.capture.days} 天
                                        </span>
                                    ) : (
                                        "0 天"
                                    )}
                                </td>
                            </tr>
                        ))}
                        {!rows.length && (
                            <tr>
                                <td colSpan={8}>沒有符合条件的交易</td>
                            </tr>
                        )}
                    </tbody>
                </table>
            </div>
        </section>
    );
}
export function HoldingTimeline({
    run,
    onAudit,
}: {
    run: StudioRun;
    onAudit: (id: string) => void;
}) {
    const start = Date.parse(run.from),
        span = Math.max(86400000, Date.parse(run.through) - start);
    return (
        <section className="ss-card">
            <h2>什麼時候持有什麼</h2>
            <p className="ss-muted">
                每條是一筆持有：紅賺、綠賠；金色外框表示已確認持有時在飆股地圖上。點線條就能驗算。
            </p>
            <div className="ss-head-row ss-small ss-muted">
                <span>{run.from}</span>
                <span>{run.through}</span>
            </div>
            <div
                className="ss-holding-bars"
                style={{ maxHeight: 380, overflowY: "auto", marginTop: 12 }}
            >
                {run.positions.map((trade) => {
                    const left = Math.max(
                            0,
                            ((Date.parse(trade.openDate) - start) / span) * 100,
                        ),
                        right = Math.min(
                            100,
                            ((Date.parse(trade.closeDate ?? run.through) -
                                start) /
                                span) *
                                100,
                        );
                    return (
                        <div className="ss-holding-bar" key={trade.id}>
                            <span>
                                {trade.code} {trade.name}
                            </span>
                            <div className="ss-holding-track">
                                <button
                                    aria-label={`${trade.name} ${trade.openDate} 至 ${trade.closeDate ?? "仍持有"}，查看交易`}
                                    title={`${trade.openDate}—${trade.closeDate ?? run.through}`}
                                    style={{
                                        left: `${left}%`,
                                        width: `${Math.max(0.45, right - left)}%`,
                                    }}
                                    data-loss={
                                        trade.pnl !== null && trade.pnl < 0
                                    }
                                    data-captured={
                                        (trade.capture.days ?? 0) > 0
                                    }
                                    onClick={() => onAudit(trade.id)}
                                />
                            </div>
                            <span className={gainClass(trade.return)}>
                                {percentage(trade.return, 0)}
                            </span>
                        </div>
                    );
                })}
            </div>
        </section>
    );
}
