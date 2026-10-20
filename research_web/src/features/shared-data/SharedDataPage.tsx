import { useCallback, useEffect, useState } from "react";
import { artifactMode } from "../../api/artifactMode";
import { readShared } from "./api";
import {
    MA_PERIODS,
    numeric,
    qualityCounts,
    validPrice,
    type Basis,
    type Families,
    type SharedSeries,
    type SharedSymbol,
} from "./model";
import { SharedChart } from "./SharedChart";
import { SharedCatalog } from "./SharedCatalog";
import "./shared-data.css";

const fmt = (v: unknown) =>
    numeric(v) ? v.toLocaleString("zh-TW", { maximumFractionDigits: 3 }) : "—";
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
    const [namesAvailable, setNamesAvailable] = useState(true);
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
    const [pivots, setPivots] = useState([1.5]);
    const [oscillator, setOscillator] = useState("RSI14");
    const [range, setRange] = useState(240);
    const [cursor, setCursor] = useState(-1);
    const updateCursor = useCallback((i: number) => setCursor(i), []);
    useEffect(() => {
        if (!privateMode) return;
        const controller = new AbortController();
        setMetadataError("");
        setFamilies(null);
        setSymbols([]);
        readShared<Families>("families", controller.signal)
            .then((data) => {
                if (!controller.signal.aborted) setFamilies(data);
            })
            .catch((reason: Error) => {
                if (!controller.signal.aborted)
                    setMetadataError(reason.message);
            });
        readShared<{ symbols: SharedSymbol[]; namesAvailable: boolean }>(
            "adjusted-daily-v1/symbols",
            controller.signal,
        )
            .then((data) => {
                if (!controller.signal.aborted) {
                    setSymbols(data.symbols);
                    setNamesAvailable(data.namesAvailable);
                }
            })
            .catch((reason: Error) => {
                if (!controller.signal.aborted) {
                    setNamesAvailable(false);
                    setMetadataError((old) =>
                        [old, reason.message].filter(Boolean).join("；"),
                    );
                }
            });
        return () => controller.abort();
    }, [privateMode, retry, metadataGeneration]);
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
    const reference = basis === "reference_factor_adjusted";
    const day =
        current && cursor >= 0
            ? Math.min(cursor, current.dates.length - 1)
            : -1;
    const reasons = current ? qualityCounts(current) : [];
    const invalid = reasons.reduce((total, [, count]) => total + count, 0);
    const toggle = (values: number[], value: number) =>
        values.includes(value)
            ? values.filter((x) => x !== value)
            : [...values, value].sort((a, b) => a - b);
    const openSymbol = () => {
        const input = search.trim();
        const found = symbols.find(
            (item) =>
                item.code === input.split(/\s+/)[0] || item.name === input,
        );
        const target = found?.code || input;
        if (/^[A-Za-z0-9._-]+$/.test(target)) {
            location.hash = `data/${encodeURIComponent(target)}`;
            setSearch("");
        }
    };
    return (
        <section className="shared-data">
            <header className="shared-heading">
                <div>
                    <h1>共用資料</h1>
                    <p>研究共用的日價、指標與已確認高低點。</p>
                </div>
                <div
                    className="shared-controls"
                    role="tablist"
                    aria-label="共用資料頁面"
                >
                    <button
                        role="tab"
                        aria-selected={tab === "viewer"}
                        onClick={() => setTab("viewer")}
                    >
                        個股檢視
                    </button>
                    <button
                        role="tab"
                        aria-selected={tab === "catalog"}
                        onClick={() => setTab("catalog")}
                    >
                        資料目錄
                    </button>
                </div>
            </header>
            {!privateMode ? (
                <div className="shared-card">
                    <h2>需要本機私有資料</h2>
                    <p>
                        目前是合成示範模式；共用資料檢視不提供示範行情。請依
                        research_web/README.md 設定本機私有模式並啟動 API。
                    </p>
                </div>
            ) : (
                <>
                    {metadataError && (
                        <p role="alert">
                            {metadataError}{" "}
                            <button onClick={() => setRetry((n) => n + 1)}>
                                重新讀取
                            </button>
                        </p>
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
                                <strong>adjusted-daily-v1</strong>
                                {current ? (
                                    <>
                                        <span>截至 {current.asof}</span>
                                        <span>
                                            世代{" "}
                                            <code>{current.generation}</code>
                                        </span>
                                        <details>
                                            <summary>驗證識別</summary>
                                            <code>{current.status_sha256}</code>
                                        </details>
                                    </>
                                ) : (
                                    <span>唯讀本機共用資料</span>
                                )}
                            </div>
                            <div className="shared-layout">
                                <div className="shared-card shared-chart-card">
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
                                                <button type="submit">
                                                    查看
                                                </button>
                                            </div>
                                            <datalist id="shared-symbols">
                                                {symbols.map((item) => (
                                                    <option
                                                        key={item.code}
                                                        value={`${item.code} ${item.name || ""}`}
                                                    />
                                                ))}
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
                                            股票名稱目前不可讀，仍可用代號查詢。
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
                                        <p role="alert">
                                            {error}{" "}
                                            <button
                                                onClick={() =>
                                                    setRetry((n) => n + 1)
                                                }
                                            >
                                                重試
                                            </button>
                                        </p>
                                    ) : !current ? (
                                        <p role="status">
                                            正在讀取／核對共用資料…
                                            暖機時會自動重試。
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
                                                <span>
                                                    量{" "}
                                                    {fmt(current.volume[day])}{" "}
                                                    張
                                                </span>
                                                {!validPrice(current, day) && (
                                                    <strong>
                                                        無效列：
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
                                            />
                                            <p className="shared-note">
                                                中層：成交量（張）。滑鼠滾輪縮放、拖曳平移；高低點畫在極值日，當日尚不一定可知。
                                            </p>
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
                                    <div className="shared-card">
                                        <h3>圖層</h3>
                                        <fieldset disabled={!reference}>
                                            <legend>共用技術指標</legend>
                                            <div className="shared-controls">
                                                {MA_PERIODS.map((n) => (
                                                    <button
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
                                                    aria-pressed={bb}
                                                    onClick={() => setBb(!bb)}
                                                >
                                                    布林 20
                                                </button>
                                                {[1.5, 4].map((k) => (
                                                    <button
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
                                                            {key === "none"
                                                                ? "隱藏"
                                                                : key ===
                                                                    "atr14_pct"
                                                                  ? "ATR14 比例"
                                                                  : key}
                                                        </option>
                                                    ))}
                                                </select>
                                            </label>
                                        </fieldset>
                                    </div>
                                    {current && day >= 0 && (
                                        <div className="shared-card">
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
                                                                {key ===
                                                                "atr14_pct"
                                                                    ? "ATR14 比例"
                                                                    : key}
                                                            </dt>
                                                            <dd>
                                                                {fmt(
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
                                        <div className="shared-card">
                                            <h3>資料品質 · 全部回傳期間</h3>
                                            <p>
                                                {current.dates[0]} –{" "}
                                                {current.dates.at(-1)}
                                            </p>
                                            <p>
                                                {current.dates.length.toLocaleString()}{" "}
                                                交易日 ·{" "}
                                                {invalid.toLocaleString()}{" "}
                                                無效列
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
                                                缺值保留空白，不插補。均線、布林與轉折全部來自共用資料，瀏覽器不重新計算。
                                            </p>
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
