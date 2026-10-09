export const HISTORY_SECTIONS = [
    { value: "method", label: "方法成效" },
    { value: "market", label: "行情與分類資料" },
    { value: "design", label: "方法設計與工具" },
] as const;
export type HistorySection = (typeof HISTORY_SECTIONS)[number]["value"];

interface HistoryPresentation {
    section?: string | null;
    title?: string | null;
    savedTitle?: string | null;
    legacyPresentationTitle?: string | null;
    conclusion?: string | null;
    originalSummary?: string | null;
    outcome?: string | null;
}

export function historySection(item: HistoryPresentation): HistorySection {
    return item.section === "market" || item.section === "design"
        ? item.section
        : "method";
}

/** Search spans all groups; a blank query uses the selected group. */
export function filterHistoryItems<T extends HistoryPresentation>(
    items: readonly T[],
    section: HistorySection,
    query: string,
): T[] {
    const search = query.trim().toLocaleLowerCase();
    return items.filter((item) =>
        search
            ? [
                  item.title,
                  item.savedTitle,
                  item.legacyPresentationTitle,
                  item.conclusion,
                  item.originalSummary,
              ].some((value) => value?.toLocaleLowerCase().includes(search))
            : historySection(item) === section,
    );
}

/** Keep a short paragraph intact: its later sentences may qualify the result. */
export function historyConclusion(item: HistoryPresentation): string {
    const text = (item.conclusion ?? "")
        .trim()
        .replace(/^這次研究的摘要[：:]\s*/, "");
    const paragraph = text.split(/\r?\n\s*\r?\n/, 1)[0] ?? "";
    return paragraph;
}

const OUTCOME_LABELS: Record<string, string> = {
    candidate_failed: "行不通",
    candidate_passed: "通過研究門檻，尚未採用",
    invalid_measurement: "量測待修正",
    data_blocked: "資料不足",
    incomplete: "研究中",
    not_evaluated: "尚未評估",
};
export function historyOutcome(item: HistoryPresentation): string {
    return item.outcome && Object.hasOwn(OUTCOME_LABELS, item.outcome)
        ? OUTCOME_LABELS[item.outcome]!
        : "尚無正式判定";
}
