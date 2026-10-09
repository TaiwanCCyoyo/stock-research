import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { FoamMap } from "../../visualizations/atlas/FoamMap";
import type { MapNode } from "../../visualizations/atlas/FoamMap";
import { demoAtlas } from "./demo";
import {
    isAtlasData,
    nearestDate,
    observe,
    percent,
    observationBounds,
    exportObservation,
} from "./model";
import type { AtlasData, Encoding, Observation, Measure } from "./model";

function PriceLine({
    stock,
    start,
    end,
    dates,
}: {
    stock: Observation;
    start: number;
    end: number;
    dates: string[];
}) {
    const values = stock.stock.adjusted.slice(Math.max(0, start), end + 1);
    const valid = values.filter((v): v is number => v !== null);
    if (!valid.length) return <p className="quiet">這段期間沒有可用報價。</p>;
    const low = Math.min(...valid),
        high = Math.max(...valid),
        span = high - low || 1;
    let open = false;
    const path = values
        .map((v, i) => {
            if (v === null) {
                open = false;
                return "";
            }
            const p = `${(12 + (i / Math.max(1, values.length - 1)) * 536).toFixed(2)},${(135 - ((v - low) / span) * 110).toFixed(2)}`;
            const s = (open ? "L" : "M") + p;
            open = true;
            return s;
        })
        .join(" ");
    return (
        <>
            <svg
                className="price-line"
                viewBox="0 0 560 160"
                role="img"
                aria-label={`${stock.stock.name}，${dates[Math.max(0, start)]} 至 ${dates[end]}調整收盤走勢`}
            >
                <path d="M12 135H548" stroke="var(--line)" />
                <path
                    d={path}
                    fill="none"
                    stroke="var(--accent)"
                    strokeWidth="2.5"
                />
                <text x="12" y="17" fill="var(--muted)" fontSize="12">
                    {high.toFixed(2)}
                </text>
                <text x="12" y="153" fill="var(--muted)" fontSize="11">
                    {dates[Math.max(0, start)]}
                </text>
                <text
                    x="548"
                    y="153"
                    textAnchor="end"
                    fill="var(--muted)"
                    fontSize="11"
                >
                    {dates[end]}
                </text>
            </svg>
            <span className="micro">
                永久除權調整收盤 · 缺報價處斷線 · 未計現金股利再投入
            </span>
        </>
    );
}
export function MarketPage({
    onResearch,
    active,
}: {
    onResearch: () => void;
    active: boolean;
}) {
    const [data, setData] = useState<AtlasData | null>(null),
        [error, setError] = useState(""),
        [loading, setLoading] = useState(true),
        [retry, setRetry] = useState(0);
    const scrollEvidence = useRef(false);
    const [measure, setMeasure] = useState<Measure>("endpoint");
    const [minGain, setMinGain] = useState(100);
    const [demo, setDemo] = useState(false),
        [requestedIndex, setIndex] = useState(0),
        [windowSize, setWindowSize] = useState(126),
        [customStart, setCustomStart] = useState(0);
    const [encoding, setEncoding] = useState<Encoding>("return"),
        [group, setGroup] = useState<string | null>(null),
        [view, setView] = useState<"groups" | "stocks">("groups");
    const [selected, setSelected] = useState<string | null>(null),
        [playing, setPlaying] = useState(false),
        [motion, setMotion] = useState(true),
        [search, setSearch] = useState("");
    const [tab, setTab] = useState<"rising" | "all" | "missing">("rising"),
        [page, setPage] = useState(0),
        [evidence, setEvidence] = useState(false);
    const bounds = observationBounds(
        data?.dates.length ?? 0,
        windowSize,
        customStart,
    );
    const selectedIndex = Math.max(
        bounds.min,
        Math.min(requestedIndex, bounds.max),
    );
    const deferredIndex = useDeferredValue(selectedIndex);
    const index = Math.max(bounds.min, Math.min(deferredIndex, bounds.max));
    useEffect(() => {
        setIndex(selectedIndex);
    }, [selectedIndex]);
    useEffect(() => {
        const controller = new AbortController();
        setLoading(true);
        setError("");
        const accept = (d: AtlasData) => {
            setData(d);
            setIndex(nearestDate(d.dates, demo ? "2020-10-01" : "2021-04-30"));
            setCustomStart(0);
            setGroup(null);
            setSelected(null);
            setPlaying(false);
            setEncoding(demo ? "weighted" : "return");
            setLoading(false);
        };
        if (demo) {
            accept(demoAtlas());
            return;
        }
        fetch(`${import.meta.env.BASE_URL}data/market-atlas.json`, {
            signal: controller.signal,
        })
            .then(async (r) => {
                if (
                    !r.ok ||
                    !r.headers.get("content-type")?.includes("application/json")
                )
                    throw new Error("歷史資料尚未匯入，請先完成資料準備。");
                const d: unknown = await r.json();
                if (!isAtlasData(d))
                    throw new Error("資料版本或欄位不符合版圖契約");
                accept(d);
            })
            .catch((e: Error) => {
                if (e.name !== "AbortError") {
                    setError(e.message);
                    setData(null);
                    setLoading(false);
                }
            });
        return () => controller.abort();
    }, [demo, retry]);
    useEffect(() => {
        if (!playing || !data || !active || !bounds.available) return;
        const timer = setInterval(
            () =>
                setIndex((i) => {
                    if (i >= data.dates.length - 1) {
                        setPlaying(false);
                        return i;
                    }
                    return Math.min(
                        Math.max(i, bounds.min) + 5,
                        data.dates.length - 1,
                    );
                }),
            850,
        );
        return () => clearInterval(timer);
    }, [playing, data, active, bounds.available, bounds.min]);
    const start = windowSize === 0 ? customStart : index - windowSize;
    const observations = useMemo(
        () =>
            data && bounds.available
                ? observe(data, start, index, encoding, measure)
                : [],
        [data, start, index, encoding, measure, bounds.available],
    );
    const hasComparison =
        windowSize === 0 ? index - 21 > start : index - 21 >= windowSize;
    const earlier = useMemo(
        () =>
            data && hasComparison
                ? observe(
                      data,
                      windowSize === 0
                          ? start
                          : Math.max(-1, index - 21 - windowSize),
                      Math.max(0, index - 21),
                      encoding,
                      measure,
                  )
                : [],
        [data, start, index, windowSize, encoding, measure, hasComparison],
    );
    const leaders = useMemo(
        () =>
            observations
                .filter(
                    (r) => r.gain !== null && r.gain >= minGain && r.weight > 0,
                )
                .sort(
                    (a, b) =>
                        b.weight - a.weight ||
                        a.stock.code.localeCompare(b.stock.code),
                ),
        [observations, minGain],
    );
    const groups = useMemo(
        () => new Map(data?.groups.map((g) => [g.id, g.label]) ?? []),
        [data],
    );
    const nodes = useMemo(() => {
        if (!data) return [];
        const selectedRows = group
            ? leaders.filter((r) => r.stock.groupIds[0] === group)
            : leaders;
        if (view === "stocks" || group)
            return selectedRows.slice(0, 32).map((r) => ({
                id: r.stock.code,
                weight: r.weight,
                group: r.stock.groupIds[0] ?? "unknown",
                label: r.stock.name,
                detail: r.stock.code,
                gain: percent(r.gain),
                count: 1,
            }));
        const result = new Map<string, MapNode>();
        for (const r of [...selectedRows].sort(
            (a, b) => (b.gain ?? 0) - (a.gain ?? 0),
        )) {
            const id = r.stock.groupIds[0] ?? "unknown",
                old = result.get(id);
            if (old) {
                old.weight += r.weight;
                old.count++;
            } else
                result.set(id, {
                    id,
                    weight: r.weight,
                    group: id,
                    label:
                        data.groups.find((g) => g.id === id)?.label ??
                        "分類待補",
                    detail: `領漲 ${r.stock.name}`,
                    gain: percent(r.gain),
                    count: 1,
                });
        }
        return [...result.values()]
            .sort((a, b) => b.weight - a.weight)
            .slice(0, 28);
    }, [leaders, group, view, data]);
    const displayed = useMemo(
        () =>
            observations
                .filter(
                    (r) =>
                        (!group || r.stock.groupIds[0] === group) &&
                        (!search ||
                            `${r.stock.code} ${r.stock.name} ${groups.get(r.stock.groupIds[0])}`.includes(
                                search,
                            )) &&
                        (tab === "all" || tab === "missing"
                            ? tab !== "missing" || r.reason !== null
                            : r.gain !== null &&
                              r.gain >= minGain &&
                              r.weight > 0),
                )
                .sort(
                    (a, b) =>
                        (b.gain ?? -Infinity) - (a.gain ?? -Infinity) ||
                        a.stock.code.localeCompare(b.stock.code),
                ),
        [observations, group, search, tab, groups, minGain],
    );
    useEffect(
        () => setPage(0),
        [group, search, tab, index, windowSize, measure, minGain],
    );
    const selectedRow = observations.find((r) => r.stock.code === selected);
    const priorCodes = new Set(
        earlier
            .filter((r) => r.gain !== null && r.gain >= minGain && r.weight > 0)
            .map((r) => r.stock.code),
    );
    const newRows = hasComparison
        ? leaders.filter((r) => !priorCodes.has(r.stock.code))
        : [];
    const currentCodes = new Set(leaders.map((r) => r.stock.code));
    const fadedRows = earlier.filter(
        (r) =>
            r.gain !== null &&
            r.gain >= minGain &&
            r.weight > 0 &&
            !currentCodes.has(r.stock.code),
    );
    useEffect(() => {
        if (selected && scrollEvidence.current) {
            document.querySelector(".stock-inspector")?.scrollIntoView({
                block: "center",
                behavior:
                    motion &&
                    !window.matchMedia("(prefers-reduced-motion: reduce)")
                        .matches
                        ? "smooth"
                        : "instant",
            });
            scrollEvidence.current = false;
        }
    }, [selected, motion]);
    const inspect = (code: string) => {
        scrollEvidence.current = true;
        setSelected(code);
        if (code === selected)
            document
                .querySelector(".stock-inspector")
                ?.scrollIntoView({ block: "center", behavior: "instant" });
    };
    const clickNode = (id: string) => {
        if (view === "groups" && !group) {
            setGroup(id);
            setSelected(null);
        } else inspect(id);
    };
    const setDate = (i: number) => {
        setPlaying(false);
        setIndex(Math.max(bounds.min, Math.min(i, bounds.max)));
    };
    const download = () => {
        if (!data) return;
        const packet = {
            schema: "opportunity-observations.v1",
            catalogHash: data.catalogHash,
            classificationAsOf: data.classificationAsOf,
            start: data.dates[start] ?? null,
            end: data.dates[index],
            encoding,
            measure,
            rule: {
                gainExponent: 2,
                cap100Multiplier: 1.25,
                minGainPercent: minGain,
            },
            provenance: data.provenance,
            limitations: data.limitations,
            observations: observations.map((r) => exportObservation(data, r)),
        };
        const url = URL.createObjectURL(
            new Blob([JSON.stringify(packet, null, 2)], {
                type: "application/json",
            }),
        );
        const a = document.createElement("a");
        a.href = url;
        a.download = `opportunities-${data.dates[index]}.json`;
        a.click();
        setTimeout(() => URL.revokeObjectURL(url), 1000);
    };
    return (
        <>
            <section className="atlas-hero">
                <div className="mountains" aria-hidden="true">
                    <i />
                    <i />
                    <i />
                </div>
                <div className="eyebrow">MARKET · IN MOTION</div>
                <div className="hero-line">
                    <div>
                        <h1>市場勢力地圖</h1>
                        <p>時間往前，新的勢力浮現。</p>
                    </div>
                    <div className="hero-date">
                        <strong>{data?.dates[index] ?? "—"}</strong>
                        <span>
                            {demo
                                ? "互動展示 · 全部為假想資料"
                                : "台灣市場 · 已保存的歷史行情"}
                        </span>
                    </div>
                </div>
                <div className="hero-bottom">
                    <span>從全貌看見輪動，從一檔股票找到證據。</span>
                    <button
                        className="text-button"
                        onClick={() => setDemo((v) => !v)}
                    >
                        {demo ? "返回真實歷史" : "試玩含市值的示意版"} ↗
                    </button>
                </div>
            </section>
            {loading ? (
                <div className="surface state-message" role="status">
                    正在整理歷史版圖…
                </div>
            ) : error ? (
                <div className="surface state-message" role="alert">
                    <h2>歷史版圖尚未準備好</h2>
                    <p>{error}</p>
                    <button
                        className="primary-button"
                        onClick={() => setRetry((v) => v + 1)}
                    >
                        重新載入
                    </button>
                    <button
                        className="text-button"
                        onClick={() => setDemo(true)}
                    >
                        先體驗明確標示的示意版
                    </button>
                </div>
            ) : (
                data && (
                    <>
                        {demo && (
                            <div className="notice">
                                展示模式：股票、價格、市值皆為假想資料，用來體驗細胞消長與大小規則。
                            </div>
                        )}
                        <section className="surface timeline">
                            <button
                                className="play-button"
                                disabled={
                                    !bounds.available ||
                                    bounds.min === bounds.max
                                }
                                aria-label={
                                    playing ? "暫停時間演變" : "播放時間演變"
                                }
                                onClick={() => {
                                    if (index === data.dates.length - 1)
                                        setIndex(bounds.min);
                                    setPlaying((v) => !v);
                                }}
                            >
                                {playing ? "Ⅱ" : "▶"}
                            </button>
                            <div className="timeline-main">
                                <div className="timeline-top">
                                    <strong>
                                        時光軸 <span>／ 拉動觀察日期</span>
                                    </strong>
                                    <span>
                                        可觀察 {data.dates[bounds.min]} —{" "}
                                        {data.dates.at(-1)}
                                    </span>
                                </div>
                                <input
                                    type="range"
                                    aria-label="觀察日期時間軸"
                                    min={bounds.min}
                                    max={bounds.max}
                                    disabled={
                                        !bounds.available ||
                                        bounds.min === bounds.max
                                    }
                                    value={selectedIndex}
                                    onChange={(e) =>
                                        setDate(Number(e.target.value))
                                    }
                                />
                                <div className="timeline-ticks">
                                    {[0, 0.25, 0.5, 0.75, 1].map((v) => (
                                        <span key={v}>
                                            {data.dates[
                                                Math.round(
                                                    bounds.min +
                                                        v *
                                                            (bounds.max -
                                                                bounds.min),
                                                )
                                            ].slice(0, 7)}
                                        </span>
                                    ))}
                                </div>
                            </div>
                            <label className="date-control">
                                <span className="sr-only">直接選日期</span>
                                <input
                                    type="date"
                                    min={data.dates[bounds.min]}
                                    max={data.dates.at(-1)}
                                    disabled={!bounds.available}
                                    value={data.dates[selectedIndex]}
                                    onChange={(e) =>
                                        e.target.value &&
                                        setDate(
                                            nearestDate(
                                                data.dates,
                                                e.target.value,
                                            ),
                                        )
                                    }
                                />
                            </label>
                        </section>
                        {selectedIndex !== index && (
                            <p className="caption" role="status">
                                已選擇 {data.dates[selectedIndex]}
                                ，正在更新觀察資料…
                            </p>
                        )}
                        <div className="atlas-toolbar">
                            <div className="segmented">
                                <button
                                    aria-pressed={view === "groups"}
                                    onClick={() => {
                                        setView("groups");
                                        setGroup(null);
                                    }}
                                >
                                    族群版圖
                                </button>
                                <button
                                    aria-pressed={view === "stocks"}
                                    onClick={() => {
                                        setView("stocks");
                                        setGroup(null);
                                    }}
                                >
                                    個股版圖
                                </button>
                            </div>
                            <label>
                                共同區間{" "}
                                <select
                                    aria-label="共同觀察區間"
                                    value={windowSize}
                                    onChange={(e) => {
                                        setWindowSize(Number(e.target.value));
                                        setPlaying(false);
                                    }}
                                >
                                    <option value={63}>近 63 交易日</option>
                                    <option value={126}>近 126 交易日</option>
                                    <option value={252}>近 252 交易日</option>
                                    <option value={504}>
                                        近 504 交易日 · 約 2 年
                                    </option>
                                    <option value={756}>
                                        近 756 交易日 · 約 3 年
                                    </option>
                                    <option value={0}>自訂起點</option>
                                </select>
                            </label>
                            {windowSize === 0 && (
                                <input
                                    aria-label="自訂共同起點"
                                    type="date"
                                    min={data.dates[0]}
                                    max={
                                        data.dates[
                                            Math.max(0, data.dates.length - 2)
                                        ]
                                    }
                                    value={data.dates[customStart]}
                                    onChange={(e) =>
                                        e.target.value &&
                                        setCustomStart(
                                            nearestDate(
                                                data.dates,
                                                e.target.value,
                                            ),
                                        )
                                    }
                                />
                            )}
                            <label>
                                飆漲門檻{" "}
                                <select
                                    aria-label="飆漲門檻"
                                    value={minGain}
                                    onChange={(e) =>
                                        setMinGain(Number(e.target.value))
                                    }
                                >
                                    <option value={60}>+60%</option>
                                    <option value={80}>+80%</option>
                                    <option value={100}>翻倍 · +100%</option>
                                    <option value={200}>3 倍 · +200%</option>
                                    <option value={400}>5 倍 · +400%</option>
                                    <option value={900}>10 倍 · +900%</option>
                                </select>
                            </label>
                            <label>
                                觀察{" "}
                                <select
                                    aria-label="漲幅觀察方式"
                                    value={measure}
                                    onChange={(e) =>
                                        setMeasure(e.target.value as Measure)
                                    }
                                >
                                    <option value="endpoint">觀察日漲幅</option>
                                    <option value="peak">
                                        期間最高 · 事後回看
                                    </option>
                                </select>
                            </label>
                            <label>
                                大小{" "}
                                <select
                                    aria-label="大小依據"
                                    value={encoding}
                                    onChange={(e) =>
                                        setEncoding(e.target.value as Encoding)
                                    }
                                >
                                    <option value="return">漲幅直徑</option>
                                    <option value="weighted" disabled={!demo}>
                                        漲幅 × 溫和市值
                                    </option>
                                </select>
                            </label>
                            <label className="motion-toggle">
                                <input
                                    type="checkbox"
                                    checked={motion}
                                    onChange={(e) =>
                                        setMotion(e.target.checked)
                                    }
                                />
                                柔和動態
                            </label>
                        </div>
                        {measure === "peak" && (
                            <div className="notice">
                                期間最高：從共同起點到區間內最高收盤，保留曾大漲後回落的機會。這是事後回看，並非可事先知道的賣點。
                            </div>
                        )}
                        {!demo && (
                            <div className="caption">
                                目錄收錄 {data.stocks.length.toLocaleString()}{" "}
                                檔，並非完整歷史可投資名單。歷史市值尚未齊備，目前用漲幅直徑；分類來自{" "}
                                {data.classificationAsOf} 快照，屬事後整理。
                                本頁顯示研究目錄的日期範圍，較早的官方行情尚未接入。
                            </div>
                        )}
                        <div className="observation-period" aria-live="polite">
                            <strong>
                                漲幅起點 {data.dates[start] ?? "資料不足"}
                            </strong>
                            <span>→</span>
                            <strong>觀察日 {data.dates[index]}</strong>
                            <span>
                                {measure === "peak"
                                    ? "計算到這段期間內的最高收盤，各股最高日另列"
                                    : "以這兩天的調整收盤計算漲幅"}{" "}
                                · {windowSize || index - start} 個交易日
                            </span>
                        </div>
                        {!bounds.available && (
                            <div className="notice">
                                資料長度不足以計算此區間，請選擇較短的共同區間。
                            </div>
                        )}
                        <div className="atlas-grid">
                            <section className="surface map-panel">
                                <div className="panel-heading">
                                    <div>
                                        <div className="breadcrumb">
                                            <button
                                                onClick={() => {
                                                    setGroup(null);
                                                    setSelected(null);
                                                }}
                                            >
                                                全市場
                                            </button>
                                            {group && (
                                                <>
                                                    {" "}
                                                    /{" "}
                                                    <span>
                                                        {groups.get(group)}
                                                    </span>
                                                </>
                                            )}
                                        </div>
                                        <h2>
                                            {group
                                                ? groups.get(group)
                                                : "此刻的勢力版圖"}
                                        </h2>
                                        <p>
                                            {view === "groups" && !group
                                                ? "族群面積＝成員權重加總；百分比為領漲個股漲幅。"
                                                : "同市值時，漲幅兩倍，等效直徑兩倍。"}
                                        </p>
                                    </div>
                                    <span className="count-label">
                                        {leaders.length} 檔 ≥ +{minGain}%
                                    </span>
                                </div>
                                <FoamMap
                                    period={`${data.dates[start]} → ${data.dates[index]}`}
                                    nodes={nodes}
                                    selected={selected}
                                    onSelect={clickNode}
                                    motion={motion}
                                />
                                <div className="map-footnote">
                                    <span>
                                        {data.dates[start] ?? "起點不足"} →{" "}
                                        {data.dates[index]}
                                    </span>
                                    <span>
                                        顯示前 {nodes.length} 個
                                        {view === "groups" && !group
                                            ? "族群"
                                            : "個股"}{" "}
                                        · 當日相對權重配置，完整名單見下方
                                    </span>
                                </div>
                            </section>
                            <aside className="surface changes-panel">
                                <div className="panel-heading">
                                    <div>
                                        <h2>勢力交替</h2>
                                        <p>對照 21 交易日前的畫面</p>
                                    </div>
                                    <span className="tiny-orbit" />
                                </div>
                                <section>
                                    <div className="event-heading">
                                        <span className="event-symbol">↗</span>
                                        <h3>新浮現</h3>
                                        <strong>
                                            {hasComparison
                                                ? newRows.length
                                                : "—"}
                                        </strong>
                                    </div>
                                    {newRows.slice(0, 5).map((r) => (
                                        <button
                                            className="event-row"
                                            key={r.stock.code}
                                            onClick={() =>
                                                inspect(r.stock.code)
                                            }
                                        >
                                            <span>
                                                <small>{r.stock.code}</small>
                                                {r.stock.name}
                                            </span>
                                            <b>{percent(r.gain)}</b>
                                        </button>
                                    ))}
                                    {!newRows.length && (
                                        <p className="quiet">
                                            {hasComparison
                                                ? "這段時間沒有新跨越門檻的股票。"
                                                : "更早的完整觀察區間不足，暫不判定浮現或移出。"}
                                        </p>
                                    )}
                                </section>
                                <section>
                                    <div className="event-heading">
                                        <span className="event-symbol faded">
                                            ↘
                                        </span>
                                        <h3>移出此刻版圖</h3>
                                        <strong>
                                            {hasComparison
                                                ? fadedRows.length
                                                : "—"}
                                        </strong>
                                    </div>
                                    {fadedRows.slice(0, 4).map((r) => (
                                        <button
                                            className="event-row"
                                            key={r.stock.code}
                                            onClick={() =>
                                                inspect(r.stock.code)
                                            }
                                        >
                                            <span>
                                                <small>{r.stock.code}</small>
                                                {r.stock.name}
                                            </span>
                                            <b>
                                                {percent(
                                                    observations.find(
                                                        (o) =>
                                                            o.stock.code ===
                                                            r.stock.code,
                                                    )?.gain ?? null,
                                                )}
                                            </b>
                                        </button>
                                    ))}
                                    {!fadedRows.length && (
                                        <p className="quiet">
                                            {hasComparison
                                                ? "沒有移出記錄。"
                                                : "較早區間資料不足。"}
                                        </p>
                                    )}
                                </section>
                                <div className="note-box">
                                    浮現指所選區間漲幅跨越 +{minGain}
                                    %；移出可能是回落、區間移動或資料缺口，並非買賣訊號。
                                </div>
                            </aside>
                        </div>
                        {selectedRow && (
                            <section
                                className="surface stock-inspector"
                                aria-label="個股證據"
                            >
                                <div className="inspector-heading">
                                    <div>
                                        <span className="eyebrow">
                                            STOCK / EVIDENCE
                                        </span>
                                        <h2>
                                            {selectedRow.stock.name}{" "}
                                            <small>
                                                {selectedRow.stock.code}
                                            </small>
                                        </h2>
                                        <span className="quiet">
                                            {selectedRow.stock.groupIds
                                                .map(
                                                    (id) =>
                                                        groups.get(id) ?? id,
                                                )
                                                .join(" · ")}
                                        </span>
                                    </div>
                                    <strong className="stock-return">
                                        {percent(selectedRow.gain)}
                                    </strong>
                                    <button
                                        className="icon-button"
                                        aria-label="關閉個股明細"
                                        onClick={() => setSelected(null)}
                                    >
                                        ×
                                    </button>
                                </div>
                                <p className="stock-period">
                                    這筆 {percent(selectedRow.gain)}：從{" "}
                                    <strong>{data.dates[start]}</strong> 到{" "}
                                    <strong>
                                        {selectedRow.observedEnd === null
                                            ? "最高日未知"
                                            : data.dates[
                                                  selectedRow.observedEnd
                                              ]}
                                    </strong>
                                    {measure === "peak"
                                        ? "（期間最高收盤日）"
                                        : "（觀察日收盤）"}
                                    。以下價格依同一起訖日排列。
                                </p>
                                <div className="inspector-body">
                                    <div>
                                        {selectedRow.observedEnd === null ? (
                                            <p className="quiet">
                                                最高日未知，無法核對價格區間。
                                            </p>
                                        ) : (
                                            <PriceLine
                                                stock={selectedRow}
                                                start={start}
                                                end={selectedRow.observedEnd}
                                                dates={data.dates}
                                            />
                                        )}
                                    </div>
                                    <div className="price-facts">
                                        <div>
                                            <span>
                                                原始收盤
                                                <br />
                                                {measure === "peak"
                                                    ? selectedRow.observedEnd ===
                                                      null
                                                        ? "最高日未知"
                                                        : data.dates[
                                                              selectedRow
                                                                  .observedEnd
                                                          ]
                                                    : ""}
                                            </span>
                                            <strong>
                                                {selectedRow.stock.raw[
                                                    start
                                                ]?.toFixed(2) ?? "—"}{" "}
                                                →{" "}
                                                {selectedRow.observedEnd ===
                                                null
                                                    ? "未知"
                                                    : (selectedRow.stock.raw[
                                                          selectedRow
                                                              .observedEnd
                                                      ]?.toFixed(2) ??
                                                      "—")}{" "}
                                                元
                                            </strong>
                                        </div>
                                        <div>
                                            <span>調整收盤</span>
                                            <strong>
                                                {selectedRow.stock.adjusted[
                                                    start
                                                ]?.toFixed(4) ?? "—"}{" "}
                                                →{" "}
                                                {selectedRow.observedEnd ===
                                                null
                                                    ? "未知"
                                                    : (selectedRow.stock.adjusted[
                                                          selectedRow
                                                              .observedEnd
                                                      ]?.toFixed(4) ?? "—")}
                                            </strong>
                                        </div>
                                        <div>
                                            <span>歷史市值</span>
                                            <strong>
                                                {selectedRow.cap === null
                                                    ? "尚缺資料"
                                                    : `${selectedRow.cap.toLocaleString()} 億`}
                                            </strong>
                                        </div>
                                        <div>
                                            <span>面積權重</span>
                                            <strong>
                                                {selectedRow.reason ??
                                                    selectedRow.weight.toFixed(
                                                        4,
                                                    )}
                                            </strong>
                                        </div>
                                    </div>
                                    <div className="participation-box">
                                        <h3>誰把握住這段漲勢？</h3>
                                        <p>
                                            尚無與這個區間配對的完整策略持倉或
                                            ETF 歷史快照。未知不能當成錯過。
                                        </p>
                                        <button
                                            className="text-button"
                                            onClick={onResearch}
                                        >
                                            查看研究交易證據 ↗
                                        </button>
                                    </div>
                                </div>
                            </section>
                        )}
                        <section className="surface stock-table">
                            <div className="table-heading">
                                <div>
                                    <h2>每一個機會，都能查清楚。</h2>
                                    <p>
                                        清單保留所有資料，不受版圖顯示數量限制。
                                    </p>
                                </div>
                                <label className="search-field">
                                    <span className="sr-only">
                                        搜尋股票或族群
                                    </span>
                                    <input
                                        placeholder="搜尋名稱、代碼、族群…"
                                        value={search}
                                        onChange={(e) =>
                                            setSearch(e.target.value)
                                        }
                                    />
                                </label>
                            </div>
                            <div className="table-controls">
                                <div className="segmented">
                                    <button
                                        aria-pressed={tab === "rising"}
                                        onClick={() => setTab("rising")}
                                    >
                                        漲幅 ≥{minGain}%
                                    </button>
                                    <button
                                        aria-pressed={tab === "all"}
                                        onClick={() => setTab("all")}
                                    >
                                        全部股票
                                    </button>
                                    <button
                                        aria-pressed={tab === "missing"}
                                        onClick={() => setTab("missing")}
                                    >
                                        資料缺口
                                    </button>
                                </div>
                                <button
                                    className="text-button"
                                    onClick={download}
                                >
                                    下載完整觀察資料 ↓
                                </button>
                            </div>
                            <div className="table-scroll">
                                <table>
                                    <thead>
                                        <tr>
                                            <th>股票</th>
                                            <th>族群</th>
                                            <th>
                                                {measure === "peak"
                                                    ? "期間最高漲幅"
                                                    : "起訖日漲幅"}
                                            </th>
                                            <th>起訖日期</th>
                                            <th>起日 → 迄日原始收盤</th>
                                            <th>資料狀態</th>
                                            <th />
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {displayed
                                            .slice(page * 20, page * 20 + 20)
                                            .map((r) => (
                                                <tr
                                                    key={r.stock.code}
                                                    className={
                                                        selected ===
                                                        r.stock.code
                                                            ? "selected-row"
                                                            : ""
                                                    }
                                                >
                                                    <td>
                                                        <strong>
                                                            {r.stock.name}
                                                        </strong>
                                                        <small>
                                                            {r.stock.code}
                                                        </small>
                                                    </td>
                                                    <td>
                                                        {groups.get(
                                                            r.stock.groupIds[0],
                                                        ) ?? "分類待補"}
                                                    </td>
                                                    <td
                                                        className={
                                                            r.gain !== null &&
                                                            r.gain < 0
                                                                ? "negative"
                                                                : "positive"
                                                        }
                                                    >
                                                        {percent(r.gain)}
                                                    </td>
                                                    <td className="period-cell">
                                                        {data.dates[start] ??
                                                            "—"}
                                                        <br />→{" "}
                                                        {r.observedEnd === null
                                                            ? "最高日未知"
                                                            : (data.dates[
                                                                  r.observedEnd
                                                              ] ?? "—")}
                                                        {measure === "peak" && (
                                                            <small>
                                                                最高日
                                                            </small>
                                                        )}
                                                    </td>
                                                    <td>
                                                        {r.stock.raw[
                                                            start
                                                        ]?.toFixed(2) ??
                                                            "—"}{" "}
                                                        →{" "}
                                                        {r.observedEnd === null
                                                            ? "未知"
                                                            : (r.stock.raw[
                                                                  r.observedEnd
                                                              ]?.toFixed(2) ??
                                                              "—")}
                                                        {measure === "peak" && (
                                                            <small>
                                                                最高日{" "}
                                                                {r.observedEnd ===
                                                                null
                                                                    ? "未知"
                                                                    : data
                                                                          .dates[
                                                                          r
                                                                              .observedEnd
                                                                      ]}
                                                            </small>
                                                        )}
                                                    </td>
                                                    <td>
                                                        {r.reason ??
                                                            "價格可核對"}
                                                    </td>
                                                    <td>
                                                        <button
                                                            className="text-button"
                                                            aria-label={`查看${r.stock.name}證據`}
                                                            onClick={() =>
                                                                inspect(
                                                                    r.stock
                                                                        .code,
                                                                )
                                                            }
                                                        >
                                                            查看 ↗
                                                        </button>
                                                    </td>
                                                </tr>
                                            ))}
                                    </tbody>
                                </table>
                            </div>
                            {!displayed.length && (
                                <div className="empty-inline">
                                    沒有符合條件的股票。
                                </div>
                            )}
                            <div className="pagination">
                                <span>
                                    共 {displayed.length.toLocaleString()} 檔 ·
                                    第 {page + 1} /{" "}
                                    {Math.max(
                                        1,
                                        Math.ceil(displayed.length / 20),
                                    )}{" "}
                                    頁
                                </span>
                                <div>
                                    <button
                                        disabled={page === 0}
                                        onClick={() => setPage((v) => v - 1)}
                                    >
                                        上一頁
                                    </button>
                                    <button
                                        disabled={
                                            (page + 1) * 20 >= displayed.length
                                        }
                                        onClick={() => setPage((v) => v + 1)}
                                    >
                                        下一頁
                                    </button>
                                </div>
                            </div>
                        </section>
                        <section className="source-section">
                            <button
                                className="text-button"
                                aria-expanded={evidence}
                                onClick={() => setEvidence((v) => !v)}
                            >
                                {evidence ? "−" : "+"} 資料來源、呈現規則與限制
                            </button>
                            {evidence && (
                                <div className="source-details">
                                    <p>
                                        個股面積 ∝ 正漲幅²；有歷史市值時，再乘以
                                        (市值 / 50 億) ^ (ln 1.25 / ln
                                        100)。非圓形細胞使用等效直徑。面積用於視覺強調，不等於可賺金額。細胞圓角會帶來小於
                                        2%
                                        的著色面積比例誤差；動畫過渡期間不適合拿尺比較。
                                    </p>
                                    <ul>
                                        {data.limitations.map((x, i) => (
                                            <li key={i}>{x}</li>
                                        ))}
                                    </ul>
                                    <p>
                                        目錄身分：
                                        <code>{data.catalogHash}</code>
                                    </p>
                                    <details>
                                        <summary>原始來源記錄</summary>
                                        <pre>
                                            {JSON.stringify(
                                                data.provenance,
                                                null,
                                                2,
                                            )}
                                        </pre>
                                    </details>
                                </div>
                            )}
                        </section>
                    </>
                )
            )}
        </>
    );
}
