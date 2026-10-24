import type { ReactNode } from "react";
import { VERDICT_LABELS, type Verdict } from "./verdicts.ts";

export function VerdictBadge({ verdict }: { verdict: Verdict }) {
    return (
        <span className="u-verdict" data-verdict={verdict}>
            {VERDICT_LABELS[verdict]}
        </span>
    );
}

export interface BarRow {
    label: string;
    value: number;
    display: string;
    highlight?: boolean;
}

/** Horizontal comparison bars scaled to the largest value shown. */
export function CompareBars({
    rows,
    stacked = false,
}: {
    rows: readonly BarRow[];
    /** Label on its own line; for narrow cards. */
    stacked?: boolean;
}) {
    const max = Math.max(...rows.map((row) => row.value), 0) || 1;
    return (
        <div className={`u-bars${stacked ? " is-stacked" : ""}`}>
            {rows.map((row) => (
                <div
                    key={row.label}
                    className={`u-bar${row.highlight === false ? " is-dim" : ""}`}
                >
                    <span>{row.label}</span>
                    <span className="u-track">
                        <span
                            style={{
                                width: `${Math.max(0, (row.value / max) * 100)}%`,
                            }}
                        />
                    </span>
                    <b>{row.display}</b>
                </div>
            ))}
        </div>
    );
}

/** Technical provenance stays available but collapsed by default. */
export function SourceInfo({
    children,
    label = "資料來源",
}: {
    children: ReactNode;
    label?: string;
}) {
    return (
        <details className="u-source">
            <summary>{label}</summary>
            <div>{children}</div>
        </details>
    );
}

/** Placeholder cards with a soft shimmer while content loads. */
export function SkeletonCards({
    count = 3,
    className = "",
    label = "正在讀取",
}: {
    count?: number;
    className?: string;
    label?: string;
}) {
    return (
        <div className={className} role="status" aria-label={label}>
            {Array.from({ length: count }, (_, i) => (
                <div key={i} className="u-card u-skel-card" aria-hidden="true">
                    <span className="u-skel" style={{ width: "34%" }} />
                    <span className="u-skel u-skel-title" />
                    <span className="u-skel" />
                    <span className="u-skel" style={{ width: "72%" }} />
                </div>
            ))}
        </div>
    );
}

/** A slim determinate progress line, e.g. while market data is prepared. */
export function ProgressLine({
    label,
    done,
    total,
}: {
    label: string;
    done: number;
    total: number;
}) {
    const ratio = total > 0 ? Math.min(1, done / total) : 0;
    return (
        <div
            className="u-progress"
            role="progressbar"
            aria-label={label}
            aria-valuemin={0}
            aria-valuemax={total}
            aria-valuenow={done}
        >
            <span>{label}</span>
            <span className="u-track">
                <span style={{ width: `${ratio * 100}%` }} />
            </span>
        </div>
    );
}
