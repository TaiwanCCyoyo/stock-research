import type { Families, CatalogEntry, Family } from "../shared-data/model.ts";

/** Return contexts are a bounded set of local routes, never arbitrary URLs. */
export function studyContext(hash: string, study: string): string {
    const source = hash.startsWith("#studies?") ? hash.slice(9) : "";
    const query = new URLSearchParams(source);
    const result = new URLSearchParams();
    for (const key of ["q", "filter"]) {
        const value = query.get(key);
        if (value) result.set(key, value);
    }
    result.set("study", study);
    return "#studies?" + result;
}
export function safeStudyBack(value: string | null): string {
    if (value === "#overview") return value;
    if (!value || !/^#studies(?:\?|$)/.test(value) || value.length > 4096)
        return "#studies";
    const query = new URLSearchParams(value.split("?")[1] ?? "");
    const result = new URLSearchParams();
    for (const key of ["q", "filter", "study"]) {
        const value = query.get(key);
        if (value) result.set(key, value);
    }
    return result.size ? "#studies?" + result : "#studies";
}
export function datasetDetailHref(
    reference: string,
    back = "#studies",
    version?: string,
): string {
    const query = new URLSearchParams({
        ref: reference,
        back: safeStudyBack(back),
    });
    if (version) query.set("version", version);
    return "#dataset?" + query;
}
export function safeDatasetBack(value: string | null): string | null {
    if (!value?.startsWith("#dataset?") || value.length > 8192) return null;
    const query = new URLSearchParams(value.slice(9));
    const ref = query.get("ref");
    return ref
        ? datasetDetailHref(
              ref,
              query.get("back") ?? undefined,
              query.get("version") ?? undefined,
          )
        : null;
}
export type DatasetMatch =
    | { kind: "catalog"; entry: CatalogEntry }
    | { kind: "family"; family: Family }
    | { kind: "choose"; choices: { version: string; label: string }[] }
    | { kind: "missing" | "ambiguous" | "unavailable" };
export function resolveDataset(
    data: Families,
    reference: string,
    version: string | null,
): DatasetMatch {
    const catalogIdentity = /^catalog:([^:]+):(.+)$/.exec(reference);
    const source = reference.startsWith("catalog:")
        ? "catalog"
        : reference.startsWith("derived:")
          ? "derived"
          : null;
    if ((source === "catalog" && !catalogIdentity) || reference === "derived:")
        return { kind: "missing" };
    const id = catalogIdentity?.[1] ?? reference.replace(/^derived:/, "");
    const requested = version ?? catalogIdentity?.[2] ?? null;
    if (catalogIdentity && version && version !== catalogIdentity[2])
        return { kind: "ambiguous" };
    // A namespace is part of identity, not a hint. Without one, an unreadable
    // catalog also prevents us from ruling out a cross-source collision.
    if (source !== "derived" && (!data.catalog || data.catalogError))
        return { kind: "unavailable" };
    if (source !== "catalog" && data.familyError)
        return { kind: "unavailable" };
    const entries = (data.catalog?.entries ?? []).filter(
        (entry) => source !== "derived" && entry.data_id === id,
    );
    const families = data.families.filter(
        (family) => source !== "catalog" && family.family === id,
    );
    if ((entries.length && families.length) || families.length > 1)
        return { kind: "ambiguous" };
    if (!requested) {
        const choices = [
            ...entries.map((entry) => ({
                version: entry.version_id,
                label: "保存版本",
            })),
            ...families.map((family) => ({
                version: family.generation,
                label: "目前 generation（非研究當時版本）",
            })),
        ];
        if (
            new Set(choices.map((choice) => choice.version)).size !==
            choices.length
        )
            return { kind: "ambiguous" };
        return choices.length
            ? { kind: "choose", choices }
            : { kind: "missing" };
    }
    const matches = entries.filter((entry) => entry.version_id === requested);
    if (matches.length > 1) return { kind: "ambiguous" };
    if (matches[0]) return { kind: "catalog", entry: matches[0] };
    if (families[0]?.generation === requested)
        return { kind: "family", family: families[0] };
    return { kind: "missing" };
}
