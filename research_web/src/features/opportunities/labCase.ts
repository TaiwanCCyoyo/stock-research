import type {
    OpportunityBundle,
    OpportunityRow,
} from "../../domain/opportunities/types.ts";
import type { LabCase } from "../wave-lab/types.ts";
import { classificationLabel } from "./classificationDisplay.ts";

/** Keep case price provenance separate from the producer's catalog identity. */
export function toLabCase(
    row: OpportunityRow,
    bundle: OpportunityBundle,
): LabCase | null {
    const firstPrice = row.security.prices[0];
    const lastPrice = row.security.prices.at(-1);
    if (!firstPrice || !lastPrice) return null;
    const caseSource = row.security.detailCaseId
        ? bundle.sources.find(
              (source) => source.id === `case:${row.security.detailCaseId}`,
          )
        : undefined;
    const catalogSource = bundle.sources.find(
        (source) => source.id === "producer:catalog_hash",
    );
    const limitations = [...bundle.limitations];
    if (!caseSource?.hash)
        limitations.push(
            "未提供或未綁定本例的精確價格來源雜湊；來源身分未知。",
        );
    if (!catalogSource?.hash)
        limitations.push("未提供原始目錄的雜湊身分；目錄身分未知。");
    return {
        id: row.security.detailCaseId ?? row.security.id,
        name: row.security.name,
        code: row.security.code,
        kind: bundle.kind === "synthetic" ? "synthetic" : "historical",
        category: classificationLabel(row),
        question: "核對這段上漲的開始、加速、休息與結束；方法標記仍可討論。",
        points: row.security.prices.map((point) => ({
            date: point.date,
            raw: point.raw ?? null,
            adjusted: point.close,
            flags: [...point.flags],
        })),
        selectedOpportunity: {
            securityId: row.security.id,
            waveId: row.wave.id,
            sourceId: row.wave.sourceId,
            start: row.wave.start,
            peakDate: row.wave.peakDate,
            endConfirmedAt: row.wave.endConfirmedAt,
            observedThrough: row.wave.observedThrough,
            scale: row.wave.scale,
            leftCensored: row.wave.leftCensored,
            rightCensored: row.wave.rightCensored,
            launch: row.wave.launch ? { ...row.wave.launch } : null,
        },
        source: {
            label: caseSource?.label ?? `${bundle.label}（本例價格來源未綁定）`,
            from: firstPrice.date,
            to: lastPrice.date,
            priceBasis: bundle.priceBasis,
            hash: caseSource?.hash,
            catalogHash: catalogSource?.hash,
            limitations,
        },
    };
}
