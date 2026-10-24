import { useCallback, useEffect, useMemo, useState } from "react";
import { artifactMode } from "../../api/artifactMode";
import { readShared, recoverSymbolNames } from "./api";
import {
    MA_PERIODS,
    resolveSymbolInput,
    formatNumber as fmt,
    formatFeature,
    featureLabels,
    priceChange,
    formatSigned,
    qualityCounts,
    validPrice,
    type Basis,
    type Families,
    type SharedSeries,
    type SharedSymbol,
} from "./model";
import { SharedChart } from "./SharedChart";
import { SharedCatalog } from "./SharedCatalog";
import { SourceInfo } from "../../components/ui/primitives";
import { RevenueChart } from "./RevenueChart";
import { OverlayStatus } from "./OverlayStatus";
import { useOverlay } from "./useOverlay";
import {
    INSTITUTIONAL_FIELDS,
    institutionalPoints,
    type InstitutionalField,
    type InstitutionalRow,
    type RevenueRow,
} from "./overlays";
import "./shared-data.css";

export function SharedDataPage({
    code,
    theme,
}: {
    code?: string;
    theme: string;
}) {
    const privateMode =
        artifactMode(import.meta.env.VITE_ARTIFACT_MODE) === "local-private";
    const selected = code || "2330";
    const [tab, setTab] = useState("viewer");
    const [search, setSearch] = useState("");
    const [basis, setBasis] = useState<Basis>("reference_factor_adjusted");
    const [families, setFamilies] = useState<Families | null>(null);
    const [symbols, setSymbols] = useState<SharedSymbol[]>([]);
    // Thousands of options are unchanged when a quote or cursor date changes.
    const symbolOptions = useMemo(
        () =>
            symbols.map((item) => (
                <option
                    key={item.code}
                    value={`${item.code} ${item.name || ""}`}
                />
            )),
        [symbols],
    );
    const [namesAvailable, setNamesAvailable] = useState(true);
    const [namesRetry, setNamesRetry] = useState(0);
    const [namesNotice, setNamesNotice] = useState("");
    const [loaded, setLoaded] = useState<{
        series: SharedSeries;
        requestedAt: number;
    } | null>(null);
    const [metadataGeneration, setMetadataGeneration] = useState("");
    const series = loaded?.series;
    const [error, setError] = useState("");
    const [metadataError, setMetadataError] = useState("");
    const [retry, setRetry] = useState(0);
    const [ma, setMa] = useState([5, 20, 60]);
    const [bb, setBb] = useState(true);
    const [pivots, setPivots] = useState([4]);
    const [oscillator, setOscillator] = useState("RSI14");
    const [range, setRange] = useState(240);
    const [cursor, setCursor] = useState(-1);
    const [institutionalField, setInstitutionalField] = useState<
        InstitutionalField | "off"
    >("off");
    const [showRevenue, setShowRevenue] = useState(false);
    const updateCursor = useCallback((i: number) => setCursor(i), []);
    useEffect(() => {
        if (!privateMode) return;
        const controller = new AbortController();
        setMetadataError("");
        setFamilies(null);

        readShared<Families>("families", controller.signal)
            .then((data) => {
                if (!controller.signal.aborted) setFamilies(data);
            })
            .catch((reason: Error) => {
                if (!controller.signal.aborted)
                    setMetadataError(reason.message);
            });
        return () => controller.abort();
    }, [privateMode, retry, metadataGeneration]);
    useEffect(() => {
        if (!privateMode) return;
        // A dedicated controller lets manual name recovery avoid reloading
        // families, prices or the chart while sharing the metadata lifecycle.
        const controller = new AbortController();
        setSymbols([]);
        setNamesAvailable(false);
        setNamesNotice("正在讀取股票名稱…");
        recoverSymbolNames(controller.signal, metadataGeneration, (data) => {
            if (controller.signal.aborted) return;
            setSymbols(data.symbols);
            setNamesAvailable(data.namesAvailable);
            setNamesNotice(
                data.namesAvailable
                    ? ""
                    : "每 60 秒自動重試名稱，最多 60 次；仍可用代號查詢。",
            );
        })
            .then((result) => {
                if (controller.signal.aborted) return;
                if (result === "exhausted")
                    setNamesNotice(
                        "名稱自動重試已達 60 次上限；可手動重新啟動。",
                    );
                if (result === "generation-changed")
                    setNamesNotice("股票名稱資料已更新，請重新載入頁面。");
            })
            .catch((reason: Error) => {
                if (!controller.signal.aborted)
                    setNamesNotice(
                        `名稱讀取停止：${reason.message}。可手動重試。`,
                    );
            });
        return () => controller.abort();
    }, [privateMode, retry, metadataGeneration, namesRetry]);
    useEffect(() => {
        if (!privateMode) return;
        const controller = new AbortController();
        setLoaded(null);
        setError("");
        const requestedAt = performance.now();
        readShared<SharedSeries>(
            `adjusted-daily-v1/series/${encodeURIComponent(selected)}?basis=${basis}`,
            controller.signal,
        )
            .then((data) => {
                if (!controller.signal.aborted) {
                    setLoaded({ series: data, requestedAt });
                    setCursor(data.dates.length - 1);
                    // Only a new observed generation refreshes discovery metadata.
                    // Changing stocks within the same generation does not refetch it.
                    setMetadataGeneration(data.generation);
                }
            })
            .catch((reason: Error) => {
                if (!controller.signal.aborted) setError(reason.message);
            });
        return () => controller.abort();
    }, [privateMode, selected, basis, retry]);
    const current =
        series?.code === selected && series.basis === basis ? series : null;
    const symbol = symbols.find((item) => item.code === selected);
    const institutional = useOverlay<InstitutionalRow>(
        "institutional",
        current?.code ?? null,
        current?.dates[0] ?? null,
        privateMode && institutionalField !== "off",
    );
    const revenue = useOverlay<RevenueRow>(
        "monthly-revenue",
        current?.code ?? null,
        current?.dates[0]?.slice(0, 7) ?? null,
        privateMode && showRevenue,
    );
    const chartDates = useMemo(() => new Set(current?.dates ?? []), [current]);
    const institutionalSeries = useMemo(
        () =>
            institutional.data && institutionalField !== "off"
                ? institutionalPoints(
                      institutional.data.rows,
                      institutionalField,
                      chartDates,
                  )
                : null,
        [institutional.data, institutionalField, chartDates],
    );
    const reference = basis === "reference_factor_adjusted";
    const day =
        current && cursor >= 0
            ? Math.min(cursor, current.dates.length - 1)
            : -1;
    const change = current ? priceChange(current, day) : null;
    const reasons = useMemo(
        () => (current ? qualityCounts(current) : []),
        [current],
    );
    const invalid = reasons.reduce((total, [, count]) => total + count, 0);
    const toggle = (values: number[], value: number) =>
        values.includes(value)
            ? values.filter((x) => x !== value)
            : [...values, value].sort((a, b) => a - b);
    const openSymbol = () => {
        const target = resolveSymbolInput(search, symbols);
        if (target) {
            location.hash = `data/${encodeURIComponent(target)}`;
            setSearch("");
        }
    };
    return (
        <section className="u-page u-wide shared-data">
            <header className="shared-heading">
                <div>
                    <h1 className="u-title">個股</h1>
                    <p className="u-lede">查股價、技術指標與已確認高低點。</p>
                </div>
                <div
                    className="shared-controls u-chips"
                    role="tablist"
                    aria-label="共用資料頁面"
                >
                    <button
                        className="u-chip"
                        role="tab"
                        aria-selected={tab === "viewer"}
                        onClick={() => setTab("viewer")}
                    >
                        個股檢視
                    </button>
                    <button
                        className="u-chip"
                        role="tab"
                        aria-selected={tab === "catalog"}
                        onClick={() => setTab("catalog")}
                    >
                        資料目錄
                    </button>
                </div>
            </header>
            <p className="u-notice">
                歷史行情，不是買賣訊號。高低點需在後續交易日才確認。
            </p>
            {!privateMode ? (
                <div className="u-card shared-card">
                    <h2>目前無法顯示個股行情</h2>
                    <p>示範模式不提供真實行情，請切換至本機資料。</p>
                    <SourceInfo>
                        <p>
                            請依 research_web/README.md 設定本機私有模式並啟動
                            API。
                        </p>
                    </SourceInfo>
                </div>
            ) : (
                <>
                    {metadataError && (
                        <div role="alert" className="u-notice">
                            <p>資料目錄暫時無法讀取。</p>
                            <SourceInfo>
                                <p>{metadataError}</p>
                            </SourceInfo>
                            <button
                                className="u-btn"
                                onClick={() => setRetry((n) => n + 1)}
                            >
                                重新讀取
                            </button>
                        </div>
                    )}
                    {tab === "catalog" ? (
                        families ? (
                            <SharedCatalog
                                data={families}
                                onViewer={() => setTab("viewer")}
                            />
                        ) : (
                            <p role="status">正在讀取目錄與核對資料…</p>
                        )
                    ) : (
                        <>
                            <div className="shared-generation">
                                {current ? (
                                    <>
                                        <span>截至 {current.asof}</span>
                                        <SourceInfo>
                                            <p>資料家族：adjusted-daily-v1</p>
                                            <p>
                                                共用資料世代：
                                                <code>
                                                    {current.generation}
                                                </code>
                                            </p>
                                            <p>
                                                SHA-256：
                                                <code>
                                                    {current.status_sha256}
                                                </code>
                                            </p>
                                        </SourceInfo>
                                    </>
                                ) : (
                                    <span>本機歷史行情</span>
                                )}
                            </div>
                            <div className="shared-layout">
                                <div className="u-card shared-card shared-chart-card">
                                    <div className="shared-controls">
                                        <h2>
                                            {symbol?.name || selected}{" "}
                                            <small>
                                                {symbol?.name ? selected : ""}{" "}
                                                {symbol?.market}
                                            </small>
                                        </h2>
                                        <form
                                            onSubmit={(event) => {
                                                event.preventDefault();
                                                openSymbol();
                                            }}
                                        >
                                            <label
                                                htmlFor="shared-symbol"
                                                className="shared-note"
                                            >
                                                股票代號／名稱
                                            </label>
                                            <div className="shared-search">
                                                <input
                                                    id="shared-symbol"
                                                    list="shared-symbols"
                                                    value={search}
                                                    onChange={(event) =>
                                                        setSearch(
                                                            event.target.value,
                                                        )
                                                    }
                                                    placeholder="2330"
                                                />
                                                <button
                                                    className="u-btn u-btn-primary"
                                                    type="submit"
                                                >
                                                    查看
                                                </button>
                                            </div>
                                            <datalist id="shared-symbols">
                                                {symbolOptions}
                                            </datalist>
                                        </form>
                                        <label>
                                            價格基準{" "}
                                            <select
                                                value={basis}
                                                onChange={(event) =>
                                                    setBasis(
                                                        event.target
                                                            .value as Basis,
                                                    )
                                                }
                                            >
                                                <option value="reference_factor_adjusted">
                                                    參考因子還原
                                                </option>
                                                <option value="raw">
                                                    原始價格
                                                </option>
                                                <option value="permanent_adjusted">
                                                    永久還原
                                                </option>
                                            </select>
                                        </label>
                                    </div>
                                    {!namesAvailable && (
                                        <p className="shared-note">
                                            {namesNotice}
                                            <button
                                                className="u-chip"
                                                onClick={() =>
                                                    setNamesRetry((n) => n + 1)
                                                }
                                            >
                                                重試股票名稱
                                            </button>
                                        </p>
                                    )}
                                    <div
                                        className="shared-controls"
                                        aria-label="顯示區間"
                                    >
                                        {[
                                            [60, "3 月"],
                                            [120, "6 月"],
                                            [240, "1 年"],
                                            [720, "3 年"],
                                            [0, "全部"],
                                        ].map(([value, label]) => (
                                            <button
                                                className="u-chip"
                                                key={value}
                                                aria-pressed={range === value}
                                                onClick={() =>
                                                    setRange(Number(value))
                                                }
                                            >
                                                {label}
                                            </button>
                                        ))}
                                    </div>
                                    {!reference && (
                                        <p className="shared-note">
                                            技術指標與高低點僅定義於參考因子還原基準；此基準只顯示價格與成交量。
                                        </p>
                                    )}
                                    {error ? (
                                        <div role="alert" className="u-notice">
                                            <p>
                                                行情暫時無法讀取，請稍後重試。
                                            </p>
                                            <SourceInfo>
                                                <p>{error}</p>
                                            </SourceInfo>
                                            <button
                                                className="u-chip"
                                                onClick={() =>
                                                    setRetry((n) => n + 1)
                                                }
                                            >
                                                重試
                                            </button>
                                        </div>
                                    ) : !current ? (
                                        <p role="status">
                                            正在讀取行情… 準備完成後會自動顯示。
                                        </p>
                                    ) : current.dates.length === 0 ? (
                                        <p>此股票沒有可顯示的日期。</p>
                                    ) : (
                                        <>
                                            <div
                                                className="shared-legend"
                                                aria-live="off"
                                            >
                                                <strong>
                                                    {current.dates[day]}
                                                </strong>
                                                <span>
                                                    開 {fmt(current.open[day])}
                                                </span>
                                                <span>
                                                    高 {fmt(current.high[day])}
                                                </span>
                                                <span>
                                                    低 {fmt(current.low[day])}
                                                </span>
                                                <span>
                                                    收 {fmt(current.close[day])}
                                                </span>
                                                <span
                                                    className={`shared-change-${change?.direction ?? "flat"}`}
                                                >
                                                    漲跌{" "}
                                                    {formatSigned(
                                                        change?.amount ?? null,
                                                    )}{" "}
                                                    · 漲跌幅{" "}
                                                    {formatSigned(
                                                        change?.percent ?? null,
                                                    )}
                                                    {change?.percent != null
                                                        ? "%"
                                                        : ""}
                                                </span>
                                                <span>
                                                    量{" "}
                                                    {fmt(
                                                        current.volume[day],
                                                        0,
                                                    )}{" "}
                                                    張
                                                </span>
                                                {!validPrice(current, day) && (
                                                    <strong>
                                                        當日資料無效：
                                                        {current.quality_reason[
                                                            day
                                                        ] || "缺少 OHLC"}
                                                        （圖上留白）
                                                    </strong>
                                                )}
                                                {reference &&
                                                    ma.map((n) => (
                                                        <span key={n}>
                                                            MA{n}{" "}
                                                            {fmt(
                                                                current.tech[
                                                                    `SMA${n}`
                                                                ]?.[day],
                                                            )}
                                                        </span>
                                                    ))}
                                            </div>
                                            <SharedChart
                                                series={current}
                                                requestedAt={
                                                    loaded!.requestedAt
                                                }
                                                ma={ma}
                                                bb={bb}
                                                pivots={pivots}
                                                oscillator={oscillator}
                                                range={range}
                                                theme={theme}
                                                onCursor={updateCursor}
                                                institutional={
                                                    institutionalSeries
                                                }
                                            />
                                            <p className="shared-note">
                                                中層：成交量（張）。滑鼠滾輪縮放、拖曳平移；高低點畫在極值日，當日尚不一定可知。
                                            </p>
                                            {institutionalField !== "off" && (
                                                <OverlayStatus
                                                    label="法人買賣超（股）"
                                                    overlay={institutional}
                                                />
                                            )}
                                            {showRevenue && (
                                                <>
                                                    <OverlayStatus
                                                        label="月營收"
                                                        overlay={revenue}
                                                    />
                                                    {revenue.data?.status ===
                                                        "ok" && (
                                                        <RevenueChart
                                                            rows={
                                                                revenue.data
                                                                    .rows
                                                            }
                                                            theme={theme}
                                                        />
                                                    )}
                                                </>
                                            )}
                                            <label>
                                                日期數值{" "}
                                                <input
                                                    type="date"
                                                    value={
                                                        current.dates[day] || ""
                                                    }
                                                    min={current.dates[0]}
                                                    max={current.dates.at(-1)}
                                                    onChange={(event) => {
                                                        const i =
                                                            current.dates.indexOf(
                                                                event.target
                                                                    .value,
                                                            );
                                                        if (i >= 0)
                                                            setCursor(i);
                                                    }}
                                                />
                                            </label>
                                        </>
                                    )}
                                </div>
                                <aside>
                                    <div className="u-card shared-card">
                                        <h3>圖層</h3>
                                        <fieldset disabled={!reference}>
                                            <legend>技術指標</legend>
                                            <div className="shared-controls">
                                                {MA_PERIODS.map((n) => (
                                                    <button
                                                        className="u-chip"
                                                        key={n}
                                                        aria-pressed={ma.includes(
                                                            n,
                                                        )}
                                                        onClick={() =>
                                                            setMa(toggle(ma, n))
                                                        }
                                                    >
                                                        MA{n}
                                                    </button>
                                                ))}
                                            </div>
                                            <div className="shared-controls">
                                                <button
                                                    className="u-chip"
                                                    aria-pressed={bb}
                                                    onClick={() => setBb(!bb)}
                                                >
                                                    布林 20
                                                </button>
                                                {[1.5, 4].map((k) => (
                                                    <button
                                                        className="u-chip"
                                                        key={k}
                                                        aria-pressed={pivots.includes(
                                                            k,
                                                        )}
                                                        onClick={() =>
                                                            setPivots(
                                                                toggle(
                                                                    pivots,
                                                                    k,
                                                                ),
                                                            )
                                                        }
                                                    >
                                                        高低點 {k} ATR
                                                    </button>
                                                ))}
                                            </div>
                                            <label>
                                                下方指標{" "}
                                                <select
                                                    value={oscillator}
                                                    onChange={(event) =>
                                                        setOscillator(
                                                            event.target.value,
                                                        )
                                                    }
                                                >
                                                    {[
                                                        "RSI14",
                                                        "MACDHist",
                                                        "ADX14",
                                                        "atr14_pct",
                                                        "none",
                                                    ].map((key) => (
                                                        <option
                                                            key={key}
                                                            value={key}
                                                        >
                                                            {featureLabels[key]}
                                                        </option>
                                                    ))}
                                                </select>
                                            </label>
                                        </fieldset>
                                        <fieldset disabled={!privateMode}>
                                            <legend>籌碼與營收</legend>
                                            <label>
                                                法人買賣超{" "}
                                                <select
                                                    value={institutionalField}
                                                    onChange={(event) =>
                                                        setInstitutionalField(
                                                            event.target
                                                                .value as
                                                                | InstitutionalField
                                                                | "off",
                                                        )
                                                    }
                                                >
                                                    <option value="off">
                                                        隱藏
                                                    </option>
                                                    {INSTITUTIONAL_FIELDS.map(
                                                        (field) => (
                                                            <option
                                                                key={field.id}
                                                                value={field.id}
                                                            >
                                                                {field.label}
                                                            </option>
                                                        ),
                                                    )}
                                                </select>
                                            </label>
                                            <div className="shared-controls">
                                                <button
                                                    className="u-chip"
                                                    aria-pressed={showRevenue}
                                                    onClick={() =>
                                                        setShowRevenue(
                                                            !showRevenue,
                                                        )
                                                    }
                                                >
                                                    月營收
                                                </button>
                                            </div>
                                        </fieldset>
                                    </div>
                                    {current && day >= 0 && (
                                        <div className="u-card shared-card">
                                            <h3>
                                                游標當日 · {current.dates[day]}
                                            </h3>
                                            <dl>
                                                {reference &&
                                                    [
                                                        "BB20_Upper",
                                                        "BB20_Lower",
                                                        "RSI14",
                                                        "MACDHist",
                                                        "ADX14",
                                                        "atr14_pct",
                                                    ].map((key) => (
                                                        <div key={key}>
                                                            <dt>
                                                                {
                                                                    featureLabels[
                                                                        key
                                                                    ]
                                                                }
                                                            </dt>
                                                            <dd>
                                                                {formatFeature(
                                                                    key,
                                                                    current
                                                                        .tech[
                                                                        key
                                                                    ]?.[day],
                                                                )}
                                                            </dd>
                                                        </div>
                                                    ))}
                                                <div>
                                                    <dt>品質</dt>
                                                    <dd>
                                                        {current.quality_reason[
                                                            day
                                                        ] ||
                                                            (validPrice(
                                                                current,
                                                                day,
                                                            )
                                                                ? "正常"
                                                                : "無效")}
                                                    </dd>
                                                </div>
                                            </dl>
                                            {reference &&
                                                current.pivots
                                                    .filter(
                                                        (p) =>
                                                            pivots.includes(
                                                                p.k,
                                                            ) &&
                                                            p.extreme_date ===
                                                                current.dates[
                                                                    day
                                                                ],
                                                    )
                                                    .map((p) => (
                                                        <p
                                                            key={`${p.k}:${p.kind}:${p.confirmed_at}`}
                                                            className="shared-note"
                                                        >
                                                            {p.k} ATR{" "}
                                                            {p.kind === "high"
                                                                ? "高點"
                                                                : "低點"}{" "}
                                                            {fmt(p.price)}，
                                                            <strong>
                                                                {p.confirmed_at}{" "}
                                                                才確認
                                                            </strong>
                                                            。
                                                        </p>
                                                    ))}
                                        </div>
                                    )}
                                    {current && (
                                        <div className="u-card shared-card">
                                            <h3>資料品質</h3>
                                            <p>
                                                {current.dates[0]} –{" "}
                                                {current.dates.at(-1)}
                                            </p>
                                            <p>
                                                {current.dates.length.toLocaleString()}{" "}
                                                交易日 ·{" "}
                                                {invalid.toLocaleString()}{" "}
                                                天資料無效
                                            </p>
                                            <dl>
                                                {reasons.map(
                                                    ([reason, count]) => (
                                                        <div key={reason}>
                                                            <dt>{reason}</dt>
                                                            <dd>{count}</dd>
                                                        </div>
                                                    ),
                                                )}
                                            </dl>
                                            <p className="shared-note">
                                                缺少的數值保留空白，不推估。
                                            </p>
                                            <SourceInfo>
                                                <p>
                                                    均線、布林與轉折全部來自共用資料，瀏覽器不重新計算。
                                                </p>
                                            </SourceInfo>
                                        </div>
                                    )}
                                </aside>
                            </div>
                        </>
                    )}
                </>
            )}
        </section>
    );
}
