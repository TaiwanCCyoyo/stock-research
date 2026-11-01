import { useEffect, useRef, useState } from "react";
import { reportFrameSrc, statusLabel } from "./model";
import { useReportIndex } from "./useReportIndex";
import { SourceInfo } from "../../components/ui/primitives";
import "./reports.css";
import { MarkdownReport } from "./MarkdownReport";
import { useStudyCards } from "../studies/useStudyCards";
import { currentStudyHash, studiesBack } from "../studies/reading";

/**
 * Shows one report in its own framed document, so its CSS cannot restyle the studio
 * and its layout cannot break the studio page.
 *
 * Trust boundary: the frame keeps the studio's origin (allow-scripts together with
 * allow-same-origin), so a report's JavaScript CAN reach the studio page, its
 * storage and its API, exactly like studio code. Only repository-authored reports,
 * reviewed like code, may be shown here; never point this at untrusted HTML.
 * The shell itself listens only to rk:* messages whose source is this frame.
 *
 * Why not a fully sandboxed (opaque-origin) frame: in the Claude desktop app's
 * built-in Chromium browser (tested 2026-10-13), such a frame could not load
 * scripts, images or fetch anything from 127.0.0.1, which left a report without its
 * kit and data. Other browsers were not tested. No popup permission is granted;
 * reports open nothing in new windows. Retained result links may download files.
 */
export function ReportViewer({
    reportId,
    palette,
    appearance,
}: {
    reportId: string;
    palette: string;
    appearance: string;
}) {
    const studies = useStudyCards();
    const card = studies.cards?.find((item) => item.id === reportId);
    const requested =
        new URLSearchParams(currentStudyHash().split("?")[1] ?? "").get(
            "view",
        ) === "reading";
    if (requested || card?.reading?.edition)
        return <MarkdownReport reportId={reportId} />;
    return (
        <HtmlReportViewer
            reportId={reportId}
            palette={palette}
            appearance={appearance}
        />
    );
}

function HtmlReportViewer({
    reportId,
    palette,
    appearance,
}: {
    reportId: string;
    palette: string;
    appearance: string;
}) {
    const { reports, error } = useReportIndex();
    const report = reports?.find((r) => r.id === reportId);
    const frame = useRef<HTMLIFrameElement>(null);
    // The first-paint theme is fixed in the URL; later changes are posted, so the
    // frame never reloads (and loses its state) when the viewer changes the theme.
    const [src] = useState(() => reportFrameSrc(reportId, palette, appearance));
    const [height, setHeight] = useState<number | null>(null);
    const [loaded, setLoaded] = useState(false);
    const [timedOut, setTimedOut] = useState(false);
    const [attempt, setAttempt] = useState(0);
    useEffect(() => {
        const timer = setTimeout(() => setTimedOut(true), 20000);
        return () => clearTimeout(timer);
    }, [attempt]);

    useEffect(() => {
        const receive = (event: MessageEvent) => {
            // Trust only messages from our own frame, whatever their origin reports.
            if (event.source !== frame.current?.contentWindow) return;
            const data = event.data as { type?: string; height?: number };
            if (
                data?.type === "rk:height" &&
                typeof data.height === "number" &&
                data.height > 0
            )
                setHeight(Math.min(Math.ceil(data.height), 200_000));
        };
        window.addEventListener("message", receive);
        return () => window.removeEventListener("message", receive);
    }, []);

    useEffect(() => {
        frame.current?.contentWindow?.postMessage(
            { type: "rk:theme", palette, appearance },
            "*",
        );
    }, [palette, appearance]);

    return (
        <div className="rv-page">
            <div className="rv-bar u-card">
                <a
                    className="rv-back u-btn"
                    href={studiesBack(currentStudyHash())}
                >
                    ← 研究
                </a>
                <div className="rv-title">
                    <strong>{report?.title || "研究報告"}</strong>
                    <span>
                        {report?.date && <span>{report.date}</span>}
                        {report?.period && (
                            <span>資料期間 {report.period}</span>
                        )}
                        {report && <span>{statusLabel(report.status)}</span>}
                    </span>
                </div>
                <a
                    className="rv-open u-btn"
                    href={src}
                    target="_blank"
                    rel="noreferrer"
                >
                    在新分頁開啟 ↗
                </a>
            </div>
            <p className="u-notice">
                歷史網頁原文；閱讀版尚未完成核對。請留意研究限制。
            </p>
            {error && (
                <div role="alert" className="u-notice">
                    <p>報告清單暫時無法讀取。</p>
                    <SourceInfo>
                        <p>{error}</p>
                    </SourceInfo>
                    <button
                        className="u-btn"
                        onClick={() => window.location.reload()}
                    >
                        重新讀取
                    </button>
                </div>
            )}
            {reports && !report && (
                <div role="alert" className="u-notice">
                    <p>找不到這份報告，請返回研究頁選擇其他報告。</p>
                    <SourceInfo>
                        <p>報告識別：{reportId}</p>
                        <p>
                            預期位置：<code>tasks/{reportId}/web-report/</code>
                        </p>
                    </SourceInfo>
                </div>
            )}
            {(!reports || report) && (
                <>
                    {!loaded && <p role="status">正在載入網頁報告…</p>}
                    {!loaded && timedOut && (
                        <div role="alert">
                            <p>報告尚未載入，可能是服務暫時無法使用。</p>
                            <button
                                className="u-btn"
                                onClick={() => {
                                    setTimedOut(false);
                                    setLoaded(false);
                                    setAttempt((n) => n + 1);
                                }}
                            >
                                重試報告
                            </button>
                        </div>
                    )}
                    <iframe
                        key={attempt}
                        ref={frame}
                        className="rv-frame"
                        title={report?.title || reportId}
                        src={src}
                        sandbox="allow-scripts allow-same-origin allow-downloads"
                        referrerPolicy="no-referrer"
                        style={height ? { height } : undefined}
                        onLoad={() => {
                            setLoaded(true);
                            frame.current?.contentWindow?.postMessage(
                                { type: "rk:theme", palette, appearance },
                                "*",
                            );
                        }}
                        onError={() => {
                            setLoaded(false);
                            setTimedOut(true);
                        }}
                    />
                </>
            )}
        </div>
    );
}
