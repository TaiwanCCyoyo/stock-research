import type {
    StudioExposure,
    StudioSummary,
} from "../../domain/strategies/types.ts";
import { isCompleteExposure } from "./exposureModel.ts";

type CaptureSummary = Pick<
    StudioSummary,
    | "captureState"
    | "captureCoverage"
    | "capturedClosedTradeCount"
    | "closedTradeCount"
    | "captureAvgWeight"
>;

export function capturedTradeLabel(run: CaptureSummary): string {
    if (run.captureState !== "ready") return "待核對";
    const coverage = run.captureCoverage;
    if (coverage) {
        const prefix =
            coverage.undeterminedClosedTradeCount > 0 ? "至少已確認" : "已確認";
        return `${prefix} ${coverage.confirmedCapturedClosedTradeCount}／${coverage.closedTradeTotal} 筆`;
    }
    return run.capturedClosedTradeCount === null
        ? "待核對"
        : `${run.capturedClosedTradeCount}／${run.closedTradeCount} 筆`;
}

export function capturedTradeNote(run: CaptureSummary): string {
    const coverage =
        run.captureState === "ready" ? run.captureCoverage : undefined;
    return coverage
        ? `已確認未持有飆股 ${coverage.confirmedNotCapturedClosedTradeCount} 筆；尚未判定 ${coverage.undeterminedClosedTradeCount} 筆。已結束交易；曾持有不等於抓到整波`
        : "已結束交易；缺資料保留未知，曾持有不等於抓到整波";
}

export function captureWeightValue(run: CaptureSummary): number | null {
    if (run.captureState !== "ready") return null;
    return run.captureCoverage
        ? run.captureCoverage.knownDayAverageWeight
        : run.captureAvgWeight;
}

export function captureWeightNote(run: CaptureSummary): string {
    const coverage =
        run.captureState === "ready" ? run.captureCoverage : undefined;
    return coverage
        ? `完整配置日 ${coverage.completeExposureDays}／${coverage.totalExposureDays} 天；缺資料 ${coverage.totalExposureDays - coverage.completeExposureDays} 天未納入平均；占整個帳戶的比例`
        : "占整個帳戶的比例；缺資料保留未知";
}

/** Every strategy uses the same subset of aligned dates; missing rows never count as zero. */
export function sharedExposureCoverage(
    dates: readonly string[],
    exposures: readonly (StudioExposure | undefined)[],
) {
    const alignedDates = [...new Set(dates)];
    const rowsByRun = exposures.map((exposure) =>
        exposure?.captureState === "ready"
            ? new Map(exposure.rows.map((row) => [row.date, row]))
            : undefined,
    );
    const completeDates = alignedDates.filter(
        (date) =>
            rowsByRun.length > 0 &&
            rowsByRun.every((rows) => {
                const row = rows?.get(date);
                return row !== undefined && isCompleteExposure(row);
            }),
    );
    return {
        completeDays: completeDates.length,
        totalDays: alignedDates.length,
        missingDays: alignedDates.length - completeDates.length,
        averageWeights: rowsByRun.map((rows) =>
            completeDates.length
                ? completeDates.reduce(
                      (sum, date) => sum + rows!.get(date)!.runawayWeight!,
                      0,
                  ) / completeDates.length
                : null,
        ),
    };
}
