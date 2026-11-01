import { useEffect, useMemo, useState } from "react";
import { readStrategyStudio, useStudioIndex } from "../../api/strategyStudio";
import {
    studioExposurePath,
    studioRunPath,
    studioSelectionIdentity,
    studioSelectionIds,
} from "../../api/strategyPaths";
import type { StudioExposure, StudioRun } from "../../domain/strategies/types";
import { LineChart } from "./StrategyCharts";
import { alignComparisons, periodMetrics } from "./model";
import { duration, gainClass, percentage, ratio } from "./format";
import { sharedExposureCoverage } from "./captureModel";
import { strategyTitle } from "./presentation";
import { StudioState } from "./shared";
import { SourceNotice } from "../../components/SourceNotice";
import "./strategies.css";

const colors = [
    "var(--accent)",
    "var(--ss-up)",
    "var(--positive)",
    "var(--ss-down)",
];
export function StrategyComparePage() {
    const resource = useStudioIndex(),
        [selected, setSelected] = useState<string[] | null>(null),
        [runs, setRuns] = useState<StudioRun[]>([]),
        [exposures, setExposures] = useState<StudioExposure[]>([]),
        [detailError, setDetailError] = useState(""),
        [exposureError, setExposureError] = useState(""),
        [detailAttempt, setDetailAttempt] = useState(0);
    const allRuns = resource.data?.runs ?? [];
    const ids =
        selected === null
            ? allRuns.slice(0, 2).map((run) => run.id)
            : selected.filter((id) => allRuns.some((run) => run.id === id));
    const identity = studioSelectionIdentity(ids),
        captureState = resource.data?.captureState;
    useEffect(() => {
        if (!identity) return;
        const controller = new AbortController();
        setDetailError("");
        setExposureError("");
        setRuns([]);
        setExposures([]);
        const runIds = studioSelectionIds(identity);
        void Promise.allSettled(
            runIds.map((id) =>
                readStrategyStudio<StudioRun>(
                    studioRunPath(id),
                    controller.signal,
                ),
            ),
        ).then((results) => {
            if (controller.signal.aborted) return;
            setRuns(
                results.flatMap((result) =>
                    result.status === "fulfilled" ? [result.value] : [],
                ),
            );
            if (results.some((result) => result.status === "rejected"))
                setDetailError(
                    "部分策略帳戶明細無法讀取；僅採用已成功讀取的策略。",
                );
        });
        void Promise.allSettled(
            runIds.map((id) =>
                readStrategyStudio<StudioExposure>(
                    studioExposurePath(id),
                    controller.signal,
                ),
            ),
        ).then((results) => {
            if (controller.signal.aborted) return;
            setExposures(
                results.flatMap((result) =>
                    result.status === "fulfilled" ? [result.value] : [],
                ),
            );
            if (results.some((result) => result.status === "rejected"))
                setExposureError(
                    "部分持股配置明細無法讀取；缺少的配置維持未知，不當成零。",
                );
        });
        return () => controller.abort();
    }, [identity, captureState, detailAttempt]);
    const aligned = useMemo(() => alignComparisons(runs), [runs]);
    const from = aligned.dates[0],
        through = aligned.dates.at(-1);
    const allocationCoverage = sharedExposureCoverage(
        aligned.dates,
        aligned.series.map((series) =>
            exposures.find((value) => value.runId === series.id),
        ),
    );
    const metrics = aligned.series.map((series, index) => {
        const run = runs.find((value) => value.id === series.id)!;
        const closed = run.positions.filter(
            (trade) =>
                trade.closeDate !== null &&
                trade.realizedPnl !== null &&
                trade.closeDate >= from &&
                trade.closeDate <= through!,
        );
        return {
            run,
            performance: periodMetrics(series.points),
            winRate: closed.length
                ? closed.filter((trade) => trade.realizedPnl! > 0).length /
                  closed.length
                : null,
            count: closed.length,
            avgWeight: allocationCoverage.averageWeights[index],
        };
    });
    const benchmarkPoints = aligned.dates.flatMap((date, index) =>
        aligned.benchmark[index] === null
            ? []
            : [{ date, equity: aligned.benchmark[index]! }],
    );
    const benchmark =
        benchmarkPoints.length === aligned.dates.length
            ? periodMetrics(benchmarkPoints)
            : null;
    return (
        <div className="ss-page u-page u-wide">
            {resource.data && <SourceNotice source={resource.data.source} />}
            <h1>策略比較</h1>
            <p className="ss-muted">
                選 2～4 個策略，在相同日期上看報酬、回落與飆股資金比例。
            </p>
            {!resource.data ? (
                <StudioState {...resource} />
            ) : (
                <>
                    <div
                        className="ss-pills"
                        role="group"
                        aria-label="比較策略選擇"
                    >
                        {allRuns.map((run) => (
                            <button
                                className="ss-chip u-chip"
                                key={run.id}
                                aria-pressed={ids.includes(run.id)}
                                disabled={
                                    !ids.includes(run.id) && ids.length >= 4
                                }
                                onClick={() =>
                                    setSelected(
                                        ids.includes(run.id)
                                            ? ids.filter((id) => id !== run.id)
                                            : [...ids, run.id],
                                    )
                                }
                            >
                                {strategyTitle(run)}
                                {run.plainTitle && (
                                    <small className="ss-muted">
                                        <br />
                                        {run.plainTitle}
                                    </small>
                                )}
                            </button>
                        ))}
                    </div>
                    {(detailError || exposureError) && ids.length >= 2 && (
                        <div className="ss-warning u-notice" role="alert">
                            {detailError && <p>{detailError}</p>}
                            {exposureError && <p>{exposureError}</p>}
                            <button
                                className="ss-button u-btn"
                                onClick={() =>
                                    setDetailAttempt((value) => value + 1)
                                }
                            >
                                重新讀取所選策略
                            </button>
                        </div>
                    )}
                    {ids.length < 2 ? (
                        <p className="ss-warning u-notice">
                            請至少選 2 個策略。
                        </p>
                    ) : runs.length < 2 ? (
                        <div className="ss-loading" role="status">
                            {detailError
                                ? "成功讀取的策略不足兩個，暫時無法比較。"
                                : "正在讀取策略的原始帳戶與交易…"}
                        </div>
                    ) : !aligned.dates.length ? (
                        <p className="ss-warning u-notice">
                            這些策略沒有共同保存日期，不能疊在一起比較。
                        </p>
                    ) : (
                        <section className="ss-card u-card">
                            <h2>
                                共同期間：{from}—{through}
                            </h2>
                            <p className="ss-muted">
                                {aligned.dates.length}{" "}
                                個共同保存日；第一天各自設為
                                100，讓本金不同的策略也能比較。0050
                                只比較股價，不含配息。
                            </p>
                            <LineChart
                                dates={aligned.dates}
                                lines={[
                                    ...aligned.series.map((series, index) => ({
                                        name: strategyTitle(
                                            runs.find(
                                                (run) => run.id === series.id,
                                            )!,
                                        ),
                                        color: colors[index],
                                        dash:
                                            index >= 2
                                                ? index === 2
                                                    ? "8 4"
                                                    : "2 4"
                                                : undefined,
                                        values: series.values,
                                    })),
                                    {
                                        name: "0050 股價，不含配息",
                                        color: "var(--ss-bench)",
                                        values: aligned.benchmark,
                                    },
                                ]}
                                label="共同期間策略與 0050 表現"
                                format={(value) => value.toFixed(1)}
                            />
                            <div className="ss-table-wrap">
                                <table className="ss-table">
                                    <thead>
                                        <tr>
                                            <th>策略</th>
                                            <th>區間總報酬</th>
                                            <th>最大跌幅</th>
                                            <th>最久沒創新高</th>
                                            <th>賺錢交易比例</th>
                                            <th>完整資料日期平均飆股資金</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {metrics.map((metric) => (
                                            <tr key={metric.run.id}>
                                                <td data-label="策略">
                                                    <a
                                                        href={`#strategy/${encodeURIComponent(metric.run.id)}`}
                                                    >
                                                        {strategyTitle(
                                                            metric.run,
                                                        )}
                                                    </a>
                                                    <small className="ss-muted">
                                                        <br />
                                                        {metric.run.plainTitle}
                                                    </small>
                                                </td>
                                                <td
                                                    data-label="區間總報酬"
                                                    className={gainClass(
                                                        metric.performance
                                                            ?.return,
                                                    )}
                                                >
                                                    {percentage(
                                                        metric.performance
                                                            ?.return,
                                                    )}
                                                </td>
                                                <td
                                                    data-label="最大跌幅"
                                                    className="ss-loss"
                                                >
                                                    {percentage(
                                                        metric.performance
                                                            ?.maxDrawdown,
                                                    )}
                                                </td>
                                                <td data-label="最久沒創新高">
                                                    {duration(
                                                        metric.performance
                                                            ?.longestUnderwaterDays,
                                                    )}
                                                </td>
                                                <td data-label="賺錢交易比例">
                                                    {ratio(metric.winRate)}
                                                    <small className="ss-muted">
                                                        <br />
                                                        {metric.count}{" "}
                                                        筆結束交易
                                                    </small>
                                                </td>
                                                <td data-label="完整資料日期平均飆股資金">
                                                    {ratio(metric.avgWeight)}
                                                    <small className="ss-muted">
                                                        <br />
                                                        完整{" "}
                                                        {
                                                            allocationCoverage.completeDays
                                                        }
                                                        ／
                                                        {
                                                            allocationCoverage.totalDays
                                                        }{" "}
                                                        天；缺資料{" "}
                                                        {
                                                            allocationCoverage.missingDays
                                                        }{" "}
                                                        天
                                                    </small>
                                                </td>
                                            </tr>
                                        ))}
                                        <tr>
                                            <td data-label="策略">
                                                0050（股價）
                                            </td>
                                            <td
                                                data-label="區間總報酬"
                                                className={gainClass(
                                                    benchmark?.return,
                                                )}
                                            >
                                                {percentage(benchmark?.return)}
                                            </td>
                                            <td
                                                data-label="最大跌幅"
                                                className="ss-loss"
                                            >
                                                {percentage(
                                                    benchmark?.maxDrawdown,
                                                )}
                                            </td>
                                            <td data-label="最久沒創新高">
                                                {duration(
                                                    benchmark?.longestUnderwaterDays,
                                                )}
                                            </td>
                                            <td data-label="賺錢交易比例">
                                                不適用
                                            </td>
                                            <td data-label="完整資料日期平均飆股資金">
                                                歷史持股未知
                                            </td>
                                        </tr>
                                    </tbody>
                                </table>
                            </div>
                            <p className="ss-muted ss-small">
                                賺錢比例以共同期間內結束的完整交易計算，部分交易可能在區間前買進；平均飆股資金只採所有策略配置皆完整的共同日期（
                                {allocationCoverage.completeDays}／
                                {allocationCoverage.totalDays} 天），缺資料的{" "}
                                {allocationCoverage.missingDays}{" "}
                                天排除，不能視為零。報酬與回落仍採完整共同期間，與各策略原回測數字不同。
                            </p>
                            <details>
                                <summary>各策略原始回測範圍</summary>
                                {runs.map((run) => (
                                    <p key={run.id}>
                                        {strategyTitle(run)}（
                                        {run.plainTitle || strategyTitle(run)}
                                        ）：
                                        {run.from}—{run.through}；共{" "}
                                        {run.closedTradeCount} 筆已結束交易。
                                        <span className="ss-muted">
                                            研究代號 {run.id}；原始名稱{" "}
                                            {run.name}。
                                        </span>
                                    </p>
                                ))}
                            </details>
                        </section>
                    )}
                </>
            )}
        </div>
    );
}
