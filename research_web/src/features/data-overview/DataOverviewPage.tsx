import { useEffect, useState } from "react";
import { apiUrl } from "../../api/base";
import {
    countLabel,
    groupDatasets,
    periodLabel,
    statusLabel,
    updatedLabel,
    validateDataStatus,
    type DataStatus,
} from "./model";
import "./data-overview.css";

function useDataStatus() {
    const [data, setData] = useState<DataStatus | null>(null);
    const [error, setError] = useState("");
    const [retry, setRetry] = useState(0);
    useEffect(() => {
        const control = new AbortController();
        setError("");
        fetch(apiUrl("/data-status"), {
            signal: control.signal,
            cache: "no-store",
        })
            .then((response) => {
                if (!response.ok)
                    throw new Error(
                        `資料總覽暫時讀不到（HTTP ${response.status}）。`,
                    );
                return response.json();
            })
            .then((value) => setData(validateDataStatus(value)))
            .catch((cause: Error) => {
                if (cause.name !== "AbortError")
                    setError(cause.message || "資料總覽暫時讀不到。");
            });
        return () => control.abort();
    }, [retry]);
    return { data, error, retry: () => setRetry((n) => n + 1) };
}

export function DataOverviewPage() {
    const status = useDataStatus();
    const groups = status.data ? groupDatasets(status.data.datasets) : [];
    return (
        <div className="u-page do-page">
            <div className="u-eyebrow">資料總覽</div>
            <h1 className="u-title">這台電腦上有哪些資料。</h1>
            <p className="u-lede">每份資料涵蓋的期間、最近更新時間與狀態。</p>
            {status.data?.status === "updating" && (
                <p className="u-notice do-banner">
                    每日資料正在更新，部分數字可能稍後才會變動。
                </p>
            )}
            {!status.data ? (
                status.error ? (
                    <div className="u-card do-state">
                        <p>{status.error}</p>
                        <button
                            className="u-btn u-btn-primary"
                            onClick={status.retry}
                        >
                            重新讀取
                        </button>
                    </div>
                ) : (
                    <p className="u-skeleton">正在讀取資料總覽…</p>
                )
            ) : (
                groups.map((group) => (
                    <section key={group.source}>
                        <h2 className="u-section-title do-group">
                            {group.title}
                            <span className="u-muted do-note">
                                {group.note}
                            </span>
                        </h2>
                        <div className="do-grid">
                            {group.datasets.map((item) => (
                                <article
                                    key={`${item.source}:${item.id}`}
                                    className="u-card do-card"
                                >
                                    <div className="do-head">
                                        <h3>{item.name}</h3>
                                        <span
                                            className="do-status"
                                            data-status={item.status}
                                        >
                                            {statusLabel(item)}
                                        </span>
                                    </div>
                                    <p className="do-period">
                                        {periodLabel(item.data_period)}
                                    </p>
                                    <dl className="do-facts">
                                        <div>
                                            <dt>代號</dt>
                                            <dd>
                                                {countLabel(item.symbols, "檔")}
                                            </dd>
                                        </div>
                                        <div>
                                            <dt>筆數</dt>
                                            <dd>
                                                {countLabel(item.rows, "筆")}
                                            </dd>
                                        </div>
                                    </dl>
                                    <p className="u-muted do-updated">
                                        {updatedLabel(item.last_updated)}
                                    </p>
                                </article>
                            ))}
                        </div>
                    </section>
                ))
            )}
            {status.data && status.data.warnings.length > 0 && (
                <details className="u-source do-warnings">
                    <summary>注意事項（{status.data.warnings.length}）</summary>
                    <div>
                        <ul>
                            {status.data.warnings.map((text) => (
                                <li key={text}>{text}</li>
                            ))}
                        </ul>
                    </div>
                </details>
            )}
        </div>
    );
}
