export interface SharedGenerationMetadata {
    family: string;
    generation: string;
    asof: string;
    built_at_utc: string;
    status_sha256: string;
}

export type SharedDataStatusState =
    | { status: "synthetic" }
    | { status: "loading" }
    | { status: "failure"; message: string }
    | { status: "available"; metadata: SharedGenerationMetadata };

export function initialSharedDataStatus(mode?: string): SharedDataStatusState {
    return mode === "local-private"
        ? { status: "loading" }
        : { status: "synthetic" };
}

export function parseSharedGenerationMetadata(
    value: unknown,
): SharedGenerationMetadata {
    if (!value || typeof value !== "object" || Array.isArray(value))
        throw new Error("共用維護資料狀態回應格式無效。");
    const record = value as Record<string, unknown>;
    for (const key of [
        "family",
        "generation",
        "asof",
        "built_at_utc",
        "status_sha256",
    ])
        if (typeof record[key] !== "string" || !record[key])
            throw new Error(`共用維護資料狀態缺少有效的 ${key}。`);
    return {
        family: record.family as string,
        generation: record.generation as string,
        asof: record.asof as string,
        built_at_utc: record.built_at_utc as string,
        status_sha256: record.status_sha256 as string,
    };
}
