import { useMemo, useState } from "react";
import { filterReports, reportTags, statusLabel } from "./model";
import { useReportIndex } from "./useReportIndex";
import "./reports.css";

export function ReportsPage() {
    const { reports, error } = useReportIndex();
    const [query, setQuery] = useState("");
    const [tag, setTag] = useState<string | null>(null);
    const tags = useMemo(() => reportTags(reports ?? []), [reports]);
    const shown = useMemo(
        () => filterReports(reports ?? [], query, tag),
        [reports, query, tag],
    );
    return (
        <div className="rp-page">
            <section className="rp-hero">
                <div>
                    <h1>研究報告</h1>
                    <p>
                        每份報告都是研究完成後寫成的互動網頁，放在各研究自己的資料夾裡。
                        這裡自動收集，不必另外登記。
                    </p>
                </div>
                <label className="rp-search">
                    <span className="visually-hidden">搜尋報告</span>
                    <input
                        type="search"
                        placeholder="搜尋標題、標籤或研究代號"
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                    />
                </label>
            </section>
            {tags.length > 0 && (
                <div className="rp-tags" role="group" aria-label="依標籤篩選">
                    <button
                        aria-pressed={tag === null}
                        onClick={() => setTag(null)}
                    >
                        全部
                    </button>
                    {tags.map((t) => (
                        <button
                            key={t}
                            aria-pressed={tag === t}
                            onClick={() => setTag(t === tag ? null : t)}
                        >
                            {t}
                        </button>
                    ))}
                </div>
            )}
            {error && <p className="rp-notice">{error}</p>}
            {!reports && !error && <p role="status">正在讀取報告清單…</p>}
            {reports && reports.length === 0 && (
                <div className="rp-empty">
                    <strong>還沒有報告。</strong>
                    <p>
                        在{" "}
                        <code>
                            tasks/&lt;研究代號&gt;/web-report/index.html
                        </code>{" "}
                        放一份報告網頁， 加上{" "}
                        <code>&lt;meta name="report:title"&gt;</code>{" "}
                        等標籤，重新整理就會出現在這裡。
                    </p>
                </div>
            )}
            {reports && reports.length > 0 && shown.length === 0 && (
                <p className="rp-notice">沒有符合條件的報告。</p>
            )}
            <ul className="rp-list">
                {shown.map((report) => (
                    <li key={report.id}>
                        <a
                            className="rp-card"
                            href={`#report/${encodeURIComponent(report.id)}`}
                        >
                            <div className="rp-card-top">
                                <span className="rp-date">
                                    {report.date || "未標日期"}
                                </span>
                                <span
                                    className={`rp-status is-${report.status || "none"}`}
                                >
                                    {statusLabel(report.status)}
                                </span>
                            </div>
                            <h2>{report.title || report.id}</h2>
                            {report.summary && <p>{report.summary}</p>}
                            <div className="rp-card-meta">
                                {report.period && (
                                    <span>資料期間 {report.period}</span>
                                )}
                                <span className="rp-id">{report.id}</span>
                            </div>
                            {report.tags.length > 0 && (
                                <div className="rp-card-tags">
                                    {report.tags.map((t) => (
                                        <span key={t}>{t}</span>
                                    ))}
                                </div>
                            )}
                        </a>
                    </li>
                ))}
            </ul>
        </div>
    );
}
