import { useEffect, useMemo, useRef, useState } from "react";
import { readArtifact } from "../../api/artifacts";
import { priceExplanation } from "../../components/priceExplanation.ts";
import { createOpportunityFixture } from "../../domain/opportunities/fixture.ts";
import {
    buildMarketView,
    comparePortfolio,
    POSITIVE_MOVE_SHARE_VERSION,
    validateBundle,
} from "../../domain/opportunities/model.ts";
import type {
    OpportunityBundle,
    OpportunityPortfolio,
    OpportunityRow,
    PortfolioComparison,
} from "../../domain/opportunities/types.ts";
import type { LabCase } from "../wave-lab/types.ts";
import { WaveLabPage } from "../wave-lab/WaveLabPage";
import { OpportunityMap } from "../../visualizations/opportunity/OpportunityMap";
import { CapitalCards, OpportunityTimeline, Sparkline } from "./evidence";
import { toLabCase } from "./labCase.ts";
import {
    classificationLabel,
    classificationContext,
    classificationSourceLabel,
    classificationSourceHref,
} from "./classificationDisplay.ts";
import { ClassificationEvidence } from "./ClassificationEvidence.tsx";
import { OpportunityTools } from "./OpportunityTools.tsx";
import { researchName, researchText } from "../research/researchDisplay.ts";
import {
    opportunitySelection,
    resolveOpportunitySelection,
    selectedDisplayedSecurityId,
    timelineRow,
    type OpportunitySelection,
} from "./selection.ts";
import {
    pct,
    seriesColor,
    share,
    stateLabel,
    reasonText,
} from "./evidenceFormat.ts";
import "./OpportunityPage.css";

const GROUP = {
    strategy: "研究策略",
    "tw-etf": "台股 ETF",
    "us-etf": "美股 ETF",
};
const DEMO = createOpportunityFixture();
function previewDateIndex(bundle: OpportunityBundle): number {
    const i = bundle.dates.findIndex((d) => d >= "2021-04-29");
    return i >= 0 ? i : Math.floor(bundle.dates.length * 0.55);
}
function stored<T>(key: string, fallback: T): T {
    try {
        return JSON.parse(localStorage.getItem(key) ?? "null") ?? fallback;
    } catch {
        return fallback;
    }
}
export function OpportunityPage({ active }: { active: boolean }) {
    const [historical, setHistorical] = useState<OpportunityBundle | null>(
        null,
    );
    const [mode, setMode] = useState("historical"),
        [loading, setLoading] = useState(true),
        [loadError, setLoadError] = useState("");
    const [custom, setCustom] = useState<OpportunityBundle | null>(null);
    const [index, setIndex] = useState(500),
        [playing, setPlaying] = useState(false);
    const [selected, setSelected] = useState<OpportunitySelection | null>(null),
        [detail, setDetail] = useState<LabCase | null>(null);
    const [tab, setTab] = useState<"stocks" | "portfolios">("stocks"),
        [query, setQuery] = useState(""),
        [group, setGroup] = useState("all");
    const [compareMode, setCompareMode] = useState<"one" | "many">("one"),
        [selectedIds, setSelectedIds] = useState<string[]>([]);
    const [pinned, setPinned] = useState<string[]>(() => {
        const saved = stored<unknown>("opportunity.pins.v1", []);
        return Array.isArray(saved)
            ? saved.filter((v) => typeof v === "string")
            : [];
    });
    const [rankMetric, setRankMetric] = useState<"capital" | "overlap">(
        "capital",
    );
    const [settings, setSettings] = useState(false),
        [motionOff, setMotionOff] = useState(false),
        [showDots, setShowDots] = useState(false);
    const [systemReduced, setSystemReduced] = useState(
        () => matchMedia("(prefers-reduced-motion: reduce)").matches,
    );
    const [notice, setNotice] = useState(""),
        [showDirectory, setShowDirectory] = useState(false);
    const sideRef = useRef<HTMLElement>(null),
        sourceEpoch = useRef(0);
    const bundle =
        mode === "custom" && custom
            ? custom
            : mode === "historical" && historical
              ? historical
              : DEMO;
    const date = bundle.dates[Math.min(index, bundle.dates.length - 1)];
    const view = useMemo(() => buildMarketView(bundle, date), [bundle, date]);
    const availableIds = selectedIds
        .filter((id) => bundle.portfolios.some((p) => p.id === id))
        .slice(0, compareMode === "one" ? 1 : 4);
    const compared = useMemo(
        () =>
            bundle.portfolios
                .filter((p) => selectedIds.includes(p.id))
                .sort(
                    (a, b) =>
                        selectedIds.indexOf(a.id) - selectedIds.indexOf(b.id),
                )
                .slice(0, compareMode === "one" ? 1 : 4)
                .map((p) => comparePortfolio(bundle, view, p)),
        [bundle, view, selectedIds, compareMode],
    );
    const portfolios = useMemo(
        () => compared.map((c) => c.portfolio),
        [compared],
    );
    const ranking = useMemo(
        () =>
            tab === "portfolios"
                ? bundle.portfolios
                      .map((p) => comparePortfolio(bundle, view, p))
                      .sort(
                          (a, b) =>
                              (rankMetric === "capital"
                                  ? (b.capital.opportunityWeight ?? -1)
                                  : (b.averagePositiveMoveShare ?? -1)) -
                              (rankMetric === "capital"
                                  ? (a.capital.opportunityWeight ?? -1)
                                  : (a.averagePositiveMoveShare ?? -1)),
                      )
                : [],
        [bundle, view, tab, rankMetric],
    );
    const selectedRow = resolveOpportunitySelection(view.rows, selected);
    const retired = view.ended.filter(
        (r) =>
            r.wave.endConfirmedAt &&
            Date.parse(date) - Date.parse(r.wave.endConfirmedAt) <
                45 * 86400000,
    );
    const stockRows = [...view.active]
        .sort((a, b) => (b.gain ?? -1) - (a.gain ?? -1))
        .concat(retired)
        .slice(0, 24);
    const reducedMotion = motionOff || systemReduced;
    const scopeLabel =
        bundle.catalogCoverage === "case-slice"
            ? "收錄範例中的飆股"
            : "收錄股票中的飆股";
    const isSynthetic = bundle.kind === "synthetic";
    const isCaseSlice = bundle.catalogCoverage === "case-slice";
    const scopeDescription = isSynthetic
        ? "示範資料使用虛構股票與持股，僅供體驗操作。"
        : isCaseSlice
          ? `目前只收錄 ${bundle.securities.length} 檔範例股票，不是全市場。`
          : `初步辨識，規則未定；範圍限本份資料收錄的 ${bundle.securities.length} 檔股票。`;
    const scopeCountLabel = isSynthetic
        ? `在 ${bundle.securities.length} 檔虛構股票中`
        : isCaseSlice
          ? `在 ${bundle.securities.length} 檔範例中`
          : `在收錄的 ${bundle.securities.length} 檔中`;
    const hasPhases = view.active.some((row) => row.phase !== null);

    useEffect(() => {
        const controller = new AbortController();
        const requestEpoch = sourceEpoch.current;
        readArtifact("opportunity-explorer", controller.signal)
            .then((value) => {
                const data = validateBundle(value);
                setHistorical(data);
                if (requestEpoch === sourceEpoch.current)
                    setIndex(previewDateIndex(data));
            })
            .catch((e) => {
                if (e.name !== "AbortError") {
                    setLoadError(e.message);
                    if (requestEpoch === sourceEpoch.current) {
                        setMode("demo");
                        setIndex(500);
                    }
                }
            })
            .finally(() => {
                if (!controller.signal.aborted) setLoading(false);
            });
        return () => controller.abort();
    }, []);
    useEffect(() => {
        const m = matchMedia("(prefers-reduced-motion: reduce)");
        const cb = () => setSystemReduced(m.matches);
        m.addEventListener("change", cb);
        return () => m.removeEventListener("change", cb);
    }, []);
    useEffect(() => {
        try {
            localStorage.setItem("opportunity.pins.v1", JSON.stringify(pinned));
        } catch {
            /* Pins remain usable in memory. */
        }
    }, [pinned]);
    useEffect(() => {
        if (!playing || !active || detail) return;
        const t = setInterval(
            () =>
                setIndex((i) => {
                    if (i >= bundle.dates.length - 1) {
                        setPlaying(false);
                        return i;
                    }
                    return Math.min(bundle.dates.length - 1, i + 3);
                }),
            240,
        );
        return () => clearInterval(t);
    }, [playing, active, bundle, detail]);
    useEffect(() => {
        if (!active) setPlaying(false);
    }, [active]);

    const changeSource = (next: string) => {
        sourceEpoch.current++;
        setMode(next);
        setPlaying(false);
        setSelected(null);
        setSelectedIds([]);
        setNotice("");
        setIndex(
            next === "demo"
                ? 500
                : previewDateIndex(next === "custom" ? custom! : historical!),
        );
    };
    const changeDate = (d: string) => {
        const i = bundle.dates.indexOf(d);
        if (i >= 0) {
            setIndex(i);
            setPlaying(false);
        }
    };
    const chooseDateValue = (value: string) => {
        if (value >= bundle.dates[0] && value <= bundle.dates.at(-1)!) {
            const i = bundle.dates.findIndex((d) => d >= value);
            if (i >= 0) changeDate(bundle.dates[i]);
        }
    };
    const selectRow = (row: OpportunityRow) => {
        setSelected(opportunitySelection(row));
        setTab("stocks");
        if (matchMedia("(max-width: 900px)").matches)
            sideRef.current?.scrollIntoView({
                behavior: reducedMotion ? "instant" : "smooth",
                block: "start",
            });
    };
    const choosePortfolio = (id: string) => {
        setNotice("");
        setSelectedIds((old) => {
            if (old.includes(id)) return old.filter((x) => x !== id);
            if (compareMode === "one") return [id];
            if (old.length >= 4) {
                setNotice("一次最多比較 4 個，請先取消一個。");
                return old;
            }
            return [...old, id];
        });
    };
    const pin = (id: string) =>
        setPinned((old) =>
            old.includes(id) ? old.filter((x) => x !== id) : [...old, id],
        );
    const evidence = () => ({
        schema: "opportunity-view-review.v1",
        bundleId: bundle.id,
        kind: bundle.kind,
        date,
        ruleVersion: bundle.ruleVersion,
        selectionPolicy: bundle.selectionPolicy,
        classificationVersion: bundle.classificationVersion,
        priceBasis: bundle.priceBasis,
        metricVersion: POSITIVE_MOVE_SHARE_VERSION,
        active: view.active.map((r) => ({
            securityId: r.security.id,
            waveId: r.wave.id,
            start: r.wave.start,
            launch: r.wave.launch,
            observation: date,
            gain: r.gain,
            peakDate: r.wave.peakDate,
            peakGain: r.peakGain,
            industry: r.industry,
            reason: r.reason,
        })),
        comparisons: compared,
        sources: bundle.sources,
        limitations: bundle.limitations,
    });

    if (detail)
        return (
            <WaveLabPage
                externalCase={detail}
                initialDate={date}
                onBack={() => setDetail(null)}
            />
        );
    return (
        <div
            className="op-page"
            data-reduced-motion={reducedMotion ? "true" : "false"}
        >
            <section className="op-hero">
                <div>
                    <h1>飆股地圖</h1>
                    <p>選一個日期，看收錄股票的上漲期間、產業與累積漲幅。</p>
                    <p
                        className={`op-scope-note ${isSynthetic ? "synthetic" : ""}`}
                    >
                        {scopeDescription}
                    </p>
                </div>
                <div className="op-date-heading">
                    <time>{date}</time>
                    <p>
                        {scopeCountLabel}，這天有 <b>{view.active.length}</b>{" "}
                        檔正在大漲 ·{" "}
                        <b>
                            {
                                view.industries.filter((g) =>
                                    g.rows.some(
                                        (row) =>
                                            row.industry.basis ===
                                                "historical" ||
                                            row.industry.basis ===
                                                "document-period",
                                    ),
                                ).length
                            }
                        </b>{" "}
                        個產業／業務族群
                    </p>
                    {view.unlaunched.length > 0 && (
                        <button
                            className="op-text-button"
                            onClick={() => setShowDirectory((v) => !v)}
                        >
                            另有 {view.unlaunched.length}{" "}
                            檔尚未辨認到明確起漲日期，查看名單 ↗
                        </button>
                    )}
                    {view.unknown.length > 0 && (
                        <button
                            className="op-text-button"
                            onClick={() => setShowDirectory(true)}
                        >
                            {view.unknown.length} 檔資料不完整，查看原因 ↗
                        </button>
                    )}
                </div>
            </section>
            {loading && (
                <p className="op-notice" role="status">
                    正在讀取真實範例；下方暫時顯示虛構股票。
                </p>
            )}
            {loadError && mode === "historical" && (
                <p className="op-notice">
                    真實資料目前無法開啟。下方為虛構股票與持股的示範資料。
                </p>
            )}
            <section
                className="op-card op-controls"
                aria-label="選擇日期與對照持股"
            >
                <div className="op-time-control">
                    <button
                        className="op-play"
                        aria-label={playing ? "暫停時間播放" : "播放時間變化"}
                        onClick={() => {
                            if (index >= bundle.dates.length - 1) setIndex(0);
                            setPlaying((v) => !v);
                        }}
                    >
                        {playing ? "Ⅱ" : "▶"}
                    </button>
                    <div className="op-slider-box">
                        <div className="op-slider-label">
                            <strong>拖動選日期</strong>
                            <span>
                                {bundle.dates[0]} — {bundle.dates.at(-1)}
                            </span>
                        </div>
                        <input
                            type="range"
                            aria-label="市場觀察日期"
                            min="0"
                            max={bundle.dates.length - 1}
                            value={Math.min(index, bundle.dates.length - 1)}
                            onChange={(e) => {
                                setPlaying(false);
                                setIndex(Number(e.target.value));
                            }}
                        />
                        <div className="op-date-ticks">
                            {[0, 0.25, 0.5, 0.75, 1].map((t) => (
                                <span key={t}>
                                    {bundle.dates[
                                        Math.round(
                                            t * (bundle.dates.length - 1),
                                        )
                                    ].slice(0, 7)}
                                </span>
                            ))}
                        </div>
                    </div>
                    <input
                        aria-label="指定觀察日期"
                        type="date"
                        min={bundle.dates[0]}
                        max={bundle.dates.at(-1)}
                        value={date}
                        onInput={(e) => chooseDateValue(e.currentTarget.value)}
                        onChange={(e) => chooseDateValue(e.currentTarget.value)}
                        onBlur={(e) => chooseDateValue(e.currentTarget.value)}
                    />
                    <button
                        className="op-settings-button"
                        aria-expanded={settings}
                        onClick={() => setSettings((v) => !v)}
                    >
                        設定 ⚙
                    </button>
                </div>
                <div className="op-pins">
                    <span>比較策略或 ETF</span>
                    <button
                        aria-pressed={!availableIds.length}
                        onClick={() => setSelectedIds([])}
                    >
                        不比較
                    </button>
                    {pinned
                        .filter((id) =>
                            bundle.portfolios.some((p) => p.id === id),
                        )
                        .map((id) => (
                            <button
                                key={id}
                                aria-pressed={availableIds.includes(id)}
                                onClick={() => choosePortfolio(id)}
                            >
                                ★{" "}
                                {researchName(
                                    bundle.portfolios.find((p) => p.id === id)!
                                        .name,
                                )}
                            </button>
                        ))}
                    <button
                        className="op-text-button"
                        onClick={() => {
                            setTab("portfolios");
                            sideRef.current?.scrollIntoView({
                                behavior: reducedMotion ? "instant" : "smooth",
                                block: "nearest",
                            });
                        }}
                    >
                        看全部 {bundle.portfolios.length} 個策略／ETF →
                    </button>
                </div>
                {settings && (
                    <div className="op-settings">
                        <label>
                            資料來源
                            <select
                                value={mode}
                                onChange={(e) => changeSource(e.target.value)}
                            >
                                <option value="demo">
                                    示範資料（虛構股票）
                                </option>
                                <option
                                    value="historical"
                                    disabled={!historical}
                                >
                                    真實範例（
                                    {historical?.securities.length ?? 8} 檔）
                                </option>
                                {custom && (
                                    <option value="custom">
                                        {custom.label}
                                    </option>
                                )}
                            </select>
                        </label>
                        <label>
                            <input
                                type="checkbox"
                                checked={motionOff}
                                onChange={(e) => setMotionOff(e.target.checked)}
                            />
                            減少畫面動態
                        </label>
                        <label>
                            <input
                                type="checkbox"
                                checked={showDots}
                                onChange={(e) => setShowDots(e.target.checked)}
                            />
                            在股票上顯示比較色點
                        </label>
                        <p>圓越大，代表從起漲到這一天累計漲得越多。</p>
                    </div>
                )}
            </section>
            {notice && (
                <p className="op-notice" role="status">
                    {notice}
                </p>
            )}
            <CapitalCards comparisons={compared} scopeLabel={scopeLabel} />
            <div className="op-main-grid">
                <section className="op-card op-map-card">
                    <div className="op-section-title">
                        <div>
                            <h2>當天的飆股</h2>
                        </div>
                        {hasPhases && (
                            <div className="op-inline-legend">
                                <span>
                                    <i className="rise" />
                                    持續上漲
                                </span>
                                <span>
                                    <i className="rest" />
                                    漲多休息
                                </span>
                                <span>
                                    <i className="retreat" />
                                    從高點拉回
                                </span>
                            </div>
                        )}
                    </div>
                    <OpportunityMap
                        key={bundle.id}
                        view={view}
                        comparisons={compared}
                        selectedSecurityId={selectedDisplayedSecurityId(
                            view.active,
                            selected,
                        )}
                        selectedWaveId={selected?.waveId ?? null}
                        onSelect={(id) => {
                            const row = view.active.find(
                                (r) => r.security.id === id,
                            );
                            if (row) selectRow(row);
                        }}
                        reducedMotion={reducedMotion}
                        showComparisonDots={showDots}
                    />
                    <div className="op-map-caption">
                        <span>
                            每個圓是一檔股票，點一下看日期與走勢。已確認當年分類的股票按產業或業務分組，其餘個別呈現。
                        </span>
                        <span>
                            族群漲幅取其中一檔從起漲至這天的最高累積漲幅。
                        </span>
                    </div>
                    {compared.length > 0 && (
                        <p className="op-footnote">
                            顏色越深，持股日期與上漲重疊越多；斜線表示無法計算。這不是實際報酬。
                        </p>
                    )}
                    {view.active.length === 0 && (
                        <p className="op-empty">
                            {scopeCountLabel}
                            ，這一天沒有符合條件的股票。可換日期，或查看下方上漲期間。
                        </p>
                    )}
                </section>
                <aside className="op-card op-side" ref={sideRef}>
                    <div
                        className="op-tabs"
                        role="tablist"
                        aria-label="股票與策略比較"
                    >
                        <button
                            role="tab"
                            aria-selected={tab === "stocks"}
                            onClick={() => setTab("stocks")}
                        >
                            正在大漲的股票
                        </button>
                        <button
                            role="tab"
                            aria-selected={tab === "portfolios"}
                            onClick={() => setTab("portfolios")}
                        >
                            策略／ETF 比較
                        </button>
                    </div>
                    {tab === "stocks" ? (
                        <>
                            {selected && !selectedRow && (
                                <p className="op-empty" role="status">
                                    這一天未列出所選波段，請移回原日期或在案例名單重新選擇。
                                </p>
                            )}
                            {selectedRow && (
                                <StockCard
                                    row={selectedRow}
                                    bundle={bundle}
                                    date={date}
                                    comparisons={compared}
                                    onClose={() => setSelected(null)}
                                    onDetails={() =>
                                        setDetail(
                                            toLabCase(selectedRow, bundle),
                                        )
                                    }
                                />
                            )}
                            {compared.length === 1 && (
                                <div className="op-side-summary">
                                    <small>
                                        {researchName(
                                            compared[0].portfolio.name,
                                        )}
                                    </small>
                                    <b>
                                        {share(
                                            compared[0]
                                                .averagePositiveMoveShare,
                                        )}
                                    </b>
                                    <p>
                                        平均持股日上漲占比 ·{" "}
                                        {compared[0].knownCount} 檔可計算
                                    </p>
                                    <small>
                                        當天持有其中 {compared[0].heldCount}{" "}
                                        檔。
                                        {compared[0].stocks.some(
                                            (s) => s.held === "unknown",
                                        ) &&
                                            `${compared[0].stocks.filter((s) => s.held === "unknown").length} 檔當天持股不明。`}
                                        {compared[0].unknownCount > 0 &&
                                            `${compared[0].unknownCount} 檔無法計算。`}
                                        不是實際報酬。
                                    </small>
                                </div>
                            )}
                            <div
                                className="op-stock-list"
                                style={{
                                    height: Math.max(
                                        100,
                                        stockRows.length * 65,
                                    ),
                                }}
                            >
                                {stockRows.map((row, i) => (
                                    <button
                                        key={row.wave.id}
                                        className={`op-stock-row ${row.state === "ended" ? "ended" : ""} ${selectedRow === row ? "selected" : ""}`}
                                        style={{
                                            transform: `translateY(${i * 65}px)`,
                                        }}
                                        onClick={() => selectRow(row)}
                                    >
                                        <span className="op-stock-name">
                                            <strong>{row.security.name}</strong>
                                            <small
                                                title={
                                                    classificationContext(
                                                        row,
                                                    ) || undefined
                                                }
                                            >
                                                {classificationLabel(row)}
                                                {stateLabel(row, date) &&
                                                    ` · ${stateLabel(row, date)}`}
                                            </small>
                                        </span>
                                        <Sparkline
                                            security={row.security}
                                            wave={row.wave}
                                            date={
                                                row.state === "ended"
                                                    ? row.wave.endConfirmedAt!
                                                    : date
                                            }
                                            portfolios={portfolios}
                                        />
                                        <span className="op-stock-value">
                                            {compared.length === 0 ? (
                                                <>
                                                    <b>
                                                        {pct(
                                                            row.state ===
                                                                "ended"
                                                                ? row.endGain
                                                                : row.gain,
                                                        )}
                                                    </b>
                                                    <small>
                                                        {row.state === "ended"
                                                            ? "結束時仍有"
                                                            : "起漲至這天"}
                                                    </small>
                                                </>
                                            ) : compared.length === 1 ? (
                                                <>
                                                    <b>
                                                        {share(
                                                            compared[0].stocks.find(
                                                                (s) =>
                                                                    s.securityId ===
                                                                    row.security
                                                                        .id,
                                                            )
                                                                ?.positiveMoveShare,
                                                        )}
                                                    </b>
                                                    <small>
                                                        持股日上漲占比
                                                    </small>
                                                </>
                                            ) : (
                                                compared.map((c, j) => {
                                                    const value = c.stocks.find(
                                                        (s) =>
                                                            s.securityId ===
                                                            row.security.id,
                                                    )?.positiveMoveShare;
                                                    return (
                                                        <span
                                                            key={c.portfolio.id}
                                                            className={`op-small-meter ${value == null ? "op-hatch" : ""}`}
                                                            title={`${c.portfolio.name}：${share(value)}`}
                                                        >
                                                            <i
                                                                style={{
                                                                    width: `${(value ?? 0) * 100}%`,
                                                                    background:
                                                                        seriesColor(
                                                                            j,
                                                                        ),
                                                                }}
                                                            />
                                                        </span>
                                                    );
                                                })
                                            )}
                                        </span>
                                    </button>
                                ))}
                            </div>
                            {!stockRows.length && (
                                <p className="op-empty">
                                    這一天沒有可列出的股票。
                                </p>
                            )}
                            <p className="op-footnote">
                                漲勢結束不代表股價大跌，只是這段大漲告一段落。
                            </p>
                        </>
                    ) : (
                        <>
                            <div className="op-segmented">
                                <button
                                    aria-pressed={compareMode === "one"}
                                    onClick={() => {
                                        setCompareMode("one");
                                        setSelectedIds((ids) =>
                                            ids.slice(0, 1),
                                        );
                                    }}
                                >
                                    一次看一個
                                </button>
                                <button
                                    aria-pressed={compareMode === "many"}
                                    onClick={() => setCompareMode("many")}
                                >
                                    一起比較 · 最多 4 個
                                </button>
                            </div>
                            <label className="op-rank-label">
                                排序
                                <select
                                    value={rankMetric}
                                    onChange={(e) =>
                                        setRankMetric(
                                            e.target.value as
                                                "capital" | "overlap",
                                        )
                                    }
                                >
                                    <option value="capital">
                                        資金放在飆股的比例
                                    </option>
                                    <option value="overlap">
                                        持股日上漲占比
                                    </option>
                                </select>
                            </label>
                            <input
                                className="op-search"
                                aria-label="搜尋策略或 ETF"
                                placeholder="搜尋策略名稱、ETF 或研究任務"
                                value={query}
                                onChange={(e) => setQuery(e.target.value)}
                            />
                            <div className="op-filter-chips">
                                {["all", "strategy", "tw-etf", "us-etf"].map(
                                    (g) => (
                                        <button
                                            key={g}
                                            aria-pressed={group === g}
                                            onClick={() => setGroup(g)}
                                        >
                                            {g === "all"
                                                ? "全部"
                                                : GROUP[
                                                      g as keyof typeof GROUP
                                                  ]}
                                        </button>
                                    ),
                                )}
                            </div>
                            <div className="op-portfolio-list">
                                {ranking
                                    .filter(
                                        (c) =>
                                            (group === "all" ||
                                                c.portfolio.kind === group) &&
                                            `${researchName(c.portfolio.name)} ${c.portfolio.name} ${c.portfolio.method?.taskId ?? ""}`
                                                .toLowerCase()
                                                .includes(query.toLowerCase()),
                                    )
                                    .map((c, i) => {
                                        const value =
                                            rankMetric === "capital"
                                                ? c.capital.opportunityWeight
                                                : c.averagePositiveMoveShare;
                                        return (
                                            <div
                                                className={`op-portfolio-row ${availableIds.includes(c.portfolio.id) ? "selected" : ""}`}
                                                key={c.portfolio.id}
                                            >
                                                <button
                                                    onClick={() =>
                                                        choosePortfolio(
                                                            c.portfolio.id,
                                                        )
                                                    }
                                                    aria-pressed={availableIds.includes(
                                                        c.portfolio.id,
                                                    )}
                                                >
                                                    <span className="op-ranking-number">
                                                        {value == null
                                                            ? "—"
                                                            : i + 1}
                                                    </span>
                                                    <span>
                                                        <strong>
                                                            {researchName(
                                                                c.portfolio
                                                                    .name,
                                                            )}
                                                        </strong>
                                                        <small>
                                                            {
                                                                GROUP[
                                                                    c.portfolio
                                                                        .kind
                                                                ]
                                                            }{" "}
                                                            · 當天持有其中{" "}
                                                            {c.heldCount} 檔
                                                            {c.stocks.some(
                                                                (s) =>
                                                                    s.held ===
                                                                    "unknown",
                                                            ) &&
                                                                ` · ${c.stocks.filter((s) => s.held === "unknown").length} 檔當天持股不明`}
                                                        </small>
                                                    </span>
                                                    <span>
                                                        <b>{share(value)}</b>
                                                        <i
                                                            className={`op-small-meter ${value == null ? "op-hatch" : ""}`}
                                                        >
                                                            <i
                                                                style={{
                                                                    width: `${(value ?? 0) * 100}%`,
                                                                }}
                                                            />
                                                        </i>
                                                    </span>
                                                </button>
                                                <button
                                                    className="op-pin-button"
                                                    aria-label={`${pinned.includes(c.portfolio.id) ? "取消釘選" : "釘選"}${c.portfolio.name}`}
                                                    aria-pressed={pinned.includes(
                                                        c.portfolio.id,
                                                    )}
                                                    onClick={() =>
                                                        pin(c.portfolio.id)
                                                    }
                                                >
                                                    {pinned.includes(
                                                        c.portfolio.id,
                                                    )
                                                        ? "★"
                                                        : "☆"}
                                                </button>
                                            </div>
                                        );
                                    })}
                            </div>
                            <p className="op-footnote">
                                只比較收錄股票截至這一天的資料。無法計算的股票不算進平均；資料越少，排名越不完整。這不是績效排名。
                            </p>
                        </>
                    )}
                </aside>
            </div>
            {compared.some((c) => c.portfolio.method) && (
                <section className="op-card op-methods">
                    <div className="op-section-title">
                        <h2>研究是怎麼做的？</h2>
                        <p>未達標的結果與方法也保留</p>
                    </div>
                    {compared
                        .filter((c) => c.portfolio.method)
                        .map((c) => (
                            <MethodCard
                                key={c.portfolio.id}
                                portfolio={c.portfolio}
                            />
                        ))}
                </section>
            )}
            <OpportunityTimeline
                bundle={bundle}
                view={view}
                selectedPortfolios={portfolios}
                selectedSecurityId={selectedDisplayedSecurityId(
                    view.rows,
                    selected,
                )}
                onSelect={(id, targetDate) => {
                    const row = timelineRow(bundle, id, targetDate);
                    changeDate(targetDate);
                    if (row) {
                        setNotice("");
                        selectRow(row);
                    } else {
                        setSelected(null);
                        setNotice(
                            "這一天尚未指定這檔股票的代表波段，可從案例名單選擇要檢視的行情。",
                        );
                    }
                }}
            />
            <details
                className="op-card op-directory"
                open={showDirectory}
                onToggle={(e) => setShowDirectory(e.currentTarget.open)}
            >
                <summary>
                    收錄名單與未畫入的股票（{bundle.securities.length} 檔）
                </summary>
                <div className="op-table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th>股票</th>
                                <th>狀態</th>
                                <th>起漲日期</th>
                                <th>開始大漲</th>
                                <th>漲幅</th>
                                <th>資料截至</th>
                            </tr>
                        </thead>
                        <tbody>
                            {view.rows.map((r) => (
                                <tr key={r.wave.id}>
                                    <td>
                                        <button
                                            className="op-text-button"
                                            aria-pressed={selectedRow === r}
                                            onClick={() => selectRow(r)}
                                        >
                                            {r.security.code} {r.security.name}
                                        </button>
                                    </td>
                                    <td>
                                        {(r.reason
                                            ? reasonText(r.reason)
                                            : null) ??
                                            (r.state === "outside"
                                                ? "不在這波期間"
                                                : stateLabel(r, date) ||
                                                  "在這段上漲期間")}
                                    </td>
                                    <td>{r.wave.start}</td>
                                    <td>
                                        {r.wave.launch?.date ??
                                            "未辨認到明確日期"}
                                    </td>
                                    <td>
                                        {pct(
                                            r.state === "ended"
                                                ? r.endGain
                                                : r.gain,
                                        )}
                                        <small className="op-value-date">
                                            {r.state === "ended"
                                                ? `結束日 ${r.wave.endConfirmedAt}`
                                                : `截至 ${date}`}
                                        </small>
                                    </td>
                                    <td>{r.wave.observedThrough}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </details>
            <details className="op-card op-provenance-details">
                <summary>資料說明</summary>
                <ul>
                    <li>{scopeDescription}</li>
                    <li>
                        資料期間：{bundle.dates[0]}～{bundle.dates.at(-1)}
                        ；資料版本截至 {bundle.asOf}。
                    </li>
                    <li>{priceExplanation(bundle.priceBasis)}</li>
                    <li>
                        波段起點與最高點是事後回看；部分當年產業分類仍待確認，目前不使用歷史市值調整圓的大小。
                    </li>
                    <li>
                        持股日上漲占比：看上漲的日子中，收盤持有這檔股票時遇到的漲幅占多少；沒有計入買賣價格、部位大小或成本，不是實際報酬。平均只納入可計算股票，每檔比重相同。
                    </li>
                </ul>
                <p>
                    圓越大，表示從起漲到選定日期的累積漲幅越多；漲幅兩倍，直徑兩倍。
                </p>
                {bundle.sources
                    .filter((s) => classificationSourceHref(s))
                    .map((s) => (
                        <div key={s.id}>
                            <strong>{classificationSourceLabel(s)}</strong>
                            {s.url && /^https?:\/\//.test(s.url) && (
                                <a
                                    href={s.url}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    {" "}
                                    查看來源 ↗
                                </a>
                            )}
                        </div>
                    ))}
            </details>
            <OpportunityTools
                bundle={bundle}
                date={date}
                evidence={evidence}
                loadError={loadError}
                onNotice={setNotice}
                onImport={(next) => {
                    sourceEpoch.current++;
                    setLoadError("");
                    setLoading(false);
                    setCustom(next);
                    setMode("custom");
                    setSelected(null);
                    setSelectedIds([]);
                    setPlaying(false);
                    setIndex(Math.floor(next.dates.length * 0.55));
                }}
            />
        </div>
    );
}

function StockCard({
    row,
    bundle,
    date,
    comparisons,
    onClose,
    onDetails,
}: {
    row: OpportunityRow;
    bundle: OpportunityBundle;
    date: string;
    comparisons: PortfolioComparison[];
    onClose: () => void;
    onDetails: () => void;
}) {
    const valueDate = row.state === "ended" ? row.wave.endConfirmedAt! : date;
    const startQuote = row.security.prices.find(
        (p) => p.date === row.wave.start,
    );
    const startClose =
        startQuote && startQuote.flags.length === 0 ? startQuote.close : null;
    const valueClose =
        row.state === "ended" && row.endGain !== null
            ? row.security.prices.find((p) => p.date === valueDate)?.close
            : row.price;
    return (
        <section className="op-stock-card">
            <div className="op-stock-card-head">
                <div>
                    <span className="op-kicker">
                        {row.security.code} · {classificationLabel(row)}
                    </span>
                    <h3>{row.security.name}</h3>
                </div>
                <button
                    className="op-close"
                    onClick={onClose}
                    aria-label="關閉股票明細"
                >
                    ×
                </button>
            </div>
            {(stateLabel(row, date) || row.reason) && (
                <p className="op-status">
                    {stateLabel(row, date)}
                    {row.reason && ` · ${reasonText(row.reason)}`}
                </p>
            )}
            <strong className="op-stock-big">
                {pct(row.state === "ended" ? row.endGain : row.gain)}
            </strong>
            <small>
                {row.wave.start} → {valueDate} ·{" "}
                {row.state === "ended" ? "結束時仍保有的漲幅" : "起漲至這天"}
            </small>
            <Sparkline
                large
                security={row.security}
                wave={row.wave}
                date={valueDate}
                portfolios={comparisons.map((c) => c.portfolio)}
            />
            <dl>
                <dt>起漲日期</dt>
                <dd>
                    {row.wave.start}
                    {row.wave.leftCensored ? "（起點可能更早）" : ""}
                </dd>
                <dt>開始大漲</dt>
                <dd>{row.wave.launch?.date ?? "沒有明確日期"}</dd>
                {row.wave.launch &&
                    row.wave.launch.rangeFrom !==
                        row.wave.launch.rangeUntil && (
                        <>
                            <dt>不同尺度估計</dt>
                            <dd>
                                {row.wave.launch.rangeFrom} ～{" "}
                                {row.wave.launch.rangeUntil}
                                {(row.wave.launch.rangeFrom < row.wave.start ||
                                    row.wave.launch.rangeUntil >
                                        row.wave.observedThrough) && (
                                    <small>
                                        各尺度的日期落在這波之外；保留供比較，漲幅仍以選定日期起算。
                                    </small>
                                )}
                            </dd>
                        </>
                    )}
                {row.wave.launch && (
                    <>
                        <dt>開始大漲至這天</dt>
                        <dd>
                            {pct(row.launchGain)} · {date}
                        </dd>
                    </>
                )}
                <dt>
                    {row.wave.rightCensored
                        ? "資料截至目前的最高漲幅"
                        : "這波後來最高"}
                </dt>
                <dd>
                    {pct(row.peakGain)} · {row.wave.peakDate}
                </dd>
                <dt>漲勢結束</dt>
                <dd>
                    {row.wave.endConfirmedAt ??
                        `未確認 · 資料至 ${row.wave.observedThrough}`}
                </dd>
                <dt>起漲／選定日期股價</dt>
                <dd>
                    {startClose?.toFixed(2) ?? "未知"} →{" "}
                    {valueClose?.toFixed(2) ?? "未知"} · {valueDate}
                </dd>
                <dt>價格如何計算</dt>
                <dd>{priceExplanation(bundle.priceBasis)}</dd>
            </dl>
            <ClassificationEvidence row={row} sources={bundle.sources} />
            <p className="op-footnote">
                虛線圈表示這波後來的最高漲幅，當時還不知道。
            </p>
            {comparisons.map((c, i) => {
                const s = c.stocks.find(
                    (v) => v.securityId === row.security.id,
                );
                return (
                    <p className="op-stock-comparison" key={c.portfolio.id}>
                        <span
                            className="op-series-dot"
                            style={{ background: seriesColor(i) }}
                        />
                        {researchName(c.portfolio.name)}
                        <strong>{share(s?.positiveMoveShare)}</strong>
                        <small>
                            持股日上漲占比 ·{" "}
                            {s?.held === "held"
                                ? "當天有持股紀錄"
                                : s?.held === "not-held"
                                  ? "當天未持有"
                                  : "當天持股未知"}
                        </small>
                    </p>
                );
            })}
            <button
                className="op-detail-button"
                onClick={onDetails}
                disabled={row.security.prices.length === 0}
            >
                {row.security.prices.length === 0
                    ? "缺少價格資料，無法查看走勢細節"
                    : "看這檔的走勢細節 →"}
            </button>
        </section>
    );
}

function MethodCard({ portfolio }: { portfolio: OpportunityPortfolio }) {
    const m = portfolio.method!;
    return (
        <details className="op-method-card">
            <summary>
                {researchName(portfolio.name)}{" "}
                <span>
                    {
                        {
                            exploratory: "研究中，尚未採用",
                            failed: "已淘汰",
                            incomplete: "研究未完成",
                            accepted: "已接受；仍需查看條件",
                        }[m.status]
                    }
                </span>
            </summary>
            <p>{researchText(m.conclusion)}</p>
            <ol>
                {m.rules.map((r, i) => (
                    <li key={i}>{researchText(r)}</li>
                ))}
            </ol>
            <details>
                <summary>完整研究紀錄</summary>
                <dl>
                    {Object.entries(m.parameters).map(([key, value]) => (
                        <div key={key}>
                            <dt>{key}</dt>
                            <dd>{String(value)}</dd>
                        </div>
                    ))}
                </dl>
                <ul>
                    {m.limitations.map((l, i) => (
                        <li key={i}>{researchText(l)}</li>
                    ))}
                </ul>
                <p>
                    任務 {m.taskId} · 版本 {m.ruleVersion}
                </p>
                {m.missionPath && <code>{m.missionPath}</code>}
                {m.reportPath && <code>{m.reportPath}</code>}
            </details>
        </details>
    );
}
