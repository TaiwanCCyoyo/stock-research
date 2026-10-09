import type { CapitalMode } from "../api/types";

export const MODE_LABELS: Record<string, string> = {
    shared: "共用資金池",
    per_stock: "各股獨立",
    unconstrained: "不設限",
};

export function modeSummaryFile(mode: CapitalMode): string {
    return `summary_${mode}.json`;
}
