import { syntheticComparison } from "./fixture.ts";
import { adaptSavedComparison } from "./model.ts";
import type { ReadState } from "./model.ts";
import l1Fixture from "../../../../scripts/tests/fixtures/l1-volume-comparison.synthetic.v1.json" with { type: "json" };
import { adaptL1Comparison } from "./l1Adapter.ts";

export const SYNTHETIC_RESULT_ID = syntheticComparison.id;
export const L1_SYNTHETIC_RESULT_ID = "l1-volume-comparison.synthetic.v1";
/** Exact immutable registrations only. No endpoint, path or provenance comes from a URL.
 * L1 uses the research producer's tracked fixture directly, with no copied payload. */
export function readRegisteredComparison(resultId: string): ReadState {
    if (resultId === L1_SYNTHETIC_RESULT_ID)
        return adaptSavedComparison(l1Fixture, (saved) =>
            adaptL1Comparison(saved, resultId),
        );
    if (resultId !== SYNTHETIC_RESULT_ID)
        return {
            status: "error",
            message: "此保存結果尚未登錄；沒有改用其他結果或即時重算。",
        };
    return adaptSavedComparison(syntheticComparison, (saved) => saved);
}
