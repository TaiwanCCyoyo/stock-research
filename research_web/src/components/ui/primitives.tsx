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
export function CompareBars({ rows }: { rows: readonly BarRow[] }) {
    const max = Math.max(...rows.map((row) => row.value), 0) || 1;
    return (
        <div className="u-bars">
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
