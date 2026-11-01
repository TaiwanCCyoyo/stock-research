import type { Verdict } from "../../components/ui/verdicts.ts";
import type { ReportEntry } from "../report-library/model.ts";
import type {
    StudioHistoryItem,
    StudioSummary,
} from "../../domain/strategies/types.ts";

/** One research card. Mirrors the reader-facing part of study-card.v2 so the
 *  page can switch to GET /studies without changing its components. */
export interface StudyCard {
    reading?: {
        state: "ready" | "in_progress" | "history";
        reason: string;
        updated_at?: string;
        edition?: string | null;
    };
    id: string;
    date: string;
    question: string;
    answer: string;
    verdict: Verdict | null;
    dataPeriod: { from: string; to: string } | null;
    keyNumbers: {
        label: string;
        value: number;
        unit: "percent" | "ratio" | "count" | "days" | "twd";
        highlight: boolean;
    }[];
    limitation: string | null;
    reportHref: string | null;
    accountRun: { runId: string; note: string } | null;
    /** Plain warnings shown beside the answer on every card, compact or not. */
    caveats: string[];
    /** Live run progress for a running study, from GET /studies. */
    progress: {
        step: number | null;
        total: number | null;
        label: string | null;
    } | null;
    details: StudyDetails;
}

/** Evidence kept behind the card's collapsed 資料來源 disclosure. */
export interface StudyDetails {
    originalSummary: string | null;
    summaryUnconfirmed: boolean;
    reportPath: string | null;
    webReportReason: string | null;
    sharedData: string[];
    sharedDataReason: string | null;
    note: string | null;
    /** Verbatim report excerpts behind each key number. */
    numberSources: { label: string; excerpt: string }[];
}

const NO_DETAILS: StudyDetails = {
    originalSummary: null,
    summaryUnconfirmed: false,
    reportPath: null,
    webReportReason: null,
    sharedData: [],
    sharedDataReason: null,
    note: null,
    numberSources: [],
};

const OUTCOME_VERDICT: Record<string, Verdict> = {
    candidate_failed: "failed",
    candidate_passed: "promising",
    incomplete: "running",
    not_evaluated: "not_evaluated",
};
const STATUS_VERDICT: Record<string, Verdict> = {
    行不通: "failed",
    研究中: "running",
    尚未評估: "not_evaluated",
};

/** Only recorded outcomes become badges; a saved report alone is no verdict. */
export function historyVerdict(item: StudioHistoryItem): Verdict | null {
    if (item.outcome && Object.hasOwn(OUTCOME_VERDICT, item.outcome))
        return OUTCOME_VERDICT[item.outcome]!;
    return Object.hasOwn(STATUS_VERDICT, item.status)
        ? STATUS_VERDICT[item.status]!
        : null;
}

/** Reader text: first paragraph without Markdown emphasis, links or the old
 *  "這次研究的摘要：" prefix. */
export function plainSummary(text: string): string {
    const paragraph =
        text
            .trim()
            .replace(/^這次研究的摘要[：:]\s*/, "")
            .split(/\r?\n\s*\r?\n/, 1)[0] ?? "";
    return paragraph
        .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
        .replace(/\*\*|__|`/g, "")
        .replace(/^[-*]\s+/gm, "")
        .replace(/\s*\n\s*/g, " ")
        .trim();
}

/** Registration and review states a reader must see next to the summary. */
export function historyCaveats(item: StudioHistoryItem): string[] {
    const caveats: string[] = [];
    if (item.status === "登錄需更新")
        caveats.push(
            item.evidenceState === "registration_unavailable"
                ? "內容待核對"
                : "目前顯示舊版，內容待核對",
        );
    if (item.summarySource === "presentation-metadata" && !item.reviewConfirmed)
        caveats.push("摘要尚未核對，以原文為準");
    return caveats;
}

export function cardFromHistory(item: StudioHistoryItem): StudyCard {
    return {
        id: item.id,
        date: item.date,
        question: item.title,
        answer: plainSummary(item.conclusion || item.originalSummary),
        verdict: historyVerdict(item),
        dataPeriod: null,
        keyNumbers: [],
        limitation: null,
        reportHref: item.webReportHref ?? null,
        accountRun: null,
        caveats: historyCaveats(item),
        progress: null,
        details: {
            originalSummary: item.originalSummary || null,
            summaryUnconfirmed:
                item.summarySource === "presentation-metadata" &&
                !item.reviewConfirmed,
            reportPath: item.reportPath,
            webReportReason: item.webReportHref
                ? null
                : (item.webReportReason ?? null),
            sharedData: item.sharedData ?? [],
            sharedDataReason: item.sharedDataReason ?? null,
            note: item.sourceNote ?? null,
            numberSources: [],
        },
    };
}

/** A static web report; listed even when the saved history service is down. */
export function cardFromReport(report: ReportEntry): StudyCard {
    return {
        id: report.id,
        date: report.date,
        question: report.title,
        answer: report.summary,
        verdict: report.status === "failed" ? "failed" : null,
        dataPeriod: null,
        keyNumbers: [],
        limitation: null,
        reportHref: `#report/${encodeURIComponent(report.id)}`,
        accountRun: null,
        caveats: [],
        progress: null,
        details: {
            ...NO_DETAILS,
            note: report.period ? `資料期間：${report.period}` : null,
        },
    };
}

/** History cards win; reports add only studies the history does not list. */
export function mergeStudyCards(
    history: readonly StudyCard[] | null,
    reports: readonly StudyCard[] | null,
): StudyCard[] | null {
    if (!history && !reports) return null;
    const ids = new Set((history ?? []).map((card) => card.id));
    return [
        ...(history ?? []),
        ...(reports ?? []).filter((card) => !ids.has(card.id)),
    ];
}

export function cardFromRun(
    run: StudioSummary,
    title: string,
    answer: string,
): StudyCard {
    return {
        id: run.id,
        date: run.from,
        question: title,
        answer,
        verdict: "archived",
        dataPeriod: { from: run.from, to: run.through },
        keyNumbers: [],
        limitation: "只有舊期間的結果；要從 2010 年評估需要重新研究。",
        reportHref: null,
        accountRun: {
            runId: run.id,
            note: `帳戶模擬 ${run.from.slice(0, 4)}–${run.through.slice(0, 4)}`,
        },
        caveats: [],
        progress: null,
        details: { ...NO_DETAILS, note: run.name },
    };
}

export type StudyFilter = "all" | Verdict | "report";

export function filterStudies(
    cards: readonly StudyCard[],
    filter: StudyFilter,
    query: string,
): StudyCard[] {
    const search = query.trim().toLocaleLowerCase();
    return cards.filter(
        (card) =>
            (filter === "all" ||
                (filter === "report"
                    ? card.reportHref !== null
                    : card.verdict === filter)) &&
            (!search ||
                [
                    card.id,
                    card.question,
                    card.answer,
                    card.details.reportPath ?? "",
                ].some((value) => value.toLocaleLowerCase().includes(search))),
    );
}

/** Newest first, grouped by calendar month for the timeline. */
export function groupByMonth(cards: readonly StudyCard[]) {
    const groups = new Map<string, StudyCard[]>();
    for (const card of [...cards].sort(
        (a, b) =>
            (b.reading?.updated_at || b.date).localeCompare(
                a.reading?.updated_at || a.date,
            ) || a.id.localeCompare(b.id),
    )) {
        const key = (card.reading?.updated_at || card.date).slice(0, 7);
        const list = groups.get(key);
        if (list) list.push(card);
        else groups.set(key, [card]);
    }
    return [...groups].map(([month, items]) => ({
        month,
        label: `${month.slice(0, 4)} 年 ${Number(month.slice(5, 7))} 月`,
        items,
    }));
}
