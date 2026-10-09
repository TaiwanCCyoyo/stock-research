import { createOpportunityFixture } from "../domain/opportunities/fixture.ts";
import { createSyntheticResearchBundle } from "./syntheticResearch.ts";

export type ArtifactMode = "public-synthetic" | "local-private";
const names = new Set(["opportunity-explorer", "saved-research-runs"]);

export function artifactMode(value?: string): ArtifactMode {
    if (!value || value === "public-synthetic") return "public-synthetic";
    if (value === "local-private") return value;
    throw new Error(
        "Unknown artifact mode; use public-synthetic or local-private.",
    );
}

export function assertArtifactResponseMode(
    value: unknown,
    modeValue?: string,
): void {
    if (
        !value ||
        typeof value !== "object" ||
        !("dataMode" in value) ||
        value.dataMode !== artifactMode(modeValue)
    )
        throw new Error(
            "Data mode mismatch: evidence unavailable. Configure frontend and local API consistently.",
        );
}

/** The private mode never falls back to demonstrations when evidence is unavailable. */
export async function readArtifactInMode(
    name: string,
    signal: AbortSignal,
    modeValue?: string,
    fetcher: typeof fetch = fetch,
): Promise<unknown> {
    if (!names.has(name)) throw new Error(`Unsupported artifact: ${name}`);
    signal.throwIfAborted();
    if (artifactMode(modeValue) === "public-synthetic")
        return name === "opportunity-explorer"
            ? createOpportunityFixture()
            : createSyntheticResearchBundle();
    const response = await fetcher(`/api/private-artifacts/v1/${name}`, {
        signal,
    });
    if (
        !response.ok ||
        !response.headers.get("content-type")?.includes("application/json")
    )
        throw new Error(
            "本機私有資料 unavailable：請設定外部資料入口並啟動本機 API。",
        );
    const value: unknown = await response.json();
    assertArtifactResponseMode(value, modeValue);
    return value;
}
