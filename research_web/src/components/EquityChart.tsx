import { useEffect, useRef } from "react";
import {
    AreaSeries,
    ColorType,
    createChart,
    LineSeries,
    type IChartApi,
    type Time,
} from "lightweight-charts";
import type { EquityPoint } from "../api/types";

interface EquityChartProps {
    curve: EquityPoint[];
    height?: number;
}

/** Equity area with running-max drawdown (%) on a separate left scale. */
export function EquityChart({ curve, height = 260 }: EquityChartProps) {
    const hostRef = useRef<HTMLDivElement>(null);
    const chartRef = useRef<IChartApi | null>(null);

    useEffect(() => {
        const host = hostRef.current;
        if (!host) return;
        const chart = createChart(host, {
            autoSize: true,
            layout: {
                background: { type: ColorType.Solid, color: "transparent" },
                textColor: "#9aa7b6",
                fontFamily: "'Inter', 'Segoe UI', 'Noto Sans TC', sans-serif",
                fontSize: 11,
                attributionLogo: false,
            },
            grid: {
                vertLines: { color: "rgba(148, 163, 184, 0.06)" },
                horzLines: { color: "rgba(148, 163, 184, 0.06)" },
            },
            rightPriceScale: { borderColor: "rgba(148, 163, 184, 0.18)" },
            leftPriceScale: {
                visible: true,
                borderColor: "rgba(148, 163, 184, 0.18)",
            },
            timeScale: { borderColor: "rgba(148, 163, 184, 0.18)" },
            localization: { locale: "zh-TW" },
        });
        chartRef.current = chart;

        const equity = chart.addSeries(AreaSeries, {
            lineColor: "#53b1fd",
            topColor: "rgba(83, 177, 253, 0.25)",
            bottomColor: "rgba(83, 177, 253, 0.02)",
            lineWidth: 2,
            priceLineVisible: false,
        });
        const drawdown = chart.addSeries(LineSeries, {
            color: "rgba(244, 82, 95, 0.8)",
            lineWidth: 1,
            priceScaleId: "left",
            priceLineVisible: false,
            lastValueVisible: false,
            priceFormat: {
                type: "custom",
                formatter: (v: number) => `${v.toFixed(1)}%`,
            },
        });

        let runningMax = -Infinity;
        const equityData: { time: Time; value: number }[] = [];
        const drawdownData: { time: Time; value: number }[] = [];
        for (const point of curve) {
            const day = point.date.slice(0, 10) as Time;
            runningMax = Math.max(runningMax, point.equity);
            equityData.push({ time: day, value: point.equity });
            drawdownData.push({
                time: day,
                value:
                    runningMax > 0
                        ? ((point.equity - runningMax) / runningMax) * 100
                        : 0,
            });
        }
        equity.setData(equityData);
        drawdown.setData(drawdownData);
        chart.timeScale().fitContent();

        return () => {
            chart.remove();
            chartRef.current = null;
        };
    }, [curve]);

    return (
        <div>
            <div ref={hostRef} style={{ width: "100%", height }} />
            <div className="legend">
                <span>
                    <span
                        className="legend-swatch"
                        style={{ background: "#53b1fd" }}
                    />
                    淨值
                </span>
                <span>
                    <span
                        className="legend-swatch"
                        style={{ background: "rgba(244, 82, 95, 0.8)" }}
                    />
                    回撤 %（左軸）
                </span>
            </div>
        </div>
    );
}
