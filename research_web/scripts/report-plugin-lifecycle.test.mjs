import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { join, resolve } from "node:path";
import test from "node:test";
import { researchReportsPlugin } from "../vite.config.ts";

async function fixture(t) {
    const scratch = resolve("../.tmp");
    await mkdir(scratch, { recursive: true });
    const root = await mkdtemp(join(scratch, "report-plugin-lifecycle-"));
    t.after(() => rm(root, { recursive: true, force: true }));
    const tasks = join(root, "tasks");
    const out = join(root, "dist");
    await mkdir(join(tasks, "example", "web-report"), { recursive: true });
    await writeFile(
        join(tasks, "example", "web-report", "index.html"),
        '<html><head><meta name="report:title" content="Example"></head></html>',
    );
    await mkdir(join(out, "reports"), { recursive: true });
    const savedIndex = JSON.stringify({
        version: "saved-release",
        reports: [],
    });
    await writeFile(join(out, "reports", "index.json"), savedIndex);
    await writeFile(join(out, "index.html"), "saved-release-shell");
    return { root, tasks, out, savedIndex };
}

// Invoke the hooks as Vite/Rollup does, with no listener or real report inputs.
async function hook(plugin, name, ...args) {
    const entry = plugin[name];
    const handler = typeof entry === "function" ? entry : entry?.handler;
    if (handler) await handler.apply({}, args);
}

async function assertSaved(f) {
    assert.equal(
        await readFile(join(f.out, "reports", "index.json"), "utf8"),
        f.savedIndex,
    );
    assert.equal(
        await readFile(join(f.out, "index.html"), "utf8"),
        "saved-release-shell",
    );
}

for (const mode of ["development", "production"]) {
    test(`${mode} serve teardown preserves the existing production report index`, async (t) => {
        const f = await fixture(t);
        const plugin = researchReportsPlugin(f.tasks, "development");
        await hook(plugin, "configResolved", {
            command: "serve",
            mode,
            root: f.root,
            build: { outDir: f.out },
        });
        await hook(plugin, "buildStart");
        await hook(plugin, "buildEnd");
        await hook(plugin, "closeBundle");
        await assertSaved(f);
    });
}

test("failed build and generate-only build do not replace saved reports", async (t) => {
    const f = await fixture(t);
    const plugin = researchReportsPlugin(f.tasks, "new-release");
    await hook(plugin, "configResolved", {
        command: "build",
        root: f.root,
        build: { outDir: f.out },
    });
    await hook(plugin, "buildStart");
    await hook(plugin, "buildEnd", new Error("failed to transform source"));
    await hook(plugin, "closeBundle");
    await assertSaved(f);
    await hook(plugin, "buildStart");
    await hook(plugin, "buildEnd");
    await hook(plugin, "closeBundle");
    await assertSaved(f);
});

test("successful output write includes reports with the build release version", async (t) => {
    const f = await fixture(t);
    const plugin = researchReportsPlugin(f.tasks, "new-release");
    await hook(plugin, "configResolved", {
        command: "build",
        root: f.root,
        build: { outDir: f.out },
    });
    await hook(plugin, "buildStart");
    await hook(plugin, "buildEnd");
    await hook(plugin, "writeBundle", {}, {});
    const index = JSON.parse(
        await readFile(join(f.out, "reports", "index.json"), "utf8"),
    );
    assert.equal(index.version, "new-release");
    assert.deepEqual(
        index.reports.map((report) => report.id),
        ["example"],
    );
    assert.match(
        await readFile(join(f.out, "reports", "example", "index.html"), "utf8"),
        /Example/,
    );
    // A watch rebuild failure must not inherit success from the preceding build.
    await hook(plugin, "buildStart");
    await hook(plugin, "buildEnd", new Error("watch rebuild failed"));
    await writeFile(join(f.out, "reports", "index.json"), f.savedIndex);
    await hook(plugin, "writeBundle", {}, {});
    await assertSaved(f);
});
