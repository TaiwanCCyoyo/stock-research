import type { StudyCard } from "./model.ts";

export type ReadingState = "ready" | "in_progress" | "history";

/** A registered static report remains readable while the private API is loading. */
export function reportView(
    requested: string | null,
    kind: StudyCard["reportKind"],
    nativeAvailable: boolean,
    pending: boolean,
) {
    if (requested === "reading") return "reading";
    if (requested === "summary") return "summary";
    if (nativeAvailable || kind === "html") return "html";
    if (kind === "markdown") return "reading";
    if (kind === "summary") return "summary";
    return pending ? "loading" : "html";
}

export function currentStudyHash(): string {
    return typeof window === "undefined" ? "" : window.location.hash;
}
export interface ReadingRecord {
    schema: "report-reading.v1";
    task_id: string;
    state: ReadingState;
    reason: string;
    updated_at: string;
    edition: string | null;
    question: string;
    answer: string;
    limitation: string;
    data_period: { from: string; to: string } | null;
    sources: { label: string; path: string }[];
}

export const READING_LABELS: Record<ReadingState, string> = {
    ready: "研究報告",
    in_progress: "進行中",
    history: "已封存",
};

export function readingState(card: StudyCard): ReadingState {
    return card.reading?.state ?? "history";
}

/** Collections describe research lifecycle, independently of editorial review. */
export function studyCollection(card: StudyCard): ReadingState {
    const verdict = card.sourceVerdict ?? card.verdict;
    if (verdict === "archived") return "history";
    if (
        verdict === "running" ||
        verdict === "not_evaluated" ||
        card.reading?.state === "in_progress"
    )
        return "in_progress";
    return "ready";
}

/** Every nonarchived identity has an honest web entry, even with source gaps. */
export function withReportEntry(card: StudyCard): StudyCard {
    if (card.reportHref)
        return {
            ...card,
            reportKind:
                card.reportKind ??
                (card.reportHref.includes("view=reading")
                    ? "markdown"
                    : "html"),
        };
    if (studyCollection(card) === "history") return card;
    return {
        ...card,
        reportKind: "summary",
        reportHref: `#report/${encodeURIComponent(card.id)}?view=summary`,
    };
}

export function readingDate(card: StudyCard): string {
    return card.reading?.updated_at || card.date;
}

export function readingLink(id: string, back = "#studies"): string {
    return `#report/${encodeURIComponent(id)}?view=reading&back=${encodeURIComponent(back)}`;
}

export function studiesBack(hash: string): string {
    const value = new URLSearchParams(hash.split("?")[1] ?? "").get("back");
    return value && /^#studies(?:\?|$)/.test(value) ? value : "#studies";
}

/** Explicit editorial acceptance is independent of verdict and original-card pins. */
export function withReading(
    card: StudyCard,
    reading: ReadingRecord,
): StudyCard {
    // A visibility-only record must not freeze the evolving study's current summary.
    if (!reading.edition) return { ...card, reading };
    return {
        ...card,
        reading,
        question: reading.question,
        answer: reading.answer,
        limitation: reading.limitation,
        dataPeriod: reading.data_period,
        // Original metrics/verdict are not automatically claims of the new edition.
        keyNumbers: [],
        sourceVerdict: card.sourceVerdict ?? card.verdict ?? undefined,
        verdict: null,
        reportKind: card.reportKind === "html" ? "html" : "markdown",
        reportHref:
            card.reportKind === "html" ? card.reportHref : readingLink(card.id),
        caveats: [],
    };
}

export function pendingCard(id: string, reason: string): StudyCard {
    return {
        id,
        date: /^\d{8}/.test(id)
            ? `${id.slice(0, 4)}-${id.slice(4, 6)}-${id.slice(6, 8)}`
            : "",
        question: "原始報告待補",
        answer: "這份紀錄尚未完成內容核對。",
        verdict: null,
        dataPeriod: null,
        keyNumbers: [],
        limitation: reason,
        reportHref: null,
        accountRun: null,
        caveats: [],
        progress: null,
        reading: { state: "in_progress", reason },
        details: {
            originalSummary: null,
            summaryUnconfirmed: true,
            reportPath: null,
            webReportReason: null,
            sharedData: [],
            sharedDataReason: null,
            note: null,
            numberSources: [],
        },
    };
}
