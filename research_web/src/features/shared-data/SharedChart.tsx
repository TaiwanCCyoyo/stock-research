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
import { sharesLabel } from "./overlays";
import {
    candleRows,
    featureRows,
    numeric,
    formatNumber,
    formatFeature,
    featureLabels,
    validPrice,
    type SharedSeries,
} from "./model";

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
    institutional = null,
}: {
    /** Stored net shares per chart date; drawn in its own pane when present. */
    institutional?: { date: string; value: number | null }[] | null;
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
            layout: {
                background: {
                    type: ColorType.Solid,
                    color: color("--surface"),
                },
                textColor: color("--muted"),
                fontFamily: 'Inter, "Noto Sans TC", sans-serif',
                attributionLogo: false,
                panes: {
                    separatorColor: color("--line"),
                    separatorHoverColor: color("--shared-crosshair"),
                },
            },
            grid: {
                vertLines: { visible: false },
                horzLines: { color: color("--line") },
            },
            crosshair: {
                vertLine: {
                    color: color("--shared-crosshair"),
                    labelBackgroundColor: color("--chip"),
                },
                horzLine: {
                    color: color("--shared-crosshair"),
                    labelBackgroundColor: color("--chip"),
                },
            },
            rightPriceScale: { borderVisible: false },
            timeScale: { borderVisible: false },
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
                        color: color(`--shared-ma${n}`),
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
                            color: color("--shared-bb"),
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
                {
                    priceFormat: {
                        type: "custom",
                        minMove: 1,
                        formatter: (value: number) => formatNumber(value, 0),
                    },
                    priceLineVisible: false,
                },
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
            const options = {
                priceLineVisible: false,
                title: featureLabels[oscillator] ?? oscillator,
                priceFormat: {
                    type: "custom" as const,
                    minMove: oscillator === "atr14_pct" ? 0.0001 : 0.01,
                    formatter: (value: number) =>
                        formatFeature(oscillator, value),
                },
            };
            if (oscillator === "MACDHist") {
                chart.addSeries(HistogramSeries, options, 2).setData(
                    indicatorRows(oscillator).map((row) =>
                        "value" in row
                            ? {
                                  ...row,
                                  color: row.value! >= 0 ? gain : loss,
                              }
                            : row,
                    ),
                );
            } else {
                chart
                    .addSeries(
                        LineSeries,
                        {
                            ...options,
                            color: color("--shared-osc"),
                            lineWidth: 1,
                        },
                        2,
                    )
                    .setData(indicatorRows(oscillator));
            }
        }
        if (institutional) {
            const pane = chart.panes().length;
            chart
                .addSeries(
                    HistogramSeries,
                    {
                        priceLineVisible: false,
                        title: "法人買賣超",
                        priceFormat: {
                            type: "custom",
                            minMove: 1,
                            formatter: (value: number) => sharesLabel(value),
                        },
                    },
                    pane,
                )
                .setData(
                    institutional.map((point) => {
                        const time = times[dateIndex.get(point.date)!];
                        return point.value === null
                            ? { time }
                            : {
                                  time,
                                  value: point.value,
                                  color: point.value >= 0 ? gain : loss,
                              };
                    }),
                );
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
    }, [series, ma, bb, pivots, oscillator, theme, onCursor, institutional]);
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
        // The chart is rebuilt when the overlay changes; reapply the range.
        institutional,
    ]);
    return (
        <div
            ref={host}
            className={`shared-chart${institutional ? " has-overlay" : ""}`}
            role="img"
            aria-label={`${series.code} K 線、成交量與指標；游標數值顯示於圖表上方與側欄`}
        />
    );
}
