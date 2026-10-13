// Discover and serve AI-written research reports: tasks/<task-id>/web-report/index.html.
// Each report is a self-contained folder (index.html, kit/, data/). The studio lists
// them from <meta name="report:*"> tags and shows them in a sandboxed iframe; no
// hand-maintained catalogue exists. Used by vite.config.ts and its functional test.
import {
    cpSync,
    existsSync,
    lstatSync,
    mkdirSync,
    readdirSync,
    readFileSync,
    realpathSync,
    writeFileSync,
} from "node:fs";
import { extname, isAbsolute, join, relative } from "node:path";

export const REPORT_FOLDER = "web-report";
const REPORT_ID = /^[A-Za-z0-9][A-Za-z0-9._-]*$/;
const META_KEYS = [
    "title",
    "summary",
    "date",
    "status",
    "tags",
    "period",
    "kit",
];

const CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
};

function decodeEntities(text) {
    return text
        .replace(/&quot;/g, '"')
        .replace(/&#39;/g, "'")
        .replace(/&lt;/g, "<")
        .replace(/&gt;/g, ">")
        .replace(/&amp;/g, "&");
}

function attribute(tag, name) {
    const match = tag.match(
        new RegExp(`\\b${name}\\s*=\\s*("([^"]*)"|'([^']*)')`, "i"),
    );
    return match ? decodeEntities(match[2] ?? match[3] ?? "") : null;
}

/** Read the report:* meta tags and <title> of one report's index.html. */
export function parseReportMeta(html) {
    const meta = {};
    for (const tag of html.match(/<meta\b[^>]*>/gi) ?? []) {
        const name = attribute(tag, "name");
        if (!name?.startsWith("report:")) continue;
        const key = name.slice("report:".length);
        if (META_KEYS.includes(key))
            meta[key] = attribute(tag, "content") ?? "";
    }
    const title = html.match(/<title>([\s\S]*?)<\/title>/i);
    return {
        title: meta.title || (title ? decodeEntities(title[1].trim()) : ""),
        summary: meta.summary ?? "",
        date: meta.date ?? "",
        status: meta.status ?? "",
        period: meta.period ?? "",
        kit: meta.kit ?? "",
        tags: (meta.tags ?? "")
            .split(",")
            .map((tag) => tag.trim())
            .filter(Boolean),
    };
}

/** The entry's own type, without following a symlink or Windows junction. */
function entryKind(path) {
    try {
        const stat = lstatSync(path);
        if (stat.isSymbolicLink()) return "link";
        if (stat.isDirectory()) return "directory";
        return stat.isFile() ? "file" : "other";
    } catch {
        return "missing";
    }
}

/**
 * Walk from tasksRoot through each named segment, checking every entry before it is
 * entered. Any symlink or junction on the way (the task folder, web-report, a
 * subfolder or the file itself) rejects the path, so the dev server, the build copy
 * and the index all see the same set of plain files. Returns the path or null.
 */
function plainPath(tasksRoot, segments, finalKind) {
    let path = tasksRoot;
    for (const [index, segment] of segments.entries()) {
        path = join(path, segment);
        const expected =
            index === segments.length - 1 ? finalKind : "directory";
        if (entryKind(path) !== expected) return null;
    }
    return path;
}

/** List every report under tasksRoot, newest date first. Links are never followed. */
export function listReports(tasksRoot) {
    if (!existsSync(tasksRoot)) return [];
    const reports = [];
    for (const name of readdirSync(tasksRoot)) {
        if (!REPORT_ID.test(name)) continue;
        const index = plainPath(
            tasksRoot,
            [name, REPORT_FOLDER, "index.html"],
            "file",
        );
        if (!index) continue;
        reports.push({
            id: name,
            ...parseReportMeta(readFileSync(index, "utf8")),
        });
    }
    return reports.sort(
        (a, b) => b.date.localeCompare(a.date) || a.id.localeCompare(b.id),
    );
}

/**
 * Resolve a requested file inside one report folder, or null. Rejects unknown ids,
 * empty, "." and ".." segments, absolute paths, and any symlink or junction on the
 * way, checked before the path is resolved. The real path must still stay inside
 * the report folder as a second guard.
 */
export function resolveReportFile(tasksRoot, id, requestPath) {
    if (!REPORT_ID.test(id)) return null;
    let rel;
    try {
        rel = decodeURIComponent(requestPath || "index.html");
    } catch {
        return null;
    }
    if (rel === "" || rel.endsWith("/")) rel += "index.html";
    if (rel.includes("\0") || /^[\\/]|^[A-Za-z]:/.test(rel)) return null;
    const parts = rel.split(/[\\/]/);
    if (parts.some((part) => part === "" || part === "." || part === ".."))
        return null;
    const file = plainPath(tasksRoot, [id, REPORT_FOLDER, ...parts], "file");
    if (!file) return null;
    try {
        const inside = relative(
            realpathSync(join(tasksRoot, id, REPORT_FOLDER)),
            realpathSync(file),
        );
        if (!inside || inside.startsWith("..") || isAbsolute(inside))
            return null;
    } catch {
        return null;
    }
    return file;
}

export function contentType(path) {
    return (
        CONTENT_TYPES[extname(path).toLowerCase()] ?? "application/octet-stream"
    );
}

/** Handle /reports/index.json and /reports/<id>/<path>; returns false when not ours. */
export function handleReportRequest(tasksRoot, url, response) {
    const path = (url ?? "").split("?")[0].split("#")[0];
    if (!path.startsWith("/reports/")) return false;
    const rest = path.slice("/reports/".length);
    if (rest === "index.json") {
        response.setHeader("Content-Type", CONTENT_TYPES[".json"]);
        response.setHeader("Cache-Control", "no-store");
        response.end(
            JSON.stringify({
                schema: "research-reports.v1",
                reports: listReports(tasksRoot),
            }),
        );
        return true;
    }
    const slash = rest.indexOf("/");
    const id = slash === -1 ? rest : rest.slice(0, slash);
    const file = resolveReportFile(
        tasksRoot,
        id,
        slash === -1 ? "" : rest.slice(slash + 1),
    );
    if (!file) {
        response.statusCode = 404;
        response.end("report file not found");
        return true;
    }
    response.setHeader("Content-Type", contentType(file));
    response.setHeader("Cache-Control", "no-cache");
    response.end(readFileSync(file));
    return true;
}

/** Copy every report folder into <outDir>/reports/ with its generated index. */
export function copyReports(tasksRoot, outDir) {
    const reports = listReports(tasksRoot);
    for (const report of reports)
        cpSync(
            join(tasksRoot, report.id, REPORT_FOLDER),
            join(outDir, "reports", report.id),
            {
                recursive: true,
                dereference: false,
                errorOnExist: false,
                filter: (source) => !lstatSync(source).isSymbolicLink(),
            },
        );
    mkdirSync(join(outDir, "reports"), { recursive: true });
    writeFileSync(
        join(outDir, "reports", "index.json"),
        JSON.stringify({ schema: "research-reports.v1", reports }),
    );
    return reports;
}
