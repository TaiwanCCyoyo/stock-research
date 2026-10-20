import { useCallback, useEffect, useState } from "react";
import {
    initialSharedDataStatus,
    parseSharedGenerationMetadata,
    type SharedDataStatusState,
} from "./sharedGenerationState.ts";

const API_BASE: string = import.meta.env.VITE_API_BASE ?? "/api";
const ARTIFACT_MODE: string | undefined = import.meta.env.VITE_ARTIFACT_MODE;

/** Status of the maintained shared generation, separate from any study snapshot. */
export function SharedDataStatus() {
    const [state, setState] = useState<SharedDataStatusState>(() =>
        initialSharedDataStatus(ARTIFACT_MODE),
    );
    const load = useCallback(async () => {
        if (ARTIFACT_MODE !== "local-private") {
            setState({ status: "synthetic" });
            return;
        }
        setState({ status: "loading" });
        try {
            const response = await fetch(
                `${API_BASE}/private-artifacts/v1/shared-status`,
            );
            if (!response.ok) {
                let message = `HTTP ${response.status}`;
                try {
                    const body = await response.json();
                    if (typeof body.detail === "string") message = body.detail;
                } catch {
                    // Keep the HTTP status if the error body is not JSON.
                }
                throw new Error(message);
            }
            const metadata = parseSharedGenerationMetadata(
                await response.json(),
            );
            setState({ status: "available", metadata });
        } catch (error) {
            setState({
                status: "failure",
                message: error instanceof Error ? error.message : String(error),
            });
        }
    }, []);

    useEffect(() => {
        if (ARTIFACT_MODE === "local-private") void load();
    }, [load]);

    return (
        <section className="ss-card" aria-label="目前維護資料">
            <h2>目前維護資料（非本頁研究快照）</h2>
            {state.status === "synthetic" && (
                <p className="ss-muted">合成模式：未讀取私有共用來源。</p>
            )}
            {state.status === "loading" && (
                <p className="ss-muted" role="status">
                    正在讀取共用維護資料狀態…
                </p>
            )}
            {state.status === "failure" && (
                <div role="alert">
                    <p className="ss-muted">
                        共用維護資料狀態讀取失敗：{state.message}
                    </p>
                    <button
                        className="ss-button"
                        type="button"
                        onClick={() => void load()}
                    >
                        重新讀取
                    </button>
                </div>
            )}
            {state.status === "available" && (
                <dl className="ss-stat-list">
                    <div>
                        <dt>世代</dt>
                        <dd>{state.metadata.generation}</dd>
                    </div>
                    <div>
                        <dt>資料截至</dt>
                        <dd>{state.metadata.asof}</dd>
                    </div>
                    <div>
                        <dt>建立時間</dt>
                        <dd>{state.metadata.built_at_utc}</dd>
                    </div>
                </dl>
            )}
        </section>
    );
}
