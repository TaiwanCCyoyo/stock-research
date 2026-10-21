import { useEffect, useRef, useState } from "react";
import { reportFrameSrc, statusLabel } from "./model";
import { useReportIndex } from "./useReportIndex";
import "./reports.css";

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
    const { reports, error } = useReportIndex();
    const report = reports?.find((r) => r.id === reportId);
    const frame = useRef<HTMLIFrameElement>(null);
    // The first-paint theme is fixed in the URL; later changes are posted, so the
    // frame never reloads (and loses its state) when the viewer changes the theme.
    const [src] = useState(() => reportFrameSrc(reportId, palette, appearance));
    const [height, setHeight] = useState<number | null>(null);

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
            <div className="rv-bar">
                <a className="rv-back" href="#reports">
                    ← 研究報告
                </a>
                <div className="rv-title">
                    <strong>{report?.title || reportId}</strong>
                    <span>
                        {report?.date && <span>{report.date}</span>}
                        {report?.period && (
                            <span>資料期間 {report.period}</span>
                        )}
                        {report && <span>{statusLabel(report.status)}</span>}
                    </span>
                </div>
                <a
                    className="rv-open"
                    href={src}
                    target="_blank"
                    rel="noreferrer"
                >
                    在新分頁開啟 ↗
                </a>
            </div>
            {error && <p className="rp-notice">{error}</p>}
            {reports && !report && (
                <p className="rp-notice">
                    找不到報告「{reportId}」。它可能還沒放進{" "}
                    <code>tasks/{reportId}/web-report/</code>。
                </p>
            )}
            {(!reports || report) && (
                <iframe
                    ref={frame}
                    className="rv-frame"
                    title={report?.title || reportId}
                    src={src}
                    sandbox="allow-scripts allow-same-origin allow-downloads"
                    referrerPolicy="no-referrer"
                    style={height ? { height } : undefined}
                    onLoad={() =>
                        frame.current?.contentWindow?.postMessage(
                            { type: "rk:theme", palette, appearance },
                            "*",
                        )
                    }
                />
            )}
        </div>
    );
}
