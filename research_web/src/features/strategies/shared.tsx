import type { ReactNode } from "react";
import type { StudioSummary } from "../../domain/strategies/types";
import { strategyStatus } from "./model";

export function StudioState({
    loading,
    error,
    retry,
    empty = false,
}: {
    loading: boolean;
    error: string;
    retry: () => void;
    empty?: boolean;
}) {
    if (error)
        return (
            <div className="ss-error">
                <strong>研究資料暫時無法讀取</strong>
                <p>{error}</p>
                <button className="ss-button" onClick={retry}>
                    重新讀取
                </button>
            </div>
        );
    return (
        <div className="ss-loading">
            {loading
                ? "正在整理已保存的研究紀錄…"
                : empty
                  ? "目前沒有符合條件的研究紀錄。"
                  : "尚未提供這份研究明細。"}
        </div>
    );
}
export function StatusBadge({
    run,
}: {
    run: Pick<StudioSummary, "ownerAdopted" | "studyStatus">;
}) {
    const status = strategyStatus(run);
    return (
        <span className={`ss-status ss-status-${status}`}>
            {status === "adopted"
                ? "已採用"
                : status === "failed"
                  ? "已淘汰"
                  : "研究中，尚未採用"}
        </span>
    );
}
export function Metric({
    label,
    value,
    note,
    className = "",
}: {
    label: string;
    value: ReactNode;
    note?: ReactNode;
    className?: string;
}) {
    return (
        <div className="ss-kpi">
            <span>{label}</span>
            <strong className={className}>{value}</strong>
            {note && <small>{note}</small>}
        </div>
    );
}
