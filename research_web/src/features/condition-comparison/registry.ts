import { syntheticComparison } from "./fixture.ts";
import { adaptSavedComparison } from "./model.ts";
import type { ReadState } from "./model.ts";

export const SYNTHETIC_RESULT_ID = syntheticComparison.id;
/** Exact immutable registrations only. No endpoint, path or provenance comes from a URL.
 * The pending research-owned L1 producer contract is deliberately NOT duplicated here. */
export function readRegisteredComparison(resultId: string): ReadState {
    if (resultId !== SYNTHETIC_RESULT_ID)
        return {
            status: "error",
            message: "此保存結果尚未登錄；沒有改用其他結果或即時重算。",
        };
    return adaptSavedComparison(syntheticComparison, (saved) => saved);
}
