import assert from "node:assert/strict";
import { mkdir, mkdtemp, rm, writeFile } from "node:fs/promises";
import { resolve, join } from "node:path";
import test from "node:test";
import {
    assertNoPrivatePublicCandidates,
    privatePublicCandidates,
} from "./private-public-guard.mjs";

test("build guard refuses every removed private candidate, even when Git ignores it", async () => {
    const scratch = resolve("../.tmp");
    await mkdir(scratch, { recursive: true });
    const directory = await mkdtemp(join(scratch, "private-build-guard-"));
    try {
        assertNoPrivatePublicCandidates(directory);
        for (const name of privatePublicCandidates) {
            const path = join(directory, name);
            await mkdir(resolve(path, ".."), { recursive: true });
            await writeFile(path, "private");
            assert.throws(
                () => assertNoPrivatePublicCandidates(directory),
                /outside public\/dist/,
            );
            await rm(path);
        }
    } finally {
        await rm(directory, { recursive: true });
    }
});
