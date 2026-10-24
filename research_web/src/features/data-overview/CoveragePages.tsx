import { useEffect, useRef, useState } from "react";
import { apiUrl } from "../../api/base";
import { CaveatChip, InfoTip } from "../../components/ui/InfoTip";
import { ProgressLine, SkeletonCards } from "../../components/ui/primitives";
import { SharedDataPage } from "../shared-data/SharedDataPage";
import {
    canUseCodeSeries,
    legacyHasNoMatch,
    legacyTarget,
    MARKS,
    listQuery,
    reasonText,
    safeBack,
    stockHref,
    type CoveredSecurity,
    type CoverageCell,
    type CoverageList,
} from "./coverageModel";
import "./coverage.css";

function CoverageLoading({ label }: { label: string }) {
    return (
        <div className="coverage-loading">
            <ProgressLine label={label} done={0} total={1} />
            <SkeletonCards
                count={2}
                className="coverage-skeleton-grid"
                label={label}
            />
        </div>
    );
}

function saveCoverageScroll(key: string, table: HTMLDivElement | null = null) {
    try {
        sessionStorage.setItem(
            `coverage-scroll:${key}`,
            String(window.scrollY),
        );
        if (table) {
            sessionStorage.setItem(
                `coverage-table-scroll:${key}`,
                JSON.stringify({
                    top: table.scrollTop,
                    left: table.scrollLeft,
                }),
            );
        }
    } catch {
        /* Storage may be unavailable. */
    }
}

async function readCoverage<T>(path: string, signal: AbortSignal): Promise<T> {
    const response = await fetch(apiUrl("/data-coverage/" + path), {
        signal,
        cache: "no-store",
    });
    if (!response.ok) throw new Error("資料暫時讀不到，請重新讀取。");
    const data = await response.json();
    if (data?.schema !== "security-coverage.v1")
        throw new Error("資料格式無法辨識。");
    return data as T;
}

function CoverageMark({ cell }: { cell: CoverageCell }) {
    const mark = MARKS[cell.mark] ?? MARKS.unknown;
    return (
        <span
            className="coverage-mark"
            data-mark={cell.mark}
            aria-label={mark.label}
        >
            {mark.icon}
        </span>
    );
}

export function StockSearch() {
    const [query, setQuery] = useState("");
    return (
        <form
            className="coverage-search"
            role="search"
            onSubmit={(event) => {
                event.preventDefault();
                location.hash =
                    "overview/stocks?" +
                    new URLSearchParams({
                        q: query.trim(),
                        kind: "",
                        status: "all",
                    });
            }}
        >
            <label
                className="coverage-search-label"
                htmlFor="coverage-global-search"
            >
                股票代號或名稱
            </label>
            <input
                id="coverage-global-search"
                placeholder="股票代號／名稱"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
            />
            <button className="u-btn" type="submit">
                搜尋
            </button>
        </form>
    );
}

export function StockCoverageList() {
    const raw = location.hash.split("?")[1] ?? "";
    const query = listQuery(raw);
    const requestKey = query.toString();
    const searched = query.get("q") ?? "";
    const [result, setResult] = useState<{
        key: string;
        data: CoverageList | null;
        error: string;
    }>({ key: "", data: null, error: "" });
    const [retry, setRetry] = useState(0);
    const [loading, setLoading] = useState(true);
    const input = useRef<HTMLInputElement>(null);
    const coverageTable = useRef<HTMLDivElement>(null);
    const current = result.key === requestKey;
    const data = current ? result.data : null;
    useEffect(() => {
        const control = new AbortController();
        setLoading(true);
        setResult((previous) =>
            previous.key === requestKey ? { ...previous, error: "" } : previous,
        );
        readCoverage<CoverageList>("securities?" + requestKey, control.signal)
            .then((data) => {
                setResult({ key: requestKey, data, error: "" });
                setLoading(false);
            })
            .catch((e: Error) => {
                if (e.name !== "AbortError") {
                    setResult({
                        key: requestKey,
                        data: null,
                        error: e.message,
                    });
                    setLoading(false);
                }
            });
        return () => control.abort();
    }, [requestKey, retry]);
    useEffect(() => {
        if (input.current) input.current.value = searched;
    }, [searched]);
    useEffect(() => {
        if (!data) return;
        const frame = requestAnimationFrame(() => {
            try {
                window.scrollTo(
                    0,
                    Number(
                        sessionStorage.getItem(
                            `coverage-scroll:${requestKey}`,
                        ) ?? 0,
                    ),
                );
                const savedTable = sessionStorage.getItem(
                    `coverage-table-scroll:${requestKey}`,
                );
                const position = savedTable
                    ? (JSON.parse(savedTable) as {
                          top?: number;
                          left?: number;
                      })
                    : null;
                if (coverageTable.current && position) {
                    coverageTable.current.scrollTop = Number(position.top ?? 0);
                    coverageTable.current.scrollLeft = Number(
                        position.left ?? 0,
                    );
                }
            } catch {
                /* Storage may be unavailable or contain an old value. */
            }
        });
        const saveWindow = () =>
            saveCoverageScroll(requestKey, coverageTable.current);
        const table = coverageTable.current;
        window.addEventListener("scroll", saveWindow, { passive: true });
        table?.addEventListener("scroll", saveWindow, { passive: true });
        return () => {
            cancelAnimationFrame(frame);
            window.removeEventListener("scroll", saveWindow);
            table?.removeEventListener("scroll", saveWindow);
        };
    }, [requestKey, data]);
    const update = (name: string, value: string) => {
        const next = new URLSearchParams(query);
        next.set(name, value);
        if (name !== "page") next.set("page", "1");
        location.hash = "overview/stocks?" + next;
    };
    return (
        <section className="coverage-list">
            <form
                className="coverage-filters"
                onSubmit={(e) => {
                    e.preventDefault();
                    update("q", input.current?.value ?? "");
                }}
            >
                <label>
                    搜尋
                    <input
                        ref={input}
                        defaultValue={query.get("q") ?? ""}
                        placeholder="代號／名稱"
                    />
                </label>
                <button className="u-btn" type="submit">
                    尋找
                </button>
                <label>
                    市場
                    <select
                        value={query.get("market") ?? ""}
                        onChange={(e) => update("market", e.target.value)}
                    >
                        <option value="">全部</option>
                        <option>TWSE</option>
                        <option>TPEx</option>
                        <option value="unknown">待確認</option>
                    </select>
                </label>
                <label>
                    種類
                    <select
                        value={query.get("kind") ?? ""}
                        onChange={(e) => update("kind", e.target.value)}
                    >
                        <option value="">全部</option>
                        <option value="stock">普通股</option>
                        <option value="etf">ETF</option>
                        <option value="unknown">待確認</option>
                    </select>
                </label>
                <label>
                    範圍
                    <select
                        value={query.get("status") ?? ""}
                        onChange={(e) => update("status", e.target.value)}
                    >
                        <option value="recent">近期有資料</option>
                        <option value="all">包含歷史</option>
                        <option value="delisted">已確認下市</option>
                        <option value="unresolved">身分待確認</option>
                    </select>
                </label>
                <label>
                    資料
                    <select
                        value={query.get("dataset") ?? ""}
                        onChange={(e) => {
                            const next = new URLSearchParams(query);
                            next.set("dataset", e.target.value);
                            next.delete("mark");
                            next.set("page", "1");
                            location.hash = "overview/stocks?" + next;
                        }}
                    >
                        <option value="">全部</option>
                        {data?.datasets.map((d) => (
                            <option key={d.id} value={d.id}>
                                {d.name}
                            </option>
                        ))}
                    </select>
                </label>
                {query.get("dataset") && (
                    <label>
                        狀態
                        <select
                            value={query.get("mark") ?? ""}
                            onChange={(e) => update("mark", e.target.value)}
                        >
                            <option value="">全部</option>
                            {Object.entries(MARKS).map(([id, mark]) => (
                                <option key={id} value={id}>
                                    {mark.label}
                                </option>
                            ))}
                        </select>
                    </label>
                )}
            </form>
            {(!current || loading) && (
                <CoverageLoading label="正在讀取股票資料" />
            )}
            {current && !loading && result.error && (
                <div role="alert">
                    {result.error}
                    <button
                        className="u-btn"
                        onClick={() => setRetry((n) => n + 1)}
                    >
                        重新讀取
                    </button>
                </div>
            )}
            {data?.synthetic && <p className="u-notice">虛構示範資料</p>}
            {data?.status === "unavailable" && (
                <p className="u-notice">
                    股票涵蓋摘要尚未備妥。
                    <InfoTip>
                        需要先由資料維護工作建立摘要，開啟本頁不會下載或掃描市場資料。
                    </InfoTip>{" "}
                    <button
                        className="u-btn"
                        onClick={() => setRetry((n) => n + 1)}
                    >
                        重新讀取
                    </button>
                </p>
            )}
            {data?.status === "partial" && (
                <p className="u-notice">
                    <CaveatChip detail="目前清單可能未涵蓋所有已知證券。">
                        部分來源尚未確認
                    </CaveatChip>
                </p>
            )}
            {data && data.status !== "unavailable" && (
                <>
                    <p className="coverage-counts">
                        {data.total.toLocaleString()} 檔 · 缺漏{" "}
                        {data.confirmed_missing} · 尚待確認 {data.unknown}
                        <InfoTip>
                            依目前篩選計算；有資料不等於歷史完整。近期有資料不等於已確認上市中，歷史觀察也不等於已下市。
                        </InfoTip>
                    </p>
                    <div className="coverage-hidden">
                        <button
                            className="u-chip"
                            onClick={() => update("status", "delisted")}
                        >
                            已確認下市 {data.hidden.delisted}
                        </button>
                        <button
                            className="u-chip"
                            onClick={() => update("status", "unresolved")}
                        >
                            身分待確認 {data.hidden.unresolved}
                        </button>
                        <span>
                            上市狀態待確認 {data.hidden.listing_unknown}
                        </span>
                    </div>
                    <div className="coverage-legend">
                        {Object.entries(MARKS).map(([id, mark]) => (
                            <span key={id}>
                                <span className="coverage-mark" data-mark={id}>
                                    {mark.icon}
                                </span>{" "}
                                {mark.label}
                            </span>
                        ))}
                    </div>
                    <div className="coverage-table-wrap" ref={coverageTable}>
                        <table className="coverage-table">
                            <thead>
                                <tr>
                                    <th>股票</th>
                                    {data.datasets.map((d) => (
                                        <th key={d.id}>
                                            <a
                                                href={
                                                    "#overview/stocks?" +
                                                    new URLSearchParams({
                                                        ...Object.fromEntries(
                                                            query,
                                                        ),
                                                        dataset: d.id,
                                                        page: "1",
                                                    })
                                                }
                                            >
                                                {d.name}
                                            </a>
                                        </th>
                                    ))}
                                </tr>
                            </thead>
                            <tbody>
                                {data.rows.map((stock) => (
                                    <tr key={stock.key}>
                                        <th scope="row">
                                            <a
                                                href={stockHref(
                                                    stock.key,
                                                    "",
                                                    location.hash,
                                                )}
                                                onClick={() =>
                                                    saveCoverageScroll(
                                                        requestKey,
                                                        coverageTable.current,
                                                    )
                                                }
                                            >
                                                {stock.name ?? stock.code}
                                            </a>
                                            <small>
                                                {stock.name
                                                    ? stock.code + " · "
                                                    : ""}
                                                {stock.market}
                                            </small>
                                            {stock.identity_status ===
                                                "unresolved" && (
                                                <small>身分待確認</small>
                                            )}
                                        </th>
                                        {stock.coverage.map((cell) => (
                                            <td key={cell.dataset}>
                                                <a
                                                    href={stockHref(
                                                        stock.key,
                                                        cell.dataset,
                                                        location.hash,
                                                    )}
                                                    onClick={() =>
                                                        saveCoverageScroll(
                                                            requestKey,
                                                            coverageTable.current,
                                                        )
                                                    }
                                                    aria-label={
                                                        stock.code +
                                                        " " +
                                                        (data.datasets.find(
                                                            (d) =>
                                                                d.id ===
                                                                cell.dataset,
                                                        )?.name ??
                                                            cell.dataset) +
                                                        "：" +
                                                        MARKS[cell.mark].label
                                                    }
                                                >
                                                    <CoverageMark cell={cell} />
                                                    <span className="coverage-mobile-label">
                                                        {
                                                            data.datasets.find(
                                                                (d) =>
                                                                    d.id ===
                                                                    cell.dataset,
                                                            )?.name
                                                        }
                                                    </span>
                                                </a>
                                            </td>
                                        ))}
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                    {!data.rows.length && (
                        <p>沒有符合篩選的股票。可切換種類或包含歷史資料。</p>
                    )}
                    <div className="coverage-pagination">
                        <button
                            className="u-btn"
                            disabled={data.page <= 1}
                            onClick={() =>
                                update("page", String(data.page - 1))
                            }
                        >
                            上一頁
                        </button>
                        <span>
                            {data.page} /{" "}
                            {Math.max(1, Math.ceil(data.total / data.size))}
                        </span>
                        <button
                            className="u-btn"
                            disabled={data.page * data.size >= data.total}
                            onClick={() =>
                                update("page", String(data.page + 1))
                            }
                        >
                            下一頁
                        </button>
                    </div>
                    <small className="u-muted">
                        最近檢查 {data.built_at?.slice(0, 10) ?? "未確認"}
                    </small>
                </>
            )}
        </section>
    );
}

function StoredRows({
    stock,
    dataset,
}: {
    stock: CoveredSecurity;
    dataset: "institutional" | "monthly-revenue";
}) {
    const [state, setState] = useState<{
        rows: Record<string, unknown>[];
        error: string;
        status: string;
    } | null>(null);
    const [retry, setRetry] = useState(0);
    useEffect(() => {
        const control = new AbortController();
        setState(null);
        const query = new URLSearchParams({ market: stock.market });
        fetch(
            apiUrl(
                "/data-series/v1/" +
                    dataset +
                    "/" +
                    encodeURIComponent(stock.code) +
                    "?" +
                    query,
            ),
            { signal: control.signal },
        )
            .then(async (response) => {
                if (!response.ok) throw new Error("資料暫時無法讀取。");
                return response.json();
            })
            .then((data) =>
                setState({
                    rows: Array.isArray(data.rows) ? data.rows : [],
                    error: data.warnings?.join(" ") ?? "",
                    status: data.status,
                }),
            )
            .catch((e: Error) => {
                if (e.name !== "AbortError")
                    setState({ rows: [], error: e.message, status: "error" });
            });
        return () => control.abort();
    }, [stock.key, stock.code, stock.market, dataset, retry]);
    if (!state) return <CoverageLoading label="正在讀取資料內容" />;
    const columns =
        dataset === "institutional"
            ? [
                  "date",
                  "foreign_total_net",
                  "trust_net",
                  "dealer_total_net",
                  "three_institutions_net",
              ]
            : ["revenue_month", "current_revenue_k_twd", "yoy_pct"];
    const labels: Record<string, string> = {
        date: "日期",
        foreign_total_net: "外資",
        trust_net: "投信",
        dealer_total_net: "自營商",
        three_institutions_net: "三大法人",
        revenue_month: "月份",
        current_revenue_k_twd: "營收（千元）",
        yoy_pct: "年增率（%）",
    };
    return (
        <>
            <p>{dataset === "institutional" ? "買賣超・股" : "每月營收"}</p>
            {state.error && <p className="u-notice">{state.error}</p>}
            {state.status === "missing" && <p>目前沒有可顯示的紀錄。</p>}
            {state.status !== "ok" && (
                <button
                    className="u-btn"
                    onClick={() => setRetry((n) => n + 1)}
                >
                    重新讀取
                </button>
            )}
            <div className="coverage-table-wrap">
                <table className="coverage-values">
                    <thead>
                        <tr>
                            {columns.map((c) => (
                                <th key={c}>{labels[c]}</th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {state.rows.map((row, i) => (
                            <tr key={i}>
                                {columns.map((c) => (
                                    <td key={c}>
                                        {row[c] === null || row[c] === undefined
                                            ? "—"
                                            : String(row[c])}
                                    </td>
                                ))}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
        </>
    );
}

export function StockCoverageDetail({
    securityKey,
    theme,
}: {
    securityKey: string;
    theme: string;
}) {
    const raw = location.hash.split("?")[1] ?? "";
    const query = new URLSearchParams(raw);
    const [detail, setDetail] = useState<{
        status: string;
        security: CoveredSecurity | null;
        generation?: string;
    } | null>(null);
    const [error, setError] = useState("");
    const [retry, setRetry] = useState(0);
    useEffect(() => {
        const control = new AbortController();
        setDetail(null);
        setError("");
        readCoverage<{
            status: string;
            security: CoveredSecurity | null;
            generation?: string;
        }>("securities/" + encodeURIComponent(securityKey), control.signal)
            .then(setDetail)
            .catch((e: Error) => {
                if (e.name !== "AbortError") setError(e.message);
            });
        return () => control.abort();
    }, [securityKey, retry]);
    const stock = detail?.security;
    const stockKey = stock?.key;
    const selected = query.get("dataset");
    useEffect(() => {
        if (!stockKey || !selected) return;
        const frame = requestAnimationFrame(() => {
            document
                .getElementById(`coverage-${selected}`)
                ?.scrollIntoView({ behavior: "smooth", block: "start" });
        });
        return () => cancelAnimationFrame(frame);
    }, [stockKey, selected]);
    const activeDataset =
        selected ?? (stock?.can_view_prices ? "adjusted_daily" : null);
    return (
        <div className="u-page">
            <a className="u-btn" href={safeBack(query.get("back"))}>
                返回股票列表
            </a>
            {error && (
                <p role="alert">
                    {error}
                    <button
                        onClick={() => setRetry((n) => n + 1)}
                        className="u-btn"
                    >
                        重新讀取
                    </button>
                </p>
            )}
            {!detail && !error && <CoverageLoading label="正在讀取股票資料" />}
            {detail?.status === "unavailable" && (
                <p>
                    涵蓋摘要尚未備妥，請稍後再試。{" "}
                    <button
                        className="u-btn"
                        onClick={() => setRetry((n) => n + 1)}
                    >
                        重新讀取
                    </button>
                </p>
            )}
            {stock && (
                <>
                    <h1 className="u-title">{stock.name ?? stock.code}</h1>
                    <p>
                        {stock.code} · {stock.market}
                        {stock.listing_status === "delisted"
                            ? " · 已確認下市"
                            : ""}
                    </p>
                    {stock.identity_status === "unresolved" && (
                        <p className="u-notice">
                            歷史身分待確認 ·{" "}
                            {stock.segment.from ?? "起點未確認"} ～{" "}
                            {stock.segment.to ?? "目前"}
                            <InfoTip>
                                偵測到可能的股號重用、長期資料中斷或市場不明。尚未證實身分，暫不串接圖表或把全部歷史掛到最新公司。
                            </InfoTip>
                        </p>
                    )}
                    <div className="coverage-detail-grid">
                        {stock.coverage.map((cell) => {
                            const isActive = activeDataset === cell.dataset;
                            const label =
                                cell.dataset === "symbol_meta"
                                    ? "名稱與產業"
                                    : ({
                                          official_daily: "官方股價",
                                          price_daily: "整合股價",
                                          institutional: "三大法人",
                                          monthly_revenue: "月營收",
                                          corporate_actions: "公司行動",
                                          adjusted_daily: "還原股價與指標",
                                      }[cell.dataset] ?? "資料");
                            return (
                                <section
                                    key={cell.dataset}
                                    className={`u-card coverage-detail-card${isActive ? " is-active" : ""}`}
                                    id={"coverage-" + cell.dataset}
                                >
                                    <h2>
                                        <a
                                            href={stockHref(
                                                stock.key,
                                                cell.dataset,
                                                safeBack(query.get("back")),
                                            )}
                                        >
                                            {label}
                                        </a>{" "}
                                        <CoverageMark cell={cell} />
                                    </h2>
                                    <p>
                                        {cell.rows === null
                                            ? "筆數待確認"
                                            : cell.rows.toLocaleString() +
                                              " 筆"}{" "}
                                        · {cell.period.from ?? "?"} ～{" "}
                                        {cell.period.to ?? "?"}
                                    </p>
                                    <InfoTip>
                                        {cell.reasons.map((reason) => (
                                            <span key={reason}>
                                                {reasonText(reason)}{" "}
                                            </span>
                                        ))}
                                        檢查時間：{cell.checked_at ?? "未確認"}
                                    </InfoTip>
                                    {isActive && (
                                        <div className="coverage-selected-viewer">
                                            {cell.dataset === "symbol_meta" && (
                                                <p>
                                                    {stock.industry ??
                                                        "產業待確認"}{" "}
                                                    · 最近觀察{" "}
                                                    {stock.observed_at?.slice(
                                                        0,
                                                        10,
                                                    ) ?? "未確認"}
                                                    <InfoTip>
                                                        這是取得資訊的日期，不是名稱或產業的歷史有效起點。
                                                    </InfoTip>
                                                </p>
                                            )}
                                            {canUseCodeSeries(
                                                stock.identity_status,
                                            ) &&
                                                cell.dataset ===
                                                    "institutional" && (
                                                    <StoredRows
                                                        key={
                                                            stock.key +
                                                            cell.dataset
                                                        }
                                                        stock={stock}
                                                        dataset="institutional"
                                                    />
                                                )}
                                            {canUseCodeSeries(
                                                stock.identity_status,
                                            ) &&
                                                cell.dataset ===
                                                    "monthly_revenue" && (
                                                    <StoredRows
                                                        key={
                                                            stock.key +
                                                            cell.dataset
                                                        }
                                                        stock={stock}
                                                        dataset="monthly-revenue"
                                                    />
                                                )}
                                            {stock.identity_status ===
                                                "unresolved" &&
                                                (cell.dataset ===
                                                    "institutional" ||
                                                    cell.dataset ===
                                                        "monthly_revenue" ||
                                                    cell.dataset ===
                                                        "adjusted_daily") && (
                                                    <p className="u-notice">
                                                        這段歷史的證券身分待確認，暫不串接其他時段的資料。
                                                    </p>
                                                )}
                                            {(cell.dataset ===
                                                "official_daily" ||
                                                cell.dataset ===
                                                    "price_daily" ||
                                                cell.dataset ===
                                                    "corporate_actions") && (
                                                <p>
                                                    此資料目前提供涵蓋摘要。
                                                    {stock.can_view_prices && (
                                                        <a
                                                            href={stockHref(
                                                                stock.key,
                                                                "adjusted_daily",
                                                                safeBack(
                                                                    query.get(
                                                                        "back",
                                                                    ),
                                                                ),
                                                            )}
                                                        >
                                                            查看還原股價
                                                        </a>
                                                    )}
                                                </p>
                                            )}
                                            {cell.dataset ===
                                                "adjusted_daily" &&
                                                stock.can_view_prices &&
                                                canUseCodeSeries(
                                                    stock.identity_status,
                                                ) && (
                                                    <SharedDataPage
                                                        key={stock.key}
                                                        code={stock.code}
                                                        theme={theme}
                                                    />
                                                )}
                                            {cell.dataset ===
                                                "adjusted_daily" &&
                                                !stock.can_view_prices && (
                                                    <p>
                                                        目前沒有可開啟的還原股價資料。
                                                    </p>
                                                )}
                                        </div>
                                    )}
                                </section>
                            );
                        })}
                    </div>
                </>
            )}
        </div>
    );
}

export function LegacyStockResolver({ code }: { code: string }) {
    const [state, setState] = useState<{
        status: string;
        candidates: CoveredSecurity[];
    } | null>(null);
    const [error, setError] = useState("");
    const [retry, setRetry] = useState(0);
    useEffect(() => {
        const control = new AbortController();
        setState(null);
        setError("");
        readCoverage<{ status: string; candidates: CoveredSecurity[] }>(
            "resolve?code=" + encodeURIComponent(code),
            control.signal,
        )
            .then((result) => {
                const target = legacyTarget(result.status, result.candidates);
                if (target) location.replace(stockHref(target));
                else setState(result);
            })
            .catch((e: Error) => {
                if (e.name !== "AbortError") setError(e.message);
            });
        return () => control.abort();
    }, [code, retry]);
    return (
        <div className="u-page">
            <a href="#overview/stocks">返回股票列表</a>
            <h1 className="u-title">選擇證券</h1>
            {error && (
                <p role="alert">
                    {error}{" "}
                    <button
                        className="u-btn"
                        onClick={() => setRetry((n) => n + 1)}
                    >
                        重新讀取
                    </button>
                </p>
            )}
            {!state && !error && <CoverageLoading label="正在確認股票身分" />}
            {state?.status === "unavailable" && (
                <p>
                    股票摘要尚未備妥，暫時無法確認身分。{" "}
                    <button
                        className="u-btn"
                        onClick={() => setRetry((n) => n + 1)}
                    >
                        重新讀取
                    </button>
                </p>
            )}
            {state?.candidates.map((stock) => (
                <p key={stock.key}>
                    <a href={stockHref(stock.key)}>
                        {stock.name ?? stock.code} · {stock.market} ·{" "}
                        {stock.segment.from ?? "起點未確認"} ～{" "}
                        {stock.segment.to ?? "目前"}
                    </a>
                </p>
            ))}
            {state && legacyHasNoMatch(state.status, state.candidates) && (
                <p>沒有找到可確認的證券。</p>
            )}
        </div>
    );
}
