import { createHash, randomUUID } from "node:crypto";
import {
    existsSync,
    lstatSync,
    mkdirSync,
    readFileSync,
    readdirSync,
    renameSync,
    rmSync,
    writeFileSync,
} from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { listReports } from "./research-reports.mjs";

const webRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const repoRoot = dirname(webRoot);
const dist = join(webRoot, "dist");
const VERSION_SCHEMA = "research-web-release.v1";

function addTree(hash, root, base, filter = () => true) {
    if (!existsSync(root)) return;
    const visit = (folder) => {
        for (const name of readdirSync(folder).sort()) {
            const path = join(folder, name);
            const stat = lstatSync(path);
            if (stat.isSymbolicLink()) continue;
            if (stat.isDirectory()) visit(path);
            else if (stat.isFile() && filter(path)) {
                hash.update(relative(base, path).replaceAll("\\", "/"));
                hash.update("\0");
                hash.update(readFileSync(path));
                hash.update("\0");
            }
        }
    };
    visit(root);
}

export function sourceVersion(root = repoRoot) {
    const hash = createHash("sha256");
    const web = join(root, "research_web");
    for (const path of [
        join(web, "src"),
        join(web, "public"),
        join(web, "scripts", "build-dashboard.mjs"),
        join(web, "scripts", "research-reports.mjs"),
        join(web, "vite.config.ts"),
        join(web, "index.html"),
        join(web, "package.json"),
        join(web, "package-lock.json"),
        join(web, "tsconfig.json"),
        join(web, "tsconfig.app.json"),
        join(web, "tsconfig.node.json"),
        join(web, ".env"),
        join(web, ".env.local"),
        join(web, ".env.production"),
        join(web, ".env.production.local"),
    ]) {
        if (existsSync(path) && lstatSync(path).isDirectory())
            addTree(hash, path, root);
        else if (existsSync(path)) {
            hash.update(relative(root, path).replaceAll("\\", "/"));
            hash.update("\0");
            hash.update(readFileSync(path));
            hash.update("\0");
        }
    }
    hash.update("mode:production\0");
    for (const name of ["VITE_ARTIFACT_MODE", "VITE_API_BASE"]) {
        hash.update(
            `${name}=${JSON.stringify({
                present: Object.hasOwn(process.env, name),
                value: process.env[name],
            })}\0`,
        );
    }
    const reportsRoot = join(root, "tasks");
    for (const report of listReports(reportsRoot))
        addTree(hash, join(reportsRoot, report.id, "web-report"), root);
    return hash.digest("hex");
}

function readReleaseVersion(directory) {
    try {
        const release = JSON.parse(
            readFileSync(join(directory, "release.json"), "utf8"),
        );
        const index = JSON.parse(
            readFileSync(join(directory, "reports", "index.json"), "utf8"),
        );
        const html = readFileSync(join(directory, "index.html"), "utf8");
        if (
            release.schema === VERSION_SCHEMA &&
            index.schema === "research-reports.v1" &&
            release.version === index.version &&
            ["public-synthetic", "local-private"].includes(
                release.artifactMode,
            ) &&
            html.includes(
                `name="research-web-version" content="${release.version}"`,
            )
        )
            return release.version;
    } catch {}
    return null;
}

/** Validate the data mode Vite baked into the frontend (artifact-mode.json in the stage). */
export function releaseArtifactMode(value) {
    if (!value || value === "public-synthetic") return "public-synthetic";
    if (value === "local-private") return value;
    throw new Error(
        "Unknown VITE_ARTIFACT_MODE; use public-synthetic or local-private.",
    );
}

function stagedArtifactMode(stage) {
    const recorded = JSON.parse(
        readFileSync(join(stage, "artifact-mode.json"), "utf8"),
    );
    return releaseArtifactMode(recorded.artifactMode);
}

export function isCurrentRelease(directory = dist, version = sourceVersion()) {
    return readReleaseVersion(directory) === version;
}

export function publishDirectory(stage, destination, rename = renameSync) {
    const backup = `${destination}.previous-${randomUUID()}`;
    const hadDestination = existsSync(destination);
    if (hadDestination) rename(destination, backup);
    try {
        rename(stage, destination);
    } catch (error) {
        if (hadDestination) rename(backup, destination);
        throw error;
    }
    if (hadDestination) rmSync(backup, { recursive: true, force: true });
}

export function ensureRelease({ root = repoRoot, build = buildStage } = {}) {
    const version = sourceVersion(root);
    const destination = join(root, "research_web", "dist");
    if (isCurrentRelease(destination, version)) {
        console.log(`[dashboard] dist is current (${version.slice(0, 12)})`);
        return "current";
    }
    const stage = join(
        root,
        "research_web",
        `.dist-stage-${process.pid}-${randomUUID()}`,
    );
    mkdirSync(stage, { recursive: true });
    try {
        build(root, stage, version);
        if (sourceVersion(root) !== version)
            throw new Error(
                "frontend sources, reports, or build settings changed during build; previous dist was preserved",
            );
        writeFileSync(
            join(stage, "release.json"),
            JSON.stringify({
                schema: VERSION_SCHEMA,
                version,
                artifactMode: stagedArtifactMode(stage),
            }),
        );
        if (readReleaseVersion(stage) !== version)
            throw new Error(
                "staged frontend and report index versions do not match",
            );
        publishDirectory(stage, destination);
        console.log(`[dashboard] published ${version.slice(0, 12)}`);
        return "built";
    } catch (error) {
        rmSync(stage, { recursive: true, force: true });
        throw error;
    }
}

export function hasBuildDependencies(webRoot) {
    const packageJson = JSON.parse(
        readFileSync(join(webRoot, "package.json"), "utf8"),
    );
    const dependencies = [
        ...Object.keys(packageJson.dependencies ?? {}),
        ...Object.keys(packageJson.devDependencies ?? {}),
    ];
    return (
        dependencies.length > 0 &&
        dependencies.every((name) =>
            existsSync(join(webRoot, "node_modules", name, "package.json")),
        )
    );
}

function buildStage(root, stage, version) {
    const npm = process.platform === "win32" ? "npm.cmd" : "npm";
    const webRoot = join(root, "research_web");
    const options = {
        cwd: webRoot,
        stdio: "inherit",
        shell: process.platform === "win32",
    };
    if (!hasBuildDependencies(webRoot)) {
        const install = spawnSync(npm, ["ci"], options);
        if (install.error) throw install.error;
        if (install.status !== 0)
            throw new Error(
                `frontend dependency installation failed (${install.status ?? install.signal})`,
            );
    }
    const result = spawnSync(npm, ["run", "build:stage"], {
        ...options,
        env: {
            ...process.env,
            RESEARCH_WEB_BUILD_OUT_DIR: stage,
            RESEARCH_WEB_VERSION: version,
            VITE_RESEARCH_WEB_VERSION: version,
        },
    });
    if (result.error) throw result.error;
    if (result.status !== 0)
        throw new Error(
            `frontend build failed (${result.status ?? result.signal})`,
        );
}

if (
    process.argv[1] &&
    resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
    try {
        ensureRelease();
    } catch (error) {
        console.error(
            `[dashboard] build failed; existing dist was preserved: ${error.message}`,
        );
        process.exitCode = 1;
    }
}
