import type { StudioSummary } from "../../domain/strategies/types.ts";

const savedRunTitles: Record<string, string> = {
    "stock:20261002-add-retry:normal-v1": "小量試單、漲了再加碼",
    "stock:20261002-entry-extension-cap:cap-v1": "小量試單，避免追高",
};

export function strategyTitle(
    run: Pick<StudioSummary, "id" | "plainTitle" | "name">,
): string {
    return Object.hasOwn(savedRunTitles, run.id)
        ? savedRunTitles[run.id]
        : run.plainTitle || run.name;
}

/** Display-only descriptions grounded in these two saved runs' unchanged rules. */
const savedRunIdeas: Record<string, string> = {
    "stock:20261002-add-retry:normal-v1":
        "先買一張試單；持有報酬達 10% 才加碼，完全沒成交的加碼單最多再試一次。",
    "stock:20261002-entry-extension-cap:cap-v1":
        "先買一張試單，但不追近 60 個交易日已漲超過 50% 的股票；加碼與排名出場規則沿用原策略。",
};

export function strategyIdea(
    run: Pick<StudioSummary, "id" | "plainIdea">,
): string {
    return Object.hasOwn(savedRunIdeas, run.id)
        ? savedRunIdeas[run.id]
        : run.plainIdea;
}
