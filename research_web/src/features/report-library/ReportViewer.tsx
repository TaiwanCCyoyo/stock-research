import {
    useCallback,
    useEffect,
    useLayoutEffect,
    useRef,
    useState,
} from "react";
import {
    reportFrameHeight,
    reportFrameSrc,
    reportNavigationHash,
    reportRevealRequest,
    revealReportEvidence,
    statusLabel,
} from "./model";
import { useReportIndex } from "./useReportIndex";
import { ReportIndexNotice } from "./ReportIndexNotice";
import { SourceInfo } from "../../components/ui/primitives";
import {
    applyReportThemeTokens,
    readReportThemeTokens,
    reportFrameThemeView,
    reportThemeMessage,
    type ReportFrameThemeState,
} from "./themeBridge";
import "./reports.css";
import { MarkdownReport } from "./MarkdownReport";
import { useStudyCards } from "../studies/useStudyCards";
import { currentStudyHash, studiesBack, reportView } from "../studies/reading";
import { ComparisonEntrance } from "../condition-comparison/ComparisonPage";
import { StudyDetailsView } from "../studies/StudyCardView";

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
    const index = useReportIndex();
    const card = studies.cards?.find((item) => item.id === reportId);
    const requested = new URLSearchParams(
        currentStudyHash().split("?")[1] ?? "",
    ).get("view");
    const view = reportView(
        requested,
        card?.reportKind,
        !!index.reports?.some((item) => item.id === reportId),
        !studies.cards && !studies.error,
    );
    if (view === "loading") return <p role="status">正在讀取報告…</p>;
    if (view === "reading")
        return (
            <MarkdownReport
                key={reportId}
                reportId={reportId}
                relatedStudies={studies.cards ?? []}
            />
        );
    if (view === "summary") {
        return (
            <article className="u-page reading-page">
                <a className="u-btn" href={studiesBack(currentStudyHash())}>
                    ← 返回研究列表
                </a>
                {!studies.cards ? (
                    studies.error ? (
                        <div role="alert">
                            <p>{studies.error}</p>
                            <button className="u-btn" onClick={studies.retry}>
                                重新讀取
                            </button>
                        </div>
                    ) : (
                        <p role="status">正在讀取研究紀錄…</p>
                    )
                ) : !card ? (
                    <p role="alert">目前無法找到這份研究紀錄。</p>
                ) : (
                    <>
                        <header className="reading-overview">
                            <p className="u-eyebrow">研究紀錄</p>
                            <h1>{card.question}</h1>
                            <p className="reading-answer">{card.answer}</p>
                            {card.limitation && (
                                <p className="reading-limitation">
                                    {card.limitation}
                                </p>
                            )}
                        </header>
                        <section className="u-card reading-source-gap">
                            <h2>目前保存的資料</h2>
                            <p>
                                {card.reading?.reason ||
                                    "尚未提供可核對的報告全文；本頁保留現有登錄資訊。"}
                            </p>
                            <p>這份紀錄尚不足以整理研究結論。</p>
                            <StudyDetailsView
                                details={card.details}
                                studyId={card.id}
                            />
                        </section>
                    </>
                )}
            </article>
        );
    }
    return (
        <HtmlReportViewer
            reportId={reportId}
            palette={palette}
            appearance={appearance}
        />
    );
}

export function HtmlReportViewer({
    reportId,
    palette,
    appearance,
}: {
    reportId: string;
    palette: string;
    appearance: string;
}) {
    const { reports, error, issue, loading, retry } = useReportIndex();
    const report = reports?.find((r) => r.id === reportId);
    const frame = useRef<HTMLIFrameElement>(null);
    // The report URL has a standalone forest fallback. Studio tokens are applied
    // after load; later palette changes never replace src or lose report state.
    const [src] = useState(() => reportFrameSrc(reportId, appearance));
    const standaloneSrc = reportFrameSrc(reportId, appearance);
    const [height, setHeight] = useState<number | null>(null);
    const [frameAttempt, setFrameAttempt] = useState(0);
    const [frameThemeState, setFrameThemeState] =
        useState<ReportFrameThemeState>("loading");
    const [frameThemeError, setFrameThemeError] = useState("");
    const [reveal, setReveal] = useState<{
        source: Window;
        document: Document;
    } | null>(null);
    const handledReveal = useRef<typeof reveal>(null);

    const applyFrameTheme = useCallback(() => {
        try {
            const studio = document.querySelector<HTMLElement>(".studio");
            const frameDocument = frame.current?.contentDocument;
            const child = frame.current?.contentWindow;
            if (!studio || !frameDocument?.documentElement || !child)
                throw new Error("同源報告文件目前無法存取");
            const computed = window.getComputedStyle(studio);
            const tokens = readReportThemeTokens((name) =>
                computed.getPropertyValue(name),
            );
            if (!tokens) throw new Error("研究室主題 token 不完整");
            applyReportThemeTokens(frameDocument.documentElement.style, tokens);
            frameDocument.documentElement.style.colorScheme = appearance;
            child.postMessage(
                reportThemeMessage(appearance, tokens),
                window.location.origin,
            );
            setFrameThemeError("");
            setFrameThemeState("ready");
        } catch {
            setFrameThemeError("報告顏色未能跟隨網站設定，內容仍可閱讀。");
            setFrameThemeState("fallback");
        }
    }, [appearance]);

    useEffect(() => {
        if (frameThemeState !== "loading" || (reports && !report)) return;
        const timeout = window.setTimeout(() => {
            setFrameThemeError(
                "報告載入逾時；目前顯示可用內容。你可以重試載入。",
            );
            setFrameThemeState("fallback");
        }, 15000);
        return () => window.clearTimeout(timeout);
    }, [frameAttempt, frameThemeState, report, reports]);

    useLayoutEffect(() => {
        if (reveal && reveal !== handledReveal.current && frame.current) {
            handledReveal.current = reveal;
            revealReportEvidence(frame.current, reveal.source, reveal.document);
        }
    }, [height, reveal]);

    useEffect(() => {
        const receive = (event: MessageEvent) => {
            // Trust only messages from our own frame, whatever their origin reports.
            if (event.source !== frame.current?.contentWindow) return;
            const target = reportNavigationHash(
                event.source,
                frame.current?.contentWindow,
                event.data,
                reports?.map(({ id }) => id) ?? null,
            );
            if (target) window.location.hash = target;
            const request = reportRevealRequest(
                event.source,
                frame.current?.contentWindow,
                event.data,
            );
            if (request && frame.current?.contentWindow) {
                try {
                    const document = frame.current.contentDocument;
                    if (!document) return;
                    const measured = reportFrameHeight(
                        document.documentElement.scrollHeight,
                    );
                    const nextHeight = measured ?? request.height;
                    if (nextHeight !== null) setHeight(nextHeight);
                    // A fresh object also services repeated requests at the same height.
                    setReveal({
                        source: frame.current.contentWindow,
                        document,
                    });
                } catch {
                    if (request.height !== null) setHeight(request.height);
                }
            }
            const data = event.data as { type?: string; height?: number };
            const nextHeight = reportFrameHeight(data?.height);
            if (data?.type === "rk:height" && nextHeight !== null)
                setHeight(nextHeight);
        };
        window.addEventListener("message", receive);
        return () => window.removeEventListener("message", receive);
    }, [reports]);

    useLayoutEffect(() => {
        if (frameThemeState === "ready") applyFrameTheme();
    }, [applyFrameTheme, frameThemeState, palette]);

    const retryFrame = () => {
        setFrameThemeError("");
        setFrameThemeState("loading");
        setFrameAttempt((attempt) => attempt + 1);
    };
    const frameThemeView = reportFrameThemeView(frameThemeState);

    return (
        <div className="rv-page">
            {reportId === "20261013-pattern-scan" && (
                <ComparisonEntrance back={`#report/${reportId}`} />
            )}
            <div className="rv-bar u-card">
                <a
                    className="rv-back u-btn"
                    href={studiesBack(currentStudyHash())}
                >
                    ← 返回研究列表
                </a>
                <div className="rv-title">
                    <strong>{report?.title || "研究報告"}</strong>
                    <span>
                        {report?.date && <span>報告日期 {report.date}</span>}
                        {report?.period && (
                            <span>資料期間 {report.period}</span>
                        )}
                        {report && <span>{statusLabel(report.status)}</span>}
                    </span>
                </div>
                <a
                    className="rv-open u-btn"
                    href={standaloneSrc}
                    target="_blank"
                    rel="noreferrer"
                >
                    在新分頁開啟 ↗
                </a>
            </div>
            {issue && (
                <ReportIndexNotice
                    issue={issue}
                    error={error}
                    loading={loading}
                    retry={retry}
                    reload={() => window.location.reload()}
                />
            )}
            {loading && !issue && (
                <p role="status" className="u-muted">
                    正在讀取報告資訊…
                </p>
            )}
            {frameThemeState === "loading" && (!reports || report) && (
                <p role="status" className="u-muted">
                    正在載入研究報告…
                </p>
            )}
            {frameThemeView.showFallback && frameThemeError && (
                <div className="rv-theme-fallback" role="status">
                    <p>{frameThemeError}</p>
                    <button
                        type="button"
                        className="u-btn"
                        onClick={retryFrame}
                    >
                        重試報告與主題
                    </button>
                </div>
            )}
            {reports && !report && !issue && (
                <div role="alert" className="u-notice">
                    <strong>這份報告目前不在清單中</strong>
                    <p>
                        連結可能已變更，或這份報告尚未加入目前的網站。你可以重新讀取清單，或返回研究列表選擇報告。
                    </p>
                    <div className="u-actions">
                        <button
                            type="button"
                            className="u-btn"
                            onClick={retry}
                            disabled={loading}
                        >
                            {loading ? "正在重新讀取…" : "重新讀取報告資訊"}
                        </button>
                        <a
                            className="u-btn"
                            href={studiesBack(currentStudyHash())}
                        >
                            返回研究列表
                        </a>
                    </div>
                    <SourceInfo label="查看查找詳情">
                        <p>報告識別：{reportId}</p>
                        <p>
                            預期位置：<code>tasks/{reportId}/web-report/</code>
                        </p>
                    </SourceInfo>
                </div>
            )}
            {(!reports || report) && (
                <iframe
                    key={frameAttempt}
                    ref={frame}
                    className="rv-frame"
                    title={report?.title || reportId}
                    src={src}
                    sandbox="allow-scripts allow-same-origin allow-downloads"
                    referrerPolicy="no-referrer"
                    style={{
                        ...(height ? { height } : {}),
                        ...(frameThemeView.hidden
                            ? { visibility: "hidden" as const }
                            : {}),
                    }}
                    onLoad={() => {
                        setReveal(null);
                        applyFrameTheme();
                    }}
                    onError={() => {
                        setFrameThemeError(
                            "報告載入失敗；目前顯示可用內容。你可以重試載入。",
                        );
                        setFrameThemeState("fallback");
                    }}
                />
            )}
        </div>
    );
}
