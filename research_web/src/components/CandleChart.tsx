import { useEffect, useMemo, useRef } from "react";
import {
    CandlestickSeries,
    ColorType,
    createChart,
    createSeriesMarkers,
    CrosshairMode,
    HistogramSeries,
    LineSeries,
    type IChartApi,
    type ISeriesApi,
    type ISeriesMarkersPluginApi,
    type SeriesMarker,
    type Time,
} from "lightweight-charts";
import type {
    CorporateActionMarker,
    PriceRow,
    TradeListRow,
} from "../api/types";
import { movingAverage } from "../lib/indicators";
import { BUY, DOWN, EVENT, MA_COLORS, SELL, UP } from "../lib/palette";

interface CandleChartProps {
    rows: PriceRow[];
    maWindows: number[];
    trades: TradeListRow[];
    corporateActions: CorporateActionMarker[];
    showTrades: boolean;
    showEvents: boolean;
    showVolume: boolean;
    /** Initial visible window start (task run start); full history stays scrollable. */
    focusFrom?: string;
}

function buildMarkers(props: CandleChartProps): SeriesMarker<Time>[] {
    const { rows, trades, corporateActions, showTrades, showEvents } = props;
    const dates = new Set(rows.map((row) => row.Date.slice(0, 10)));
    const markers: SeriesMarker<Time>[] = [];

    if (showTrades) {
        for (const trade of trades) {
            const day = trade.date.slice(0, 10);
            if (!dates.has(day)) continue;
            const action = trade.action.toUpperCase();
            // Only actual entries/exits get arrows; dividends/splits are covered by
            // the corporate-action dots so they don't read as trades.
            if (action !== "BUY" && action !== "SELL") continue;
            const isBuy = action === "BUY";
            markers.push({
                time: day as Time,
                position: isBuy ? "belowBar" : "aboveBar",
                shape: isBuy ? "arrowUp" : "arrowDown",
                color: isBuy ? BUY : SELL,
                text: isBuy ? "買" : "賣",
            });
        }
    }
    if (showEvents) {
        for (const event of corporateActions) {
            if (!dates.has(event.date)) continue;
            markers.push({
                time: event.date as Time,
                position: "aboveBar",
                shape: "circle",
                color: EVENT,
                size: 0.4,
            });
        }
    }
    markers.sort((a, b) => String(a.time).localeCompare(String(b.time)));
    return markers;
}

export function CandleChart(props: CandleChartProps) {
    const { rows, maWindows, showVolume, focusFrom } = props;
    const hostRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
    const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
    const maRefs = useRef<Map<number, ISeriesApi<"Line">>>(new Map());
    const markersRef = useRef<ISeriesMarkersPluginApi<Time> | null>(null);

    const markers = useMemo(() => buildMarkers(props), [props]);

    // Create the chart once.
    useEffect(() => {
        const host = hostRef.current;
        if (!host) return;
        const chart = createChart(host, {
            autoSize: true,
            layout: {
                background: { type: ColorType.Solid, color: "transparent" },
                textColor: "#9aa7b6",
                fontFamily: "'Inter', 'Segoe UI', 'Noto Sans TC', sans-serif",
                fontSize: 12,
                attributionLogo: false,
            },
            grid: {
                vertLines: { color: "rgba(148, 163, 184, 0.07)" },
                horzLines: { color: "rgba(148, 163, 184, 0.07)" },
            },
            rightPriceScale: { borderColor: "rgba(148, 163, 184, 0.18)" },
            timeScale: { borderColor: "rgba(148, 163, 184, 0.18)" },
            crosshair: {
                mode: CrosshairMode.Normal,
                vertLine: {
                    color: "rgba(83, 177, 253, 0.4)",
                    labelBackgroundColor: "#1f2a3a",
                },
                horzLine: {
                    color: "rgba(83, 177, 253, 0.4)",
                    labelBackgroundColor: "#1f2a3a",
                },
            },
            localization: { locale: "zh-TW" },
        });
        const candles = chart.addSeries(CandlestickSeries, {
            upColor: UP,
            downColor: DOWN,
            borderUpColor: UP,
            borderDownColor: DOWN,
            wickUpColor: UP,
            wickDownColor: DOWN,
        });
        chartRef.current = chart;
        candleRef.current = candles;
        markersRef.current = createSeriesMarkers(candles, []);
        const maSeries = maRefs.current;
        return () => {
            chart.remove();
            chartRef.current = null;
            candleRef.current = null;
            volumeRef.current = null;
            markersRef.current = null;
            maSeries.clear();
        };
    }, []);

    // Candle + volume data.
    useEffect(() => {
        const chart = chartRef.current;
        const candles = candleRef.current;
        if (!chart || !candles) return;
        candles.setData(
            rows.map((row) => ({
                time: row.Date.slice(0, 10) as Time,
                open: row.Open,
                high: row.High,
                low: row.Low,
                close: row.Close,
            })),
        );

        if (showVolume && !volumeRef.current) {
            const volume = chart.addSeries(HistogramSeries, {
                priceFormat: { type: "volume" },
                priceScaleId: "volume",
                lastValueVisible: false,
                priceLineVisible: false,
            });
            chart
                .priceScale("volume")
                .applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
            volumeRef.current = volume;
        }
        if (!showVolume && volumeRef.current) {
            chart.removeSeries(volumeRef.current);
            volumeRef.current = null;
        }
        volumeRef.current?.setData(
            rows.map((row, i) => ({
                time: row.Date.slice(0, 10) as Time,
                value: Number(row.Volume ?? 0),
                color:
                    row.Close >= (i > 0 ? rows[i - 1].Close : row.Open)
                        ? "rgba(244, 82, 95, 0.35)"
                        : "rgba(43, 191, 138, 0.35)",
            })),
        );
        const lastDate =
            rows.length > 0 ? rows[rows.length - 1].Date.slice(0, 10) : null;
        if (focusFrom && lastDate && focusFrom < lastDate) {
            // Pad the left edge so markers on the first run day are not clipped.
            const padded = new Date(`${focusFrom}T00:00:00`);
            padded.setDate(padded.getDate() - 14);
            const from = padded.toISOString().slice(0, 10);
            chart
                .timeScale()
                .setVisibleRange({ from: from as Time, to: lastDate as Time });
        } else {
            chart.timeScale().fitContent();
        }
    }, [rows, showVolume, focusFrom]);

    // Moving-average overlays.
    useEffect(() => {
        const chart = chartRef.current;
        if (!chart) return;
        const active = new Set(maWindows);
        for (const [window, series] of maRefs.current) {
            if (!active.has(window)) {
                chart.removeSeries(series);
                maRefs.current.delete(window);
            }
        }
        for (const window of maWindows) {
            let series = maRefs.current.get(window);
            if (!series) {
                series = chart.addSeries(LineSeries, {
                    color: MA_COLORS[window] ?? "#9aa7b6",
                    lineWidth: 1,
                    priceLineVisible: false,
                    lastValueVisible: false,
                    crosshairMarkerVisible: false,
                });
                maRefs.current.set(window, series);
            }
            series.setData(
                movingAverage(rows, window).map((p) => ({
                    time: p.time as Time,
                    value: p.value,
                })),
            );
        }
    }, [rows, maWindows]);

    // Trade / corporate-action markers.
    useEffect(() => {
        markersRef.current?.setMarkers(markers);
    }, [markers]);

    return <div ref={hostRef} className="chart-host" />;
}
