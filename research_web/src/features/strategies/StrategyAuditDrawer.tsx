import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { useStudioAccount, useStudioTrade } from "../../api/strategyStudio";
import { TradeCandles } from "./StrategyCharts";
import {
    fillLabel,
    validCandles,
    tradeMarks,
    tradeCalculation,
} from "./auditModel";
import { gainClass, money, percentage } from "./format";
import { transactionCost, dividendCostNote } from "./fillDisplayModel";
import { StudioState } from "./shared";
import { marketCaptureLink } from "../full-history/navigation.ts";

function Drawer({
    title,
    children,
    onClose,
}: {
    title: string;
    children: ReactNode;
    onClose: () => void;
}) {
    const host = useRef<HTMLElement>(null);
    useEffect(() => {
        const previous =
            document.activeElement instanceof HTMLElement
                ? document.activeElement
                : null;
        host.current?.querySelector<HTMLButtonElement>("button")?.focus();
        const close = (event: KeyboardEvent) => {
            if (event.key === "Escape") {
                event.preventDefault();
                onClose();
            }
            if (event.key !== "Tab") return;
            const targets = [
                ...(host.current?.querySelectorAll<HTMLElement>(
                    'button:not(:disabled),a[href],input,select,summary,[tabindex="0"]',
                ) ?? []),
            ];
            const first = targets[0],
                last = targets.at(-1);
            if (event.shiftKey && document.activeElement === first) {
                event.preventDefault();
                last?.focus();
            } else if (!event.shiftKey && document.activeElement === last) {
                event.preventDefault();
                first?.focus();
            }
        };
        const overflow = document.body.style.overflow;
        document.body.style.overflow = "hidden";
        window.addEventListener("keydown", close);
        return () => {
            window.removeEventListener("keydown", close);
            document.body.style.overflow = overflow;
            previous?.focus();
        };
    }, [onClose]);
    return (
        <>
            <div className="ss-scrim" onClick={onClose} />
            <aside
                className="ss-drawer"
                role="dialog"
                aria-modal="true"
                aria-label={title}
                ref={host}
            >
                <header>
                    <h2>{title}</h2>
                    <button
                        className="ss-close"
                        onClick={onClose}
                        aria-label="關閉明細"
                    >
                        ×
                    </button>
                </header>
                {children}
            </aside>
        </>
    );
}
export function TradeAuditDrawer({
    runId,
    tradeId,
    onClose,
}: {
    runId: string;
    tradeId: string;
    onClose: () => void;
}) {
    const resource = useStudioTrade(runId, tradeId),
        trade = resource.data;
    const buy = trade?.fills.find(
        (fill) => fill.action === "BUY" && fill.entryCandidates?.length,
    );
    const sells = trade?.fills.filter((fill) => fill.action === "SELL") ?? [];
    const calculation = trade ? tradeCalculation(trade) : null;
    return (
        <Drawer
            title={
                trade
                    ? `${trade.code} ${trade.name} · 逐筆驗算`
                    : "逐筆交易驗算"
            }
            onClose={onClose}
        >
            {!trade ? (
                <StudioState {...resource} />
            ) : (
                <>
                    <p className="ss-muted">
                        {trade.openDate} → {trade.closeDate ?? "資料截止仍持有"}{" "}
                        · {trade.days} 天
                    </p>
                    <div className="ss-big">
                        <span className={gainClass(trade.pnl)}>
                            {money(trade.pnl)}
                        </span>{" "}
                        <small>{percentage(trade.return)}</small>
                    </div>
                    {!trade.closeDate && (
                        <p className="ss-warning">
                            這筆仍未結束，包含 {money(trade.unrealizedPnl)}{" "}
                            的未實現損益；不能視為已落袋。
                        </p>
                    )}
                    <TradeCandles
                        candles={validCandles(trade.candles)}
                        marks={tradeMarks(trade)}
                    />
                    {validCandles(trade.candles).length <
                        trade.candles.length && (
                        <p className="ss-muted">
                            部分日期缺少開高低收，未畫出日 K
                            線；請以逐筆明細核對。
                        </p>
                    )}
                    <h3>每筆成交與帳務</h3>
                    <div className="ss-table-wrap">
                        <table className="ss-table">
                            <thead>
                                <tr>
                                    <th>日期／動作</th>
                                    <th>股數</th>
                                    <th>成交價</th>
                                    <th>開盤／收盤</th>
                                    <th>交易手續費</th>
                                    <th>交易稅</th>
                                    <th>其他成交成本</th>
                                    <th>現金進出</th>
                                </tr>
                            </thead>
                            <tbody>
                                {trade.fills.map((fill) => (
                                    <tr key={fill.id}>
                                        <td>
                                            {fill.date}
                                            <br />
                                            {fillLabel(fill)}
                                            {fill.decisionDate && (
                                                <small className="ss-muted">
                                                    <br />
                                                    決定日 {fill.decisionDate}
                                                </small>
                                            )}
                                        </td>
                                        <td>
                                            {fill.quantity?.toLocaleString() ??
                                                "—"}
                                        </td>
                                        <td>{fill.price ?? "—"}</td>
                                        <td>
                                            {fill.dayOpen ?? "—"}／
                                            {fill.dayClose ?? "—"}
                                        </td>
                                        <td>
                                            {transactionCost(
                                                fill.fee,
                                                fill.action,
                                            )}
                                        </td>
                                        <td>
                                            {transactionCost(
                                                fill.tax,
                                                fill.action,
                                            )}
                                        </td>
                                        <td>
                                            {transactionCost(
                                                fill.penalty,
                                                fill.action,
                                            )}
                                        </td>
                                        <td
                                            className={gainClass(fill.cashFlow)}
                                        >
                                            {money(fill.cashFlow, true)}
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    <p className="ss-small ss-muted">
                        現金進出已扣成交成本；公司行動以各自入帳日期列出。
                        {trade.fills.some(
                            (fill) =>
                                fill.action === "DIVIDEND" &&
                                [fill.fee, fill.tax, fill.penalty].some(
                                    (value) => value == null,
                                ),
                        ) && <> {dividendCostNote}</>}
                    </p>
                    <h3>報酬怎麼算</h3>
                    <div className="ss-formula">
                        （賣出收入 ＋ 已入帳股息與退款
                        {trade.closeDate ? "" : " ＋ 期末持股估值"} −
                        買進成本）÷ 買進成本
                        <br />（{money(calculation?.sellIncome, true)} ＋{" "}
                        {money(calculation?.dividends, true)}
                        {trade.closeDate
                            ? ""
                            : ` ＋ ${money(trade.mark, true)}`}{" "}
                        − {money(calculation?.cost, true)}）÷{" "}
                        {money(calculation?.cost, true)}
                        <br />＝{" "}
                        <b className={gainClass(calculation?.return)}>
                            {percentage(calculation?.return, 2)}
                        </b>
                        <br />
                        {calculation?.verified
                            ? "✓ 現金明細加總與保存損益一致"
                            : `尚未核對一致；與保存損益差額 ${money(calculation?.difference, true)}`}
                    </div>
                    <h3>為什麼買</h3>
                    {buy ? (
                        <>
                            <p>
                                {buy.decisionDate ?? "決定日期未保存"}{" "}
                                的進場候選：
                            </p>
                            <div className="ss-candidates">
                                {buy.entryCandidates!.map((candidate) => (
                                    <span
                                        key={candidate.code}
                                        className={
                                            candidate.affordability.includes(
                                                "unaffordable",
                                            )
                                                ? "ss-unaffordable"
                                                : ""
                                        }
                                    >
                                        {candidate.code}
                                        {candidate.code === trade.code
                                            ? ` ${trade.name}`
                                            : ""}{" "}
                                        ·{" "}
                                        {candidate.affordability.includes(
                                            "unaffordable",
                                        )
                                            ? "一張買不起"
                                            : candidate.affordability.includes(
                                                    "affordable",
                                                )
                                              ? "一張買得起"
                                              : "可負擔性未保存"}
                                    </span>
                                ))}
                            </div>
                        </>
                    ) : (
                        <p className="ss-muted">
                            沒有保存這筆的進場候選名單，無法逐筆確認選股順序。
                        </p>
                    )}
                    <h3>為什麼賣</h3>
                    {!sells.length ? (
                        <p>資料截止仍持有，沒有賣出紀錄。</p>
                    ) : sells.every((fill) => fill.dailyRank !== null) ? (
                        sells.map((fill) => (
                            <p key={fill.id}>
                                {fill.decisionDate ?? fill.date} 持股排名第{" "}
                                {fill.dailyRank} 名；{fill.date} 執行賣出。
                            </p>
                        ))
                    ) : (
                        <p className="ss-warning">
                            依規則應退出，但沒有保存當日排名，無法逐筆確認。
                        </p>
                    )}
                    <h3>持有時有沒有在飆股地圖上</h3>
                    <p>
                        {trade.capture.days === null
                            ? "逐日判定尚未完整，無法確認。"
                            : `已核對 ${trade.capture.knownDays} 個持有交易日，其中 ${trade.capture.days} 天在飆股地圖上。`}
                    </p>
                    <a
                        className="ss-button"
                        href={marketCaptureLink(trade.openDate, trade.code)}
                    >
                        回地圖看買進時的市場
                    </a>
                    {trade.missingReasons.length > 0 && (
                        <details>
                            <summary>這筆有哪些核對限制</summary>
                            <ul>
                                {trade.missingReasons.map((reason, index) => (
                                    <li key={index}>{reason}</li>
                                ))}
                            </ul>
                        </details>
                    )}
                </>
            )}
        </Drawer>
    );
}
export function AccountAuditDrawer({
    runId,
    date,
    onClose,
}: {
    runId: string;
    date: string;
    onClose: () => void;
}) {
    const resource = useStudioAccount(runId, date),
        account = resource.data;
    const missing =
        account?.holdings.some((holding) => holding.marketValue === null) ??
        false;
    const marketValue = missing
        ? null
        : (account?.holdings.reduce(
              (sum, holding) => sum + (holding.marketValue ?? 0),
              0,
          ) ?? null);
    return (
        <Drawer title={`${date} · 帳戶驗算`} onClose={onClose}>
            {!account ? (
                <StudioState {...resource} />
            ) : (
                <>
                    <p className="ss-muted">
                        當天收盤後的持股、現金與已認列資產。
                    </p>
                    <div className="ss-table-wrap">
                        <table className="ss-table">
                            <thead>
                                <tr>
                                    <th>股票</th>
                                    <th>股數</th>
                                    <th>估值價格</th>
                                    <th>持股市值</th>
                                    <th>飆股</th>
                                </tr>
                            </thead>
                            <tbody>
                                {account.holdings.map((holding) => (
                                    <tr key={holding.code}>
                                        <td>
                                            {holding.code} {holding.name}
                                            {holding.modeled && (
                                                <small className="ss-muted">
                                                    <br />
                                                    模型估值
                                                </small>
                                            )}
                                        </td>
                                        <td>
                                            {holding.quantity.toLocaleString()}
                                        </td>
                                        <td>{holding.price ?? "未知"}</td>
                                        <td>
                                            {money(holding.marketValue, true)}
                                        </td>
                                        <td>
                                            {holding.onMap === null
                                                ? "待核對"
                                                : holding.onMap
                                                  ? "是"
                                                  : "否"}
                                        </td>
                                    </tr>
                                ))}
                                {!account.holdings.length && (
                                    <tr>
                                        <td colSpan={5}>當天沒有持股</td>
                                    </tr>
                                )}
                            </tbody>
                        </table>
                    </div>
                    <div className="ss-formula">
                        持股市值 {money(marketValue, true)}
                        <br />＋ 現金 {money(account.cash, true)}
                        <br />＋ 其他已認列資產{" "}
                        {money(account.otherAssets, true)}
                        <br />＝ 重建帳戶{" "}
                        <b>{money(account.reconstructedEquity, true)}</b>
                        <hr />
                        研究帳戶紀錄{" "}
                        <b>{money(account.recordedEquity, true)}</b>
                        <br />
                        {account.verified
                            ? "✓ 核對一致"
                            : `差額 ${money(account.difference, true)}`}
                    </div>
                    {account.reasons.length > 0 && (
                        <div className="ss-warning">
                            <strong>核對說明</strong>
                            <ul>
                                {account.reasons.map((reason, index) => (
                                    <li key={index}>{reason}</li>
                                ))}
                            </ul>
                        </div>
                    )}
                    {account.holdings.some(
                        (holding) => holding.modeled || holding.missingReason,
                    ) && (
                        <details>
                            <summary>查看持股估值限制</summary>
                            {account.holdings
                                .filter(
                                    (holding) =>
                                        holding.modeled ||
                                        holding.missingReason,
                                )
                                .map((holding) => (
                                    <p key={holding.code}>
                                        {holding.code} {holding.name}：
                                        {holding.missingReason ??
                                            "研究帳本使用模型價格，不能視為當日實際收盤成交價。"}
                                    </p>
                                ))}
                        </details>
                    )}
                </>
            )}
        </Drawer>
    );
}
