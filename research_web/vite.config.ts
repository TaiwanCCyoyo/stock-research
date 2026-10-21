import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { resolve } from "node:path";
// @ts-expect-error Plain Node module also used by the functional guard test.
import { assertNoPrivatePublicCandidates } from "./scripts/private-public-guard.mjs";
// @ts-expect-error Plain Node module also used by its functional test.
import * as reports from "./scripts/research-reports.mjs";

// AI-written reports live beside their studies: tasks/<task-id>/web-report/.
const tasksRoot = fileURLToPath(new URL("../tasks", import.meta.url));
let buildOutDir = "";
const releaseVersion = process.env.RESEARCH_WEB_VERSION ?? "development";

// https://vite.dev/config/
export default defineConfig(({ command }) => {
    if (command === "build" && !process.env.RESEARCH_WEB_BUILD_OUT_DIR)
        throw new Error(
            "Run npm run build to stage and publish the frontend safely.",
        );
    return {
        plugins: [
            react(),
            {
                name: "research-web-release-version",
                transformIndexHtml(html) {
                    return reports.stampIndexHtml(html, releaseVersion);
                },
            },
            {
                name: "private-presentation-build-guard",
                buildStart() {
                    assertNoPrivatePublicCandidates(
                        fileURLToPath(new URL("./public", import.meta.url)),
                    );
                },
            },
            {
                name: "research-reports",
                configResolved(config) {
                    buildOutDir = resolve(config.root, config.build.outDir);
                },
                // Registered directly (not as a post hook) so report HTML is served
                // untouched, before Vite's HTML transform could inject its client.
                configureServer(server) {
                    server.middlewares.use((request, response, next) => {
                        if (
                            !reports.handleReportRequest(
                                tasksRoot,
                                request.url,
                                response,
                                releaseVersion,
                            )
                        )
                            next();
                    });
                },
                closeBundle() {
                    if (buildOutDir)
                        reports.copyReports(
                            tasksRoot,
                            buildOutDir,
                            releaseVersion,
                        );
                },
            },
            {
                name: "research-checkout-identity",
                configureServer(server) {
                    server.middlewares.use(
                        "/__research_service__",
                        (_request, response) => {
                            response.setHeader(
                                "Content-Type",
                                "application/json",
                            );
                            response.end(
                                JSON.stringify({
                                    schema: "stock-research-service.v1",
                                    service: "research-web",
                                    dataMode:
                                        process.env.VITE_ARTIFACT_MODE ??
                                        "public-synthetic",
                                    apiTarget:
                                        process.env.RESEARCH_WEB_API_TARGET ??
                                        "http://127.0.0.1:8517",
                                    projectRoot: fileURLToPath(
                                        new URL("..", import.meta.url),
                                    ),
                                }),
                            );
                        },
                    );
                },
            },
        ],
        server: {
            // The one-command launcher serves both historical and research routes.
            // An explicitly configured older API can still be used for /api.
            proxy: {
                "/history-api": {
                    target:
                        process.env.RESEARCH_WEB_API_TARGET ??
                        "http://127.0.0.1:8517",
                    changeOrigin: true,
                },
                "/api": {
                    target:
                        process.env.RESEARCH_WEB_API_TARGET ??
                        "http://127.0.0.1:8517",
                    changeOrigin: true,
                    rewrite: (path) => path.replace(/^\/api/, ""),
                },
            },
        },
        build: {
            outDir: process.env.RESEARCH_WEB_BUILD_OUT_DIR,
        },
    };
});
