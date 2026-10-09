/** Saved IDs are opaque query values; never put or decode them in a path segment. */
const queryPath = (endpoint: string, values: Record<string, string>) =>
    `${endpoint}?${new URLSearchParams(values).toString()}`;

export const studioRunPath = (runId: string) =>
    queryPath("/run", { run_id: runId });
export const studioTradePath = (runId: string, tradeId: string) =>
    queryPath("/trade", { run_id: runId, trade_id: tradeId });
export const studioAccountPath = (runId: string, date: string) =>
    queryPath("/account", { run_id: runId, date });
export const studioExposurePath = (runId: string) =>
    queryPath("/exposure", { run_id: runId });

/** Request-group identities also preserve opaque IDs, including line breaks. */
export const studioSelectionIdentity = (runIds: readonly string[]) =>
    JSON.stringify(runIds);
export const studioSelectionIds = (identity: string): string[] =>
    JSON.parse(identity);
