import type { StudyCard } from "./model.ts";

export type ReadingState = "ready" | "in_progress" | "history";
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
    ready: "報告",
    in_progress: "進行中",
    history: "歷史與待整理",
};

export function readingState(card: StudyCard): ReadingState {
    return card.reading?.state ?? "history";
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
        verdict: null,
        reportHref: reading.edition ? readingLink(card.id) : card.reportHref,
        caveats: [],
    };
}

export function pendingCard(id: string, reason: string): StudyCard {
    return {
        id,
        date: /^\d{8}/.test(id)
            ? `${id.slice(0, 4)}-${id.slice(4, 6)}-${id.slice(6, 8)}`
            : "",
        question: id,
        answer: "這份紀錄尚未完成內容核對。",
        verdict: null,
        dataPeriod: null,
        keyNumbers: [],
        limitation: reason,
        reportHref: null,
        accountRun: null,
        caveats: [],
        progress: null,
        reading: { state: "history", reason },
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
