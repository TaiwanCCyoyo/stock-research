import { readArtifactInMode } from "./artifactMode.ts";

/** Public fictional controls or an explicitly configured local private API. */
export async function readArtifact(
    name: string,
    signal: AbortSignal,
): Promise<unknown> {
    return readArtifactInMode(name, signal, import.meta.env.VITE_ARTIFACT_MODE);
}
