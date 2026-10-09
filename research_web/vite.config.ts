import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
// @ts-expect-error Plain Node module also used by the functional guard test.
import { assertNoPrivatePublicCandidates } from "./scripts/private-public-guard.mjs";

// https://vite.dev/config/
export default defineConfig({
    plugins: [
        react(),
        {
            name: "private-presentation-build-guard",
            buildStart() {
                assertNoPrivatePublicCandidates(
                    fileURLToPath(new URL("./public", import.meta.url)),
                );
            },
        },
        {
            name: "research-checkout-identity",
            configureServer(server) {
                server.middlewares.use(
                    "/__research_service__",
                    (_request, response) => {
                        response.setHeader("Content-Type", "application/json");
                        response.end(
                            JSON.stringify({
                                schema: "stock-research-service.v1",
                                service: "research-web",
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
                target: "http://127.0.0.1:8517",
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
});
