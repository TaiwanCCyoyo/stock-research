import { useEffect, useRef } from "react";
import {
    CandlestickSeries,
    ColorType,
    HistogramSeries,
    LineSeries,
    createChart,
    createSeriesMarkers,
    type IChartApi,
    type UTCTimestamp,
} from "lightweight-charts";
import {
    candleRows,
    featureRows,
    numeric,
    validPrice,
    type SharedSeries,
} from "./model";

const colors = [
    "#d9822b",
    "#b59b2b",
    "#9775cf",
    "#448fbe",
    "#7c9d4b",
    "#ad8970",
];
export function SharedChart({
    series,
    requestedAt,
    ma,
    bb,
    pivots,
    oscillator,
    range,
    theme,
    onCursor,
}: {
    series: SharedSeries;
    ma: number[];
    bb: boolean;
    pivots: number[];
    oscillator: string;
    requestedAt: number;
    range: number;
    theme: string;
    onCursor: (index: number) => void;
}) {
    const host = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);
    const measuredRequest = useRef<number | null>(null);
    useEffect(() => {
        if (!host.current) return;
        const css = getComputedStyle(host.current);
        const color = (name: string) => css.getPropertyValue(name).trim();
        const gain = color("--gain"),
            loss = color("--loss");
        const chart = createChart(host.current, {
            autoSize: true,
            height: 560,
            layout: {
                background: {
                    type: ColorType.Solid,
                    color: color("--surface"),
                },
                textColor: color("--muted"),
                attributionLogo: false,
            },
            grid: {
                vertLines: { color: color("--line") },
                horzLines: { color: color("--line") },
            },
            rightPriceScale: { borderColor: color("--line") },
            timeScale: { borderColor: color("--line") },
            localization: { locale: "zh-TW" },
        });
        chartRef.current = chart;
        // Convert the daily calendar once, rather than letting each setData
        // parse the same ISO dates again for every price/indicator series.
        // UTC midnight preserves the daily axis; API dates remain unchanged.
        const times = series.dates.map(
            (date) => (Date.parse(`${date}T00:00:00Z`) / 1000) as UTCTimestamp,
        );
        const dateIndex = new Map(series.dates.map((date, i) => [date, i]));
        const timeIndex = new Map(times.map((time, i) => [time, i]));
        const indicatorRows = (key: string) =>
            featureRows(series, key).map((row, i) => ({
                ...row,
                time: times[i],
            }));
        const candles = chart.addSeries(CandlestickSeries, {
            upColor: gain,
            downColor: loss,
            borderUpColor: gain,
            borderDownColor: loss,
            wickUpColor: gain,
            wickDownColor: loss,
        });
        candles.setData(
            candleRows(series).map((row, i) => ({ ...row, time: times[i] })),
        );
        const reference = series.basis === "reference_factor_adjusted";
        if (reference) {
            ma.forEach((n) => {
                chart
                    .addSeries(LineSeries, {
                        color: colors[[5, 10, 20, 60, 120, 240].indexOf(n)],
                        lineWidth: 1,
                        priceLineVisible: false,
                        lastValueVisible: false,
                        title: `MA${n}`,
                    })
                    .setData(indicatorRows(`SMA${n}`));
            });
            if (bb)
                ["BB20_Upper", "BB20_Middle", "BB20_Lower"].forEach((key) => {
                    chart
                        .addSeries(LineSeries, {
                            color: "#72a99c",
                            lineWidth: 1,
                            priceLineVisible: false,
                            lastValueVisible: false,
                        })
                        .setData(indicatorRows(key));
                });
            const dateSet = new Set(
                series.dates.filter((_, i) => validPrice(series, i)),
            );
            const marks = series.pivots
                .filter(
                    (p) => pivots.includes(p.k) && dateSet.has(p.extreme_date),
                )
                .sort((a, b) => a.extreme_date.localeCompare(b.extreme_date));
            createSeriesMarkers(
                candles,
                marks.map((p) => ({
                    time: times[dateIndex.get(p.extreme_date)!],
                    position:
                        p.kind === "high"
                            ? ("aboveBar" as const)
                            : ("belowBar" as const),
                    color: p.kind === "high" ? gain : loss,
                    shape:
                        p.kind === "high"
                            ? ("arrowDown" as const)
                            : ("arrowUp" as const),
                    size: 0.6,
                })),
            );
        }
        chart
            .addSeries(
                HistogramSeries,
                { priceFormat: { type: "volume" }, priceLineVisible: false },
                1,
            )
            .setData(
                times.map((time, i) =>
                    validPrice(series, i) && numeric(series.volume[i])
                        ? {
                              time,
                              value: series.volume[i]!,
                              color:
                                  series.close[i]! >= series.open[i]!
                                      ? gain
                                      : loss,
                          }
                        : { time },
                ),
            );
        if (reference && oscillator !== "none") {
            chart
                .addSeries(
                    LineSeries,
                    {
                        color: "#a991d1",
                        lineWidth: 1,
                        priceLineVisible: false,
                        title: oscillator,
                    },
                    2,
                )
                .setData(indicatorRows(oscillator));
        }
        chart
            .panes()
            .forEach((pane, i) => pane.setStretchFactor(i === 0 ? 5 : 1.4));
        chart.subscribeCrosshairMove((event) => {
            if (event.time) {
                if (typeof event.time === "number") {
                    const index = timeIndex.get(event.time);
                    if (index !== undefined) onCursor(index);
                    return;
                }
                const time =
                    typeof event.time === "string"
                        ? event.time
                        : typeof event.time === "object"
                          ? `${event.time.year}-${String(event.time.month).padStart(2, "0")}-${String(event.time.day).padStart(2, "0")}`
                          : "";
                const index = dateIndex.get(time);
                if (index !== undefined) onCursor(index);
            } else onCursor(series.dates.length - 1);
        });
        return () => {
            chartRef.current = null;
            chart.remove();
        };
    }, [series, ma, bb, pivots, oscillator, theme, onCursor]);
    useEffect(() => {
        if (range === 0) chartRef.current?.timeScale().fitContent();
        else
            chartRef.current?.timeScale().setVisibleLogicalRange({
                from: Math.max(0, series.dates.length - range),
                to: series.dates.length + 2,
            });
        const element = host.current;
        if (!element || measuredRequest.current === requestedAt) return;
        delete element.dataset.loadMs;
        delete element.dataset.code;
        let secondFrame = 0;
        // Covers fetch, React commit, chart data/range setup and a paint opportunity.
        // This is browser instrumentation, not a GPU presentation timestamp.
        const firstFrame = requestAnimationFrame(() => {
            secondFrame = requestAnimationFrame(() => {
                element.dataset.loadMs = (
                    performance.now() - requestedAt
                ).toFixed(2);
                element.dataset.code = series.code;
                measuredRequest.current = requestedAt;
            });
        });
        return () => {
            cancelAnimationFrame(firstFrame);
            cancelAnimationFrame(secondFrame);
        };
    }, [
        range,
        series,
        requestedAt,
        ma,
        bb,
        pivots,
        oscillator,
        theme,
        onCursor,
    ]);
    return (
        <div
            ref={host}
            className="shared-chart"
            role="img"
            aria-label={`${series.code} K 線、成交量與指標；游標數值顯示於圖表上方與側欄`}
        />
    );
}
