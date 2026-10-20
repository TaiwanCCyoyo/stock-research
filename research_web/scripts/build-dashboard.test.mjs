import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import test from "node:test";
import {
    ensureRelease,
    isCurrentRelease,
    publishDirectory,
    sourceVersion,
} from "./build-dashboard.mjs";

async function fixture() {
    const scratch = resolve("../.tmp");
    await mkdir(scratch, { recursive: true });
    const root = await mkdtemp(join(scratch, "dashboard-release-"));
    const web = join(root, "research_web");
    await mkdir(join(web, "src"), { recursive: true });
    await mkdir(join(web, "scripts"), { recursive: true });
    await mkdir(join(root, "tasks"), { recursive: true });
    await writeFile(join(web, "src", "main.tsx"), "source-v1");
    await writeFile(
        join(web, "scripts", "research-reports.mjs"),
        "report source",
    );
    await writeFile(join(web, "vite.config.ts"), "vite source");
    await writeFile(join(web, "index.html"), "<html></html>");
    await writeFile(join(web, "package.json"), "{}");
    return { root, web };
}

function fakeBuild(root, stage, version) {
    const web = join(root, "research_web");
    mkdirSync(join(stage, "reports"), { recursive: true });
    writeFileSync(
        join(stage, "index.html"),
        `<meta name="research-web-version" content="${version}">`,
    );
    writeFileSync(
        join(stage, "reports", "index.json"),
        JSON.stringify({ schema: "research-reports.v1", version, reports: [] }),
    );
    writeFileSync(
        join(stage, "app.js"),
        readFileSync(join(web, "src", "main.tsx")),
    );
}

test("release rebuilds stale source and keeps frontend and report indexes on one version", async () => {
    const { root, web } = await fixture();
    try {
        const build = (atRoot, stage, version) =>
            fakeBuild(atRoot, stage, version);
        assert.equal(await ensureRelease({ root, build }), "built");
        const dist = join(web, "dist");
        const firstVersion = sourceVersion(root);
        assert.equal(isCurrentRelease(dist, firstVersion), true);
        assert.equal(await ensureRelease({ root, build }), "current");

        await writeFile(join(web, "src", "main.tsx"), "source-v2");
        const secondVersion = sourceVersion(root);
        assert.notEqual(firstVersion, secondVersion);
        assert.equal(await ensureRelease({ root, build }), "built");
        assert.equal(isCurrentRelease(dist, secondVersion), true);
        const index = JSON.parse(
            await readFile(join(dist, "reports", "index.json"), "utf8"),
        );
        const release = JSON.parse(
            await readFile(join(dist, "release.json"), "utf8"),
        );
        assert.equal(index.version, secondVersion);
        assert.equal(release.version, secondVersion);
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});

test("release fingerprint includes Vite production env files and effective overrides", async () => {
    const { root, web } = await fixture();
    const previousArtifactMode = process.env.VITE_ARTIFACT_MODE;
    const previousApiBase = process.env.VITE_API_BASE;
    try {
        const baseline = sourceVersion(root);
        await writeFile(
            join(web, ".env.production"),
            "VITE_API_BASE=/private-api\n",
        );
        const envFileVersion = sourceVersion(root);
        assert.notEqual(envFileVersion, baseline);
        process.env.VITE_ARTIFACT_MODE = "synthetic-private";
        assert.notEqual(sourceVersion(root), envFileVersion);
    } finally {
        if (previousArtifactMode === undefined)
            delete process.env.VITE_ARTIFACT_MODE;
        else process.env.VITE_ARTIFACT_MODE = previousArtifactMode;
        if (previousApiBase === undefined) delete process.env.VITE_API_BASE;
        else process.env.VITE_API_BASE = previousApiBase;
        await rm(root, { recursive: true, force: true });
    }
});

test("failed staging leaves the prior usable dist untouched", async () => {
    const { root, web } = await fixture();
    try {
        const build = (atRoot, stage, version) =>
            fakeBuild(atRoot, stage, version);
        await ensureRelease({ root, build });
        const dist = join(web, "dist");
        const before = await readFile(join(dist, "release.json"), "utf8");
        await writeFile(join(web, "src", "main.tsx"), "broken-source");
        assert.throws(
            () =>
                ensureRelease({
                    root,
                    build: () => {
                        throw new Error("synthetic build failure");
                    },
                }),
            /synthetic build failure/,
        );
        assert.equal(
            await readFile(join(dist, "release.json"), "utf8"),
            before,
        );
        assert.equal(isCurrentRelease(dist, JSON.parse(before).version), true);
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});

test("source changes during the staged build reject publication and retain old dist", async () => {
    const { root, web } = await fixture();
    try {
        const build = (atRoot, stage, version) =>
            fakeBuild(atRoot, stage, version);
        await ensureRelease({ root, build });
        const dist = join(web, "dist");
        const before = await readFile(join(dist, "release.json"), "utf8");
        await writeFile(join(web, "src", "main.tsx"), "source-v2");
        assert.throws(
            () =>
                ensureRelease({
                    root,
                    build: (atRoot, stage, version) => {
                        fakeBuild(atRoot, stage, version);
                        writeFileSync(
                            join(web, "src", "main.tsx"),
                            "source-v3",
                        );
                    },
                }),
            /changed during build/,
        );
        assert.equal(
            await readFile(join(dist, "release.json"), "utf8"),
            before,
        );
        assert.equal(isCurrentRelease(dist, JSON.parse(before).version), true);
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});

test("failed directory swap restores the previous dist", async () => {
    const { root, web } = await fixture();
    const destination = join(web, "dist");
    const stage = join(web, "stage");
    try {
        await mkdir(destination);
        await mkdir(stage);
        await writeFile(join(destination, "index.html"), "old frontend");
        await writeFile(join(stage, "index.html"), "new frontend");
        let failedOnce = false;
        assert.throws(
            () =>
                publishDirectory(stage, destination, (from, to) => {
                    if (from === stage && !failedOnce) {
                        failedOnce = true;
                        throw new Error("synthetic rename failure");
                    }
                    renameSync(from, to);
                }),
            /synthetic rename failure/,
        );
        assert.equal(
            await readFile(join(destination, "index.html"), "utf8"),
            "old frontend",
        );
    } finally {
        await rm(root, { recursive: true, force: true });
    }
});
