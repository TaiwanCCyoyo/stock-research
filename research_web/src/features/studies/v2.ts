import { artifactMode } from "../../api/artifactMode.ts";
import type { Verdict } from "../../components/ui/verdicts.ts";
import type { StudyCard } from "./model.ts";

/** One saved tasks/<task-id>/study.json as served by GET /studies
 *  (study-card.v2; docs/en/study-presentation.md), plus response-only run fields. */
export interface StudyCardV2 {
    schema: "study-card.v2";
    task_id: string;
    kind: "study" | "tooling";
    question: string;
    answer: string;
    verdict: Verdict;
    data_period: { from: string; to: string } | null;
    key_numbers: {
        label: string;
        value: number;
        unit: StudyCard["keyNumbers"][number]["unit"];
        highlight: boolean;
        source_excerpt: string;
    }[];
    limitation: string;
    report: { web_report: string | null; markdown: string | null };
    account_run: { run_id: string; period_note: string } | null;
    delivery_state: string | null;
    scratch_run: { run: string } | null;
    provenance: {
        answer_source: string | null;
        shared_data: string[];
    };
    progress?: Record<string, unknown> | null;
    run_state?: string;
}

export interface StudiesWarning {
    task_id: string;
    code: string;
    message: string;
}

export interface StudiesResponse {
    cards: StudyCardV2[];
    warnings: StudiesWarning[];
}

/** Warning codes a reader must see on the card itself. Others (an unavailable
 *  legacy source, an invalid card) hide the card and stay in the page notes. */
const CARD_CAVEATS: Record<string, string> = {
    report_sha256_mismatch: "報告內容與登錄時不同，內容待核對",
    source_unavailable: "原始報告尚未找到，內容待核對",
    scratch_unavailable: "執行進度暫時讀不到",
};

export async function readStudies(
    signal: AbortSignal,
    fetcher: typeof fetch = fetch,
): Promise<StudiesResponse> {
    const response = await fetcher("/history-api/studies", {
        signal,
        headers: {
            "X-Research-Data-Mode": artifactMode(
                import.meta.env?.VITE_ARTIFACT_MODE,
            ),
        },
    });
    if (!response.ok)
        throw new Error(`研究卡片暫時讀不到（HTTP ${response.status}）。`);
    if (response.headers.get("content-type")?.includes("text/html"))
        throw new Error("研究資料服務尚未啟動。");
    const value = (await response.json()) as Partial<StudiesResponse>;
    if (!Array.isArray(value?.cards) || !Array.isArray(value?.warnings))
        throw new Error("研究卡片格式不符，無法讀取。");
    return {
        cards: value.cards.filter((card) => card?.schema === "study-card.v2"),
        warnings: value.warnings,
    };
}

/** "20261021-momentum-only-doubling" → "2026-10-21" (the task date). */
export function taskDate(taskId: string): string {
    const digits = taskId.slice(0, 8);
    return /^\d{8}$/.test(digits)
        ? `${digits.slice(0, 4)}-${digits.slice(4, 6)}-${digits.slice(6, 8)}`
        : "";
}

/** Numeric step/total progress from the run record, when it has one. */
export function runProgress(
    card: Pick<StudyCardV2, "progress" | "run_state">,
): StudyCard["progress"] {
    const progress = card.progress;
    if (!progress || typeof progress !== "object") return null;
    const step = Number(progress.step),
        total = Number(progress.total);
    const label = typeof progress.label === "string" ? progress.label : null;
    if (!Number.isFinite(step) || !Number.isFinite(total) || total <= 0)
        return label ? { step: null, total: null, label } : null;
    return { step, total, label };
}

export function cardFromV2(
    card: StudyCardV2,
    warnings: readonly StudiesWarning[] = [],
): StudyCard {
    const caveats = [
        ...new Set(
            warnings
                .filter((warning) => warning.task_id === card.task_id)
                .map((warning) => CARD_CAVEATS[warning.code])
                .filter((text): text is string => !!text),
        ),
    ];
    return {
        id: card.task_id,
        date: taskDate(card.task_id),
        question: card.question,
        answer: card.answer,
        verdict: card.verdict,
        dataPeriod: card.data_period,
        keyNumbers: card.key_numbers.map((number) => ({
            label: number.label,
            value: number.value,
            unit: number.unit,
            highlight: number.highlight,
        })),
        limitation: card.limitation,
        reportHref: card.report.web_report
            ? `#report/${encodeURIComponent(card.task_id)}`
            : null,
        accountRun: card.account_run
            ? {
                  runId: card.account_run.run_id,
                  note: card.account_run.period_note,
              }
            : null,
        caveats,
        progress: runProgress(card),
        details: {
            originalSummary: card.provenance.answer_source,
            summaryUnconfirmed: false,
            reportPath: card.report.markdown,
            webReportReason: null,
            sharedData: card.provenance.shared_data,
            sharedDataReason: null,
            note: null,
            numberSources: card.key_numbers.map((number) => ({
                label: number.label,
                excerpt: number.source_excerpt,
            })),
        },
    };
}

/** Cards hidden by the reader (legacy source unavailable, invalid card). */
export function hiddenCount(response: StudiesResponse): number {
    const shown = new Set(response.cards.map((card) => card.task_id));
    return new Set(
        response.warnings
            .filter((warning) => warning.task_id && !shown.has(warning.task_id))
            .map((warning) => warning.task_id),
    ).size;
}
