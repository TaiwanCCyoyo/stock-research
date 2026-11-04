import { useMemo } from "react";
import { useDirectionResource } from "../direction-discussion/useDirectionResource";
import { HistoryChartDetail } from "./HistoryChartDetail";
import { readWaveContext, readWaveDetail, waveHref } from "./stockJourney";
import type { WaveContext } from "./stockJourney";

function SavedWave({ context }: { context: WaveContext }) {
    const load = useMemo(
        () => (signal: AbortSignal) => readWaveDetail(context, signal),
        [context],
    );
    const { state, retry } = useDirectionResource(
        JSON.stringify(context),
        load,
    );
    return (
        <div className="u-page">
            <a className="u-btn" href={waveHref(context, "market")}>
                返回原地圖波段
            </a>
            <h1>歷史波段個股檢視</h1>
            <p>事後波段，不是當日訊號。只讀指定來源，不使用現況行情補缺。</p>
            <dl style={{ overflowWrap: "anywhere" }}>
                <dt>區間／地圖觀察日</dt>
                <dd>
                    {context.from} → {context.to} ／ {context.date}
                </dd>
                <dt>價格基準</dt>
                <dd>{context.priceBasis}</dd>
                <dt>精確版本</dt>
                <dd>{context.catalogId}</dd>
                <dt>來源紀錄</dt>
                <dd>
                    {context.securityKey} ／ {context.securityId} ／{" "}
                    {context.seriesId} ／ {context.waveId}
                </dd>
            </dl>
            {state.status === "loading" && (
                <p role="status">正在核對歷史版本與波段價格…</p>
            )}
            {state.status === "error" && (
                <div>
                    <p role="alert">{state.message}</p>
                    <button onClick={retry}>重新核對</button>
                </div>
            )}
            {state.status === "loaded" && (
                <HistoryChartDetail
                    detail={state.data}
                    initialInterval={context}
                />
            )}
        </div>
    );
}
export function WaveStockPage({ hash }: { hash: string }) {
    let context;
    try {
        context = readWaveContext(hash);
        if (!context) throw new Error("缺少波段來源。");
    } catch (error) {
        return (
            <div className="u-page">
                <p role="alert">
                    {error instanceof Error
                        ? error.message
                        : "波段來源無法讀取。"}
                </p>
                <a href="#market">另行開啟地圖（不重播來源波段）</a>
            </div>
        );
    }
    return <SavedWave key={hash} context={context} />;
}
