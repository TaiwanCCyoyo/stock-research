import { existsSync } from "node:fs";
import { join } from "node:path";

export const privatePublicCandidates = [
    "data/opportunity-explorer.json.gz",
    "data/saved-research-runs.json.gz",
    "data/research-evidence-v2-classified/opportunity-explorer.json.gz",
    "data/research-evidence-v2-classified/saved-research-runs.json.gz",
    "data/saved-research-studio.manifest.json",
    "data/saved-research-studio.part-00000.bin",
    "data/saved-research-studio.part-00001.bin",
];

export function assertNoPrivatePublicCandidates(publicDirectory) {
    const found = privatePublicCandidates.filter((name) =>
        existsSync(join(publicDirectory, name)),
    );
    if (found.length)
        throw new Error(
            `Private presentation artifacts must stay outside public/dist: ${found.join(", ")}`,
        );
}
