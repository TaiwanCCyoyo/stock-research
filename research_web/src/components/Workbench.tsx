import { useEffect, useMemo, useState } from "react";
import { fetchPrices } from "../api/client";
import type {
    CorporateActionMarker,
    PriceRow,
    TaskBundle,
    TradeListRow,
} from "../api/types";
import { stockLabel } from "../lib/format";
import { MA_COLORS } from "../lib/palette";
import { CandleChart } from "./CandleChart";

const MA_CHOICES = [5, 10, 20, 60];

interface WorkbenchProps {
    bundle: TaskBundle;
    trades: TradeListRow[];
}

/** Symbols worth charting: traded codes first, then the rest of the task's pool. */
function symbolChoices(bundle: TaskBundle, trades: TradeListRow[]): string[] {
    const traded = [...new Set(trades.map((t) => String(t.code)))];
    const pool = (bundle.summary.run?.codes ?? []).map(String);
    return [...traded, ...pool.filter((code) => !traded.includes(code))];
}

export function Workbench({ bundle, trades }: WorkbenchProps) {
    const symbols = useMemo(
        () => symbolChoices(bundle, trades),
        [bundle, trades],
    );
    const [symbol, setSymbol] = useState<string>(symbols[0] ?? "");
    const [maWindows, setMaWindows] = useState<number[]>([5, 10, 20]);
    const [showTrades, setShowTrades] = useState(true);
    const [showEvents, setShowEvents] = useState(true);
    const [showVolume, setShowVolume] = useState(true);
    const [rows, setRows] = useState<PriceRow[]>([]);
    const [events, setEvents] = useState<CorporateActionMarker[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Reset symbol when switching task.
    useEffect(() => {
        setSymbol(symbols[0] ?? "");
    }, [symbols]);

    useEffect(() => {
        if (!symbol) {
            setRows([]);
            setEvents([]);
            return;
        }
        let cancelled = false;
        setLoading(true);
        setError(null);
        fetchPrices(bundle.task, [symbol])
            .then((response) => {
                if (cancelled) return;
                setRows(response.prices[symbol] ?? []);
                setEvents(response.corporate_actions[symbol] ?? []);
            })
            .catch((err: Error) => {
                if (!cancelled) setError(err.message);
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [bundle.task, symbol]);

    const symbolTrades = useMemo(
        () => trades.filter((t) => String(t.code) === symbol),
        [trades, symbol],
    );

    function toggleMa(window: number) {
        setMaWindows((current) =>
            current.includes(window)
                ? current.filter((w) => w !== window)
                : [...current, window].sort((a, b) => a - b),
        );
    }

    return (
        <section className="panel">
            <div className="toolbar">
                <select
                    className="select"
                    value={symbol}
                    onChange={(e) => setSymbol(e.target.value)}
                    aria-label="選擇股票"
                >
                    {symbols.map((code) => (
                        <option key={code} value={code}>
                            {stockLabel(code, bundle.stock_names)}
                        </option>
                    ))}
                </select>
                {MA_CHOICES.map((window) => (
                    <button
                        key={window}
                        type="button"
                        className={`chip-toggle${maWindows.includes(window) ? " on" : ""}`}
                        onClick={() => toggleMa(window)}
                    >
                        MA{window}
                    </button>
                ))}
                <button
                    type="button"
                    className={`chip-toggle${showTrades ? " on" : ""}`}
                    onClick={() => setShowTrades((v) => !v)}
                >
                    買賣標記
                </button>
                <button
                    type="button"
                    className={`chip-toggle${showEvents ? " on" : ""}`}
                    onClick={() => setShowEvents((v) => !v)}
                >
                    除權息
                </button>
                <button
                    type="button"
                    className={`chip-toggle${showVolume ? " on" : ""}`}
                    onClick={() => setShowVolume((v) => !v)}
                >
                    成交量
                </button>
            </div>
            {error && <div className="error-banner">價格載入失敗：{error}</div>}
            <div className="chart-host">
                {rows.length > 0 && (
                    <CandleChart
                        rows={rows}
                        maWindows={maWindows}
                        trades={symbolTrades}
                        corporateActions={events}
                        showTrades={showTrades}
                        showEvents={showEvents}
                        showVolume={showVolume}
                        focusFrom={bundle.summary.run?.start}
                    />
                )}
                {rows.length === 0 && !loading && (
                    <div className="empty-state">此標的沒有價格資料</div>
                )}
                {loading && (
                    <div className="chart-overlay">
                        <div className="spinner" />
                    </div>
                )}
            </div>
            <div className="legend">
                {maWindows.map((window) => (
                    <span key={window}>
                        <span
                            className="legend-swatch"
                            style={{
                                background: MA_COLORS[window] ?? "#9aa7b6",
                            }}
                        />
                        MA{window}
                    </span>
                ))}
                {showTrades && (
                    <>
                        <span>
                            <span
                                className="legend-swatch"
                                style={{ background: "#53b1fd" }}
                            />
                            買進
                        </span>
                        <span>
                            <span
                                className="legend-swatch"
                                style={{ background: "#ffb547" }}
                            />
                            賣出
                        </span>
                    </>
                )}
                {showEvents && (
                    <span>
                        <span
                            className="legend-swatch"
                            style={{ background: "#a78bfa" }}
                        />
                        除權息事件
                    </span>
                )}
            </div>
        </section>
    );
}
