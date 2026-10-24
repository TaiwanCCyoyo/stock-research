import { useCallback, useEffect, useState } from "react";
import { SourceInfo } from "../../components/ui/primitives";
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

    if (state.status === "synthetic") return null;

    return (
        <section className="ss-shared-status" aria-label="共用行情資料來源">
            {state.status === "loading" && (
                <p className="ss-muted" role="status">
                    正在讀取行情來源…
                </p>
            )}
            {state.status === "failure" && (
                <div role="alert">
                    <p className="ss-muted">
                        行情來源暫時無法讀取，仍可查看已保存的研究。
                    </p>
                    <SourceInfo>
                        <p>{state.message}</p>
                    </SourceInfo>
                    <button
                        className="ss-button u-btn"
                        type="button"
                        onClick={() => void load()}
                    >
                        重新讀取
                    </button>
                </div>
            )}
            {state.status === "available" && (
                <SourceInfo label="共用行情資料來源">
                    <p>這是目前共用行情的狀態，與本頁已保存的研究期間不同。</p>
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
                </SourceInfo>
            )}
        </section>
    );
}
