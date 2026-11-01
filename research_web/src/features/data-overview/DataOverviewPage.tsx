import { useEffect, useState } from "react";
import { apiUrl } from "../../api/base";
import {
    countLabel,
    groupDatasets,
    datasetPeriodLabel,
    datasetUpdatedLabel,
    datasetHref,
    catalogIdentity,
    catalogGuideHref,
    assetIndexHref,
    statusLabel,
    validateDataStatus,
    type DataStatus,
} from "./model";
import "./data-overview.css";
import { InfoTip } from "../../components/ui/InfoTip";
import { StockCoverageList } from "./CoveragePages";
import { VersionIdentity } from "../shared-data/VersionIdentity";

function useDataStatus() {
    const [data, setData] = useState<DataStatus | null>(null);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(true);
    const [retry, setRetry] = useState(0);
    useEffect(() => {
        const control = new AbortController();
        setError("");
        setLoading(true);
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
            .then((value) => {
                if (!control.signal.aborted) setData(validateDataStatus(value));
            })
            .catch((cause: Error) => {
                if (!control.signal.aborted && cause.name !== "AbortError")
                    setError(cause.message || "資料總覽暫時讀不到。");
            })
            .finally(() => {
                if (!control.signal.aborted) setLoading(false);
            });
        return () => control.abort();
    }, [retry]);
    return { data, error, loading, retry: () => setRetry((n) => n + 1) };
}

export function DataOverviewPage({ stocks = false }: { stocks?: boolean }) {
    const status = useDataStatus();
    const groups = status.data ? groupDatasets(status.data.datasets) : [];
    return (
        <div className={`u-page do-page${stocks ? " u-wide" : ""}`}>
            <nav className="u-segmented" aria-label="資料檢視">
                <a
                    className="u-chip"
                    aria-current={!stocks ? "page" : undefined}
                    href="#overview"
                >
                    資料集
                </a>
                <a
                    className="u-chip"
                    aria-current={stocks ? "page" : undefined}
                    href="#overview/stocks"
                >
                    股票
                </a>
            </nav>
            {stocks ? (
                <StockCoverageList />
            ) : (
                <div>
                    <div className="u-eyebrow">資料總覽</div>
                    <h1 className="u-title">資料集總覽</h1>
                    <p className="u-lede">
                        每份資料涵蓋的期間、最近更新時間與狀態。
                    </p>
                    <p className="u-muted">
                        代號數依各資料集的收錄範圍計算，可能包含
                        ETF、歷史證券或不同身分時段，不等於目前上市普通股家數。
                    </p>
                    {status.data?.status === "updating" && (
                        <p className="u-notice do-banner">
                            每日資料正在更新，部分數字可能稍後才會變動。
                        </p>
                    )}
                    {status.data && status.loading && (
                        <p className="u-notice" role="status">
                            正在重新讀取；以下保留上次成功讀取的結果。
                        </p>
                    )}
                    {status.data && status.error && (
                        <div className="u-notice" role="alert">
                            <p>
                                {status.error}{" "}
                                以下保留上次成功讀取的結果，尚未確認目前狀態。
                            </p>
                            {groups.length > 0 && (
                                <button
                                    className="u-btn"
                                    onClick={status.retry}
                                >
                                    重新讀取
                                </button>
                            )}
                        </div>
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
                    ) : groups.length === 0 ? (
                        <div className="u-card do-state" role="status">
                            <p>上次成功讀取時沒有已登錄的資料集。</p>
                            <button
                                className="u-btn"
                                onClick={status.retry}
                                disabled={status.loading}
                            >
                                {status.loading ? "正在重新讀取…" : "重新讀取"}
                            </button>
                        </div>
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
                                                    <InfoTip>
                                                        有資料僅表示已保存，歷史完整性及研究適用性仍需依資料說明確認。
                                                    </InfoTip>
                                                </span>
                                            </div>
                                            {catalogIdentity(item) && (
                                                <div className="do-identity">
                                                    <span>
                                                        資料集：
                                                        {
                                                            catalogIdentity(
                                                                item,
                                                            )!.dataId
                                                        }
                                                    </span>
                                                    <VersionIdentity
                                                        version={
                                                            catalogIdentity(
                                                                item,
                                                            )!.version
                                                        }
                                                    />
                                                </div>
                                            )}
                                            <p className="do-period">
                                                {datasetPeriodLabel(item)}
                                            </p>
                                            <dl className="do-facts">
                                                <div>
                                                    <dt>代號</dt>
                                                    <dd>
                                                        {countLabel(
                                                            item.symbols,
                                                            "個",
                                                        )}
                                                    </dd>
                                                </div>
                                                <div>
                                                    <dt>筆數</dt>
                                                    <dd>
                                                        {countLabel(
                                                            item.rows,
                                                            "筆",
                                                        )}
                                                    </dd>
                                                </div>
                                            </dl>
                                            <p className="u-muted do-updated">
                                                {datasetUpdatedLabel(item)}
                                            </p>
                                            {datasetHref(item) && (
                                                <a
                                                    className="u-btn"
                                                    href={datasetHref(item)!}
                                                >
                                                    看涵蓋股票
                                                </a>
                                            )}
                                            {item.source === "catalog" && (
                                                <div className="do-source-links">
                                                    <a
                                                        href={catalogGuideHref}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                    >
                                                        資料目錄取用說明 ↗
                                                    </a>
                                                    <a
                                                        href={assetIndexHref}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                    >
                                                        來源研究與資料契約索引 ↗
                                                    </a>
                                                    <p className="u-muted do-note">
                                                        以本卡的資料集與版本識別查找；固定版本不隨每日資料更新。
                                                    </p>
                                                </div>
                                            )}
                                        </article>
                                    ))}
                                </div>
                            </section>
                        ))
                    )}
                    {status.data && status.data.warnings.length > 0 && (
                        <details className="u-source do-warnings">
                            <summary>
                                注意事項（{status.data.warnings.length}）
                            </summary>
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
            )}
        </div>
    );
}
