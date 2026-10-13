import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import {
    mkdir,
    mkdtemp,
    rm,
    symlink,
    unlink,
    writeFile,
} from "node:fs/promises";
import { join, resolve } from "node:path";
import test from "node:test";
import {
    copyReports,
    handleReportRequest,
    listReports,
    parseReportMeta,
    resolveReportFile,
} from "./research-reports.mjs";

const page = (
    title,
    date,
    extra = "",
) => `<!doctype html><html><head><title>fallback</title>
<meta name="report:title" content="${title}" />
<meta content="2019 – 2026" name="report:period">
<meta name="report:date" content="${date}" />
<meta name="report:tags" content="HHHL, 型態 ,," />
<meta name="report:status" content='demo' />${extra}
</head><body></body></html>`;

async function scratchTasks() {
    const scratch = resolve("../.tmp");
    await mkdir(scratch, { recursive: true });
    const root = await mkdtemp(join(scratch, "research-reports-"));
    const report = async (id, html) => {
        const folder = join(root, id, "web-report");
        await mkdir(join(folder, "data"), { recursive: true });
        await writeFile(join(folder, "index.html"), html);
        await writeFile(
            join(folder, "data", "summary.js"),
            "window.REPORT_DATA = {};",
        );
    };
    return { root, report };
}

function fakeResponse() {
    const headers = {};
    return {
        statusCode: 200,
        headers,
        body: null,
        setHeader(name, value) {
            headers[name.toLowerCase()] = value;
        },
        end(body) {
            this.body = body;
        },
    };
}

test("meta tags are read in any attribute order, with entities and trimmed tags", () => {
    const meta = parseReportMeta(page("A &amp; B", "2026-10-12"));
    assert.equal(meta.title, "A & B");
    assert.equal(meta.period, "2019 – 2026");
    assert.equal(meta.status, "demo");
    assert.deepEqual(meta.tags, ["HHHL", "型態"]);
    assert.equal(
        parseReportMeta("<title>Only title</title>").title,
        "Only title",
    );
});

test("reports are discovered from tasks/*/web-report, newest first, and others ignored", async () => {
    const { root, report } = await scratchTasks();
    try {
        await report("20261001-old", page("Old", "2026-10-01"));
        await report("20261012-new", page("New", "2026-10-12"));
        await mkdir(join(root, "20261005-no-report"), { recursive: true });
        await mkdir(join(root, "20261006-empty", "web-report"), {
            recursive: true,
        });
        assert.deepEqual(
            listReports(root).map((r) => r.id),
            ["20261012-new", "20261001-old"],
        );
        assert.deepEqual(listReports(join(root, "missing")), []);
    } finally {
        await rm(root, { recursive: true });
    }
});

test("only files inside one report folder are served; traversal and bad ids are refused", async () => {
    const { root, report } = await scratchTasks();
    try {
        await report("20261012-new", page("New", "2026-10-12"));
        await writeFile(join(root, "secret.txt"), "secret");
        const ok = resolveReportFile(root, "20261012-new", "data/summary.js");
        assert.ok(ok?.endsWith(join("web-report", "data", "summary.js")));
        assert.ok(
            resolveReportFile(root, "20261012-new", "")?.endsWith("index.html"),
        );
        for (const bad of [
            "../../secret.txt",
            "..%2F..%2Fsecret.txt",
            "%2e%2e/%2e%2e/secret.txt",
            "/etc/passwd",
            "C:/Windows/win.ini",
            "data/",
            "missing.js",
            "%zz",
        ])
            assert.equal(
                resolveReportFile(root, "20261012-new", bad),
                null,
                bad,
            );
        assert.equal(resolveReportFile(root, "..", "secret.txt"), null);
        assert.equal(
            resolveReportFile(root, "20261012-new/../x", "index.html"),
            null,
        );

        const index = fakeResponse();
        assert.equal(
            handleReportRequest(root, "/reports/index.json?x=1", index),
            true,
        );
        assert.equal(JSON.parse(index.body).reports[0].id, "20261012-new");
        const file = fakeResponse();
        handleReportRequest(
            root,
            "/reports/20261012-new/data/summary.js",
            file,
        );
        assert.equal(
            file.headers["content-type"],
            "text/javascript; charset=utf-8",
        );
        const refused = fakeResponse();
        handleReportRequest(
            root,
            "/reports/20261012-new/..%2F..%2Fsecret.txt",
            refused,
        );
        assert.equal(refused.statusCode, 404);
        assert.equal(
            handleReportRequest(root, "/history-api/x", fakeResponse()),
            false,
        );
    } finally {
        await rm(root, { recursive: true });
    }
});

test("a build copies every report folder with its generated index", async () => {
    const { root, report } = await scratchTasks();
    const out = join(root, "..", `${root.split(/[\\/]/).pop()}-dist`);
    try {
        await report("20261012-new", page("New", "2026-10-12"));
        copyReports(root, out);
        assert.ok(
            existsSync(
                join(out, "reports", "20261012-new", "data", "summary.js"),
            ),
        );
        const index = JSON.parse(
            readFileSync(join(out, "reports", "index.json"), "utf8"),
        );
        assert.deepEqual(
            index.reports.map((r) => r.id),
            ["20261012-new"],
        );
    } finally {
        await rm(root, { recursive: true });
        await rm(out, { recursive: true, force: true });
    }
});

// Links are made only inside a synthetic scratch folder. A directory link uses a
// junction, which Windows allows without extra privileges; a file symlink may need
// Developer Mode, so that one case is skipped when the OS refuses to create it.
async function link(target, path, type) {
    try {
        await symlink(target, path, type);
        return true;
    } catch (error) {
        if (error.code === "EPERM" || error.code === "EACCES") return false;
        throw error;
    }
}

test("links are refused anywhere on a report path, matching the build copy", async (t) => {
    const { root, report } = await scratchTasks();
    const outside = `${root}-outside`;
    const out = `${root}-dist`;
    const links = [];
    try {
        await report("20261012-real", page("Real", "2026-10-12"));
        const folder = join(root, "20261012-real", "web-report");
        await mkdir(join(outside, "web-report"), { recursive: true });
        await writeFile(join(outside, "secret.txt"), "secret");
        await writeFile(
            join(outside, "web-report", "index.html"),
            page("Linked task", "2026-10-13"),
        );

        // A junction inside a report, to its own data folder and to outside it.
        for (const [name, target] of [
            ["data-link", join(folder, "data")],
            ["escape", outside],
        ]) {
            await symlink(target, join(folder, name), "junction");
            links.push(join(folder, name));
        }
        // A task folder that is itself a junction to a folder holding a report.
        await symlink(outside, join(root, "20261013-linked"), "junction");
        links.push(join(root, "20261013-linked"));

        assert.ok(resolveReportFile(root, "20261012-real", "data/summary.js"));
        assert.equal(
            resolveReportFile(root, "20261012-real", "data-link/summary.js"),
            null,
        );
        assert.equal(
            resolveReportFile(root, "20261012-real", "escape/secret.txt"),
            null,
        );
        assert.equal(
            resolveReportFile(root, "20261013-linked", "index.html"),
            null,
        );
        assert.deepEqual(
            listReports(root).map((r) => r.id),
            ["20261012-real"],
        );

        if (
            await link(
                join(folder, "data", "summary.js"),
                join(folder, "file-link.js"),
                "file",
            )
        ) {
            links.push(join(folder, "file-link.js"));
            assert.equal(
                resolveReportFile(root, "20261012-real", "file-link.js"),
                null,
            );
        } else
            t.diagnostic(
                "file symlink not permitted here; directory junctions still covered",
            );

        copyReports(root, out);
        assert.ok(
            existsSync(
                join(out, "reports", "20261012-real", "data", "summary.js"),
            ),
        );
        for (const name of ["data-link", "escape", "file-link.js"])
            assert.equal(
                existsSync(join(out, "reports", "20261012-real", name)),
                false,
                name,
            );
        assert.equal(
            existsSync(join(out, "reports", "20261013-linked")),
            false,
        );
    } finally {
        // Remove the links themselves first so no cleanup can walk through them.
        for (const path of links.reverse())
            await rm(path, { force: true, recursive: false }).catch(() =>
                unlink(path),
            );
        await rm(root, { recursive: true, force: true });
        await rm(outside, { recursive: true, force: true });
        await rm(out, { recursive: true, force: true });
    }
});
