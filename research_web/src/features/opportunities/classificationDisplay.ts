import type {
    OpportunityRow,
    OpportunitySecurity,
    SourceRef,
} from "../../domain/opportunities/types.ts";

type ClassificationRow = Pick<OpportunityRow, "industry"> & {
    security: Pick<
        OpportunitySecurity,
        "classificationSnapshot" | "industry" | "classificationReferences"
    >;
};

function classificationSnapshots(row: ClassificationRow) {
    const snapshot = row.security.classificationSnapshot;
    if (snapshot) return [snapshot];
    // Legacy membership dates are not retrieval timestamps; retain every source
    // in its saved order without treating one snapshot as newer or authoritative.
    return row.security.industry
        .filter((membership) => membership.basis === "current-snapshot")
        .map((membership) => ({
            label: membership.label,
            observedAt: null,
            sourceId: membership.sourceId,
        }));
}

/** Labels describe provenance without changing the model's grouping identity. */
export function classificationLabel(row: ClassificationRow): string {
    if (
        row.industry.basis === "historical" ||
        row.industry.basis === "document-period"
    )
        return row.industry.label;
    const labels = [
        ...new Set(
            classificationSnapshots(row).map((snapshot) => snapshot.label),
        ),
    ];
    return labels.length ? labels.join("、") : "分類待補";
}

/** Explain the label's time basis without changing its grouping or evidence. */
export function classificationContext(row: ClassificationRow): string {
    if (row.industry.basis === "historical") return "";
    if (row.industry.basis === "document-period") return "依當年度年報整理";
    return classificationSnapshots(row).length
        ? "參照現有分類，當年歸屬待確認"
        : "";
}

/** Display the inclusive calendar end of a validated half-open interval. */
function inclusiveEnd(untilExclusive: string | null): string | null {
    if (untilExclusive === null) return null;
    const end = new Date(`${untilExclusive}T00:00:00Z`);
    end.setUTCDate(end.getUTCDate() - 1);
    return end.toISOString().slice(0, 10);
}

export function classificationEvidence(
    row: ClassificationRow,
    sources: readonly SourceRef[],
) {
    const sourceFor = (id: string) =>
        sources.find((source) => source.id === id) ?? null;
    const industry = row.industry;
    return {
        group:
            industry.basis === "historical" ||
            industry.basis === "document-period"
                ? {
                      id: industry.id,
                      label: industry.label,
                      basis: industry.basis,
                      from: industry.from,
                      through: inclusiveEnd(industry.untilExclusive),
                      sourceId: industry.sourceId,
                      source: sourceFor(industry.sourceId),
                  }
                : null,
        snapshots: classificationSnapshots(row).map((snapshot) => ({
            ...snapshot,
            source: sourceFor(snapshot.sourceId),
        })),
        references: (row.security.classificationReferences ?? []).map(
            (reference) => ({
                ...reference,
                through: inclusiveEnd(reference.untilExclusive),
                sources: reference.sourceIds.map((sourceId) => ({
                    sourceId,
                    source: sourceFor(sourceId),
                })),
            }),
        ),
    };
}

export function classificationSourceHref(source: SourceRef): string | null {
    if (!source.url) return null;
    try {
        const url = new URL(source.url);
        return url.protocol === "https:" || url.protocol === "http:"
            ? url.href
            : null;
    } catch {
        return null;
    }
}

/** Keep recorded document names/page references, not storage or pipeline identity. */
export function classificationSourceLabel(source: SourceRef | null): string {
    if (!source) return "尚未提供可核對的來源";
    const label = source.label
        .replace(/\([^)]*zero-based[^)]*\)/gi, "")
        .replace(/（[^）]*zero-based[^）]*）/gi, "");
    const pagePattern =
        /\b(?:(?:physical|printed)\s+)?(?:PDF\s+)?pages?\s+\d+(?:\s*[-–—]\s*\d+)?\b|第\s*\d+(?:\s*[-–—～]\s*\d+)?\s*頁/gi;
    const pages = [...new Set(label.match(pagePattern) ?? [])];
    let title = label.split(/\s+\|\s+/)[0].trim();
    // Joined evidence labels prefix the original document name with the selected
    // period and grouping; those are already explained in their own UI fields.
    if (title.startsWith("回溯文件期間"))
        title = title.split("；").at(-1)?.trim() ?? "";
    title = title
        .replace(
            /\b(?:raw-file-bytes|canonical-retained-observation-json|claims?\b|(?:sha-?256|hash|path)\s*[:=]).*/i,
            "",
        )
        .replace(pagePattern, "")
        .replace(/(?:[,;，；]\s*)?\blines?\s+\d+(?:\s*[-–—]\s*\d+)?/gi, "")
        .replace(/[\s|;；,:：]+$/g, "")
        .trim();
    const technical =
        /\b(?:raw-file-bytes|canonical-retained|preserved-(?:research-artifact|catalog-chunk)|file[_-]bytes|sha-?256|\w+_(?:hash|sha256))\b|^Snapshot-only classification|\b(?:rows|sources)\[|[a-z]:[\\/]|(?:^|\s)(?:\.{1,2}[\\/]|[\\/])\S+|\b[\w.-]+\.(?:parquet|jsonl?|csv|toml|ya?ml|py|ts|pdf)\b|\b[\da-f]{32,}\b|(?:^|\s)\w+_id\s*[:=]|^(?:[\w.-]+:){2,}[\w.-]+$/i;
    if (
        !title ||
        title === source.id ||
        title === source.hash ||
        (source.path && title.includes(source.path)) ||
        technical.test(title)
    )
        title = "已保存的來源資料";
    return [title, ...pages].join(" · ");
}
