import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { artifactMode } from "../../api/artifactMode";
import { studiesBack, type ReadingRecord } from "../studies/reading";
import {
    imageUnavailableLabel,
    markdownFragmentId,
    markdownHeadingIds,
    scrollMarkdownFragment,
} from "./markdownNavigation";

interface ReadingResponse {
    task_id: string;
    reading: ReadingRecord | null;
    markdown: string;
    sources: { label: string; path: string }[];
    state: string;
    reason: string;
}

export function MarkdownReport({ reportId }: { reportId: string }) {
    const [data, setData] = useState<ReadingResponse | null>(null);
    const [error, setError] = useState("");
    const [retry, setRetry] = useState(0);
    const [source, setSource] = useState<number | null>(null);
    const [original, setOriginal] = useState<{
        markdown: string;
        label: string;
    } | null>(null);
    const [sourceError, setSourceError] = useState("");
    const [sourceRetry, setSourceRetry] = useState(0);
    const base = `/history-api/studies/${encodeURIComponent(reportId)}`;
    const back = studiesBack(window.location.hash);
    useEffect(() => {
        const controller = new AbortController();
        let timeout = false;
        const timer = setTimeout(() => {
            timeout = true;
            controller.abort();
        }, 20000);
        setData(null);
        setError("");
        fetch(`${base}/reading`, {
            signal: controller.signal,
            headers: {
                "X-Research-Data-Mode": artifactMode(
                    import.meta.env.VITE_ARTIFACT_MODE,
                ),
            },
        })
            .then(async (response) => {
                if (!response.ok)
                    throw new Error(
                        response.status === 404
                            ? "這份研究尚未提供可讀取的原文。"
                            : "報告服務暫時無法讀取。請重試。",
                    );
                const value = (await response.json()) as ReadingResponse;
                if (
                    typeof value.markdown !== "string" ||
                    !Array.isArray(value.sources)
                )
                    throw new Error("報告內容格式無法確認。");
                if (!controller.signal.aborted) setData(value);
            })
            .catch((cause: Error) => {
                if (timeout) setError("報告載入逾時，請重試。");
                else if (!controller.signal.aborted) setError(cause.message);
            })
            .finally(() => clearTimeout(timer));
        return () => {
            clearTimeout(timer);
            controller.abort();
        };
    }, [base, retry]);
    useEffect(() => {
        setOriginal(null);
        setSourceError("");
        if (source === null) return;
        const controller = new AbortController();
        let timeout = false;
        const timer = setTimeout(() => {
            timeout = true;
            controller.abort();
        }, 20000);
        fetch(`${base}/source?index=${source}`, {
            signal: controller.signal,
            headers: {
                "X-Research-Data-Mode": artifactMode(
                    import.meta.env.VITE_ARTIFACT_MODE,
                ),
            },
        })
            .then(async (response) => {
                if (!response.ok) throw new Error("來源原文暫時無法讀取。");
                const value = (await response.json()) as {
                    markdown: string;
                    label: string;
                };
                if (typeof value.markdown !== "string")
                    throw new Error("來源格式無法確認。");
                if (!controller.signal.aborted) setOriginal(value);
            })
            .catch((cause: Error) => {
                if (timeout) setSourceError("來源載入逾時，請重試。");
                else if (!controller.signal.aborted)
                    setSourceError(cause.message);
            })
            .finally(() => clearTimeout(timer));
        return () => {
            clearTimeout(timer);
            controller.abort();
        };
    }, [base, source, sourceRetry]);
    return (
        <article className="u-page reading-page">
            <a className="u-btn" href={back}>
                ← 返回研究列表
            </a>
            <p className="st-identity">{reportId}</p>
            {error ? (
                <div role="alert" className="u-notice">
                    <p>{error}</p>
                    <button
                        className="u-btn"
                        onClick={() => setRetry((n) => n + 1)}
                    >
                        重新讀取
                    </button>
                </div>
            ) : !data ? (
                <p role="status">正在讀取報告…</p>
            ) : (
                <>
                    <p className="u-notice">
                        {data.reading?.state === "ready"
                            ? "已整理閱讀版 · 原始結果與研究限制保留"
                            : data.reason || "歷史原文，尚未完成閱讀版核對。"}
                    </p>
                    {data.reading?.updated_at && (
                        <p>閱讀版更新：{data.reading.updated_at}</p>
                    )}
                    {data.reading?.data_period && (
                        <p>
                            研究資料：{data.reading.data_period.from} ～{" "}
                            {data.reading.data_period.to}
                        </p>
                    )}
                    <div className="reading-prose">
                        <ReactMarkdown
                            remarkPlugins={[remarkGfm]}
                            rehypePlugins={[
                                [
                                    markdownHeadingIds,
                                    { prefix: "reading-edition-" },
                                ],
                            ]}
                            skipHtml
                            components={{
                                img: ({ alt }) => (
                                    <span>{imageUnavailableLabel(alt)}</span>
                                ),
                                a: ({ href, children }) => {
                                    if (
                                        markdownFragmentId(
                                            href,
                                            "reading-edition-",
                                        )
                                    )
                                        return (
                                            <button
                                                className="reading-source-link"
                                                onClick={() =>
                                                    scrollMarkdownFragment(
                                                        href,
                                                        "reading-edition-",
                                                        (id) =>
                                                            document.getElementById(
                                                                id,
                                                            ),
                                                    )
                                                }
                                            >
                                                {children}
                                            </button>
                                        );
                                    if (href?.startsWith("#"))
                                        return <span>{children}</span>;
                                    if (href?.startsWith("https://"))
                                        return (
                                            <a
                                                href={href}
                                                target="_blank"
                                                rel="noreferrer"
                                            >
                                                {children}
                                            </a>
                                        );
                                    let path = "";
                                    try {
                                        path = href
                                            ? new URL(
                                                  href,
                                                  `https://reading.invalid/tasks/${reportId}/${data.reading?.edition ?? "report.md"}`,
                                              ).pathname.replace(
                                                  /^\/tasks\//,
                                                  "",
                                              )
                                            : "";
                                    } catch {
                                        /* An invalid legacy link remains readable text. */
                                    }
                                    const index = data.sources.findIndex(
                                        (item) => item.path === path,
                                    );
                                    return index >= 0 ? (
                                        <button
                                            className="reading-source-link"
                                            onClick={() => setSource(index)}
                                        >
                                            {children}
                                        </button>
                                    ) : (
                                        <span>{children}</span>
                                    );
                                },
                            }}
                        >
                            {data.markdown}
                        </ReactMarkdown>
                    </div>
                    {data.sources.length > 0 && (
                        <section
                            className="reading-sources"
                            aria-label="原始資料來源"
                        >
                            <h2>原始資料來源</h2>
                            <p>
                                以下原文保留當時的說法；閱讀版的更正與未回答事項列在上方。
                            </p>
                            {data.sources.map((item, index) => (
                                <button
                                    className="u-btn"
                                    key={item.path}
                                    aria-pressed={source === index}
                                    onClick={() => setSource(index)}
                                >
                                    {item.label}
                                </button>
                            ))}
                        </section>
                    )}
                    {source !== null && (
                        <section aria-label="來源原文" className="u-card">
                            <h2>
                                {original?.label ?? data.sources[source]?.label}
                            </h2>
                            <button
                                className="u-btn"
                                onClick={() => setSource(null)}
                            >
                                收起原文
                            </button>
                            {sourceError ? (
                                <div role="alert">
                                    <p>{sourceError}</p>
                                    <button
                                        onClick={() =>
                                            setSourceRetry((n) => n + 1)
                                        }
                                    >
                                        重試來源
                                    </button>
                                </div>
                            ) : original ? (
                                <div className="reading-prose">
                                    <ReactMarkdown
                                        remarkPlugins={[remarkGfm]}
                                        rehypePlugins={[
                                            [
                                                markdownHeadingIds,
                                                { prefix: "reading-source-" },
                                            ],
                                        ]}
                                        skipHtml
                                        components={{
                                            img: ({ alt }) => (
                                                <span>
                                                    {imageUnavailableLabel(alt)}
                                                </span>
                                            ),
                                            a: ({ href, children }) =>
                                                markdownFragmentId(
                                                    href,
                                                    "reading-source-",
                                                ) ? (
                                                    <button
                                                        className="reading-source-link"
                                                        onClick={() =>
                                                            scrollMarkdownFragment(
                                                                href,
                                                                "reading-source-",
                                                                (id) =>
                                                                    document.getElementById(
                                                                        id,
                                                                    ),
                                                            )
                                                        }
                                                    >
                                                        {children}
                                                    </button>
                                                ) : (
                                                    <span>{children}</span>
                                                ),
                                        }}
                                    >
                                        {original.markdown}
                                    </ReactMarkdown>
                                </div>
                            ) : (
                                <p role="status">正在讀取來源…</p>
                            )}
                        </section>
                    )}
                </>
            )}
        </article>
    );
}
