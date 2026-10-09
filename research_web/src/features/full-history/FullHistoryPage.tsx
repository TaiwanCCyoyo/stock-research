import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { OpportunityMap } from "../../visualizations/opportunity/OpportunityMap";
import { priceExplanation } from "../../components/priceExplanation.ts";
import type { PortfolioComparison } from "../../domain/opportunities/types.ts";
import {
    appears,
    dateIndex,
    percent,
    phaseLabel,
    recentEnded,
    toMapView,
    type HistoryDisplayMode,
} from "./model.ts";
import { useHistory } from "./useHistory.ts";
import { readMarketLink } from "./navigation.ts";
import { HistoryChartDetail } from "./HistoryChartDetail";
import { HistoryRanking } from "./HistoryRanking";
import { frameStatusMessage, historyFrameDisplay } from "./frameDisplay.ts";
import { HistoryTimeline } from "./HistoryTimeline";
import { HistoryMethodOptions } from "./HistoryMethodOptions";
import { HistoryComparisons } from "./HistoryComparisons";
import {
    growthBasisLabel,
    growthDurationLabel,
    growthUnknownExplanation,
} from "./growthDisplay.ts";
import "./FullHistoryPage.css";

export function FullHistoryPage({ active }: { active: boolean }) {
    const history = useHistory(active);
    const {
        metadata,
        frame,
        directory,
        desiredDate,
        selectedId,
        setSelectedId,
    } = history;
    const [dateDraft, setDateDraft] = useState("");
    const [mode, setMode] = useState<HistoryDisplayMode>("launched");
    const [thresholdPct, setThresholdPct] = useState(100);
    const [query, setQuery] = useState("");
    const [showComparisons, setShowComparisons] = useState(false);
    const [comparisons, setComparisons] = useState<PortfolioComparison[]>([]);
    const detailElement = useRef<HTMLDivElement>(null);
    const appliedLink = useRef<string | null>(null);
    useEffect(() => {
        if (!active) {
            appliedLink.current = null;
            return;
        }
        if (!metadata) return;
        const apply = () => {
            const link = readMarketLink(location.hash);
            if (!link) return;
            const key = `${metadata.catalogId}:${location.hash}`;
            if (appliedLink.current === key) return;
            appliedLink.current = key;
            if (link.date) history.goToDate(link.date);
            if (link.code) setSelectedId(`TW:${link.code}`);
            if (link.thresholdPct !== null) setThresholdPct(link.thresholdPct);
            if (link.mode !== null) setMode(link.mode);
        };
        apply();
        window.addEventListener("hashchange", apply);
        return () => window.removeEventListener("hashchange", apply);
    }, [active, metadata, history.goToDate, setSelectedId]);
    useEffect(() => setDateDraft(desiredDate), [desiredDate]);
    const ended = useMemo(
        () =>
            directory && frame
                ? recentEnded(directory.rows, frame, thresholdPct)
                : [],
        [directory, frame, thresholdPct],
    );
    const view = useMemo(
        () => (frame ? toMapView(frame, mode, ended, thresholdPct) : null),
        [frame, mode, ended, thresholdPct],
    );
    const displayed = useMemo(
        () =>
            frame?.rows.filter((row) =>
                appears(row, frame.date, mode, thresholdPct),
            ) ?? [],
        [frame, mode, thresholdPct],
    );
    const selected = frame?.rows.find((row) => row.securityId === selectedId);
    const noCandidate =
        frame?.rows.filter((row) => !row.launchCandidate).length ?? 0;
    const notYet =
        frame?.rows.filter(
            (row) =>
                row.launchCandidate && row.launchCandidate.date > frame.date,
        ).length ?? 0;
    const begunRows = (frame?.rows ?? []).filter(
        (row) =>
            mode === "catalog" ||
            (row.launchCandidate && row.launchCandidate.date <= frame!.date),
    );
    const unknownGrowth = begunRows.filter(
        (row) => row.growth?.sizingGainPct == null,
    ).length;
    const belowThreshold = begunRows.filter(
        (row) =>
            row.growth?.sizingGainPct != null &&
            row.growth.sizingGainPct < thresholdPct - 1e-9,
    ).length;
    const allRows = (frame?.rows ?? [])
        .filter((row) =>
            `${row.code} ${row.name} ${row.industry.label}`.includes(
                query.trim(),
            ),
        )
        .sort(
            (a, b) =>
                (b.growth?.sizingGainPct ?? -Infinity) -
                (a.growth?.sizingGainPct ?? -Infinity),
        );
    const reducedMotion = matchMedia(
        "(prefers-reduced-motion: reduce)",
    ).matches;
    const renderedDate = frame?.date ?? desiredDate;
    const frameDisplay = historyFrameDisplay({
        frame,
        desiredDate,
        loading: history.loading,
        error: history.error,
    });
    const datedComparisons = comparisons.filter(
        (comparison) => comparison.date === frame?.date,
    );
    const submitDate = (e: FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        const submitted = new FormData(e.currentTarget).get("observationDate");
        const requested = typeof submitted === "string" ? submitted : dateDraft;
        if (!metadata || !/^\d{4}-\d{2}-\d{2}$/.test(requested)) return;
        const actualDate = metadata.dates[dateIndex(metadata.dates, requested)];
        history.goToDate(actualDate);
        setDateDraft(actualDate);
        // Normalize the form even when the selected trading-day index is unchanged.
        const field = e.currentTarget.elements.namedItem("observationDate");
        if (field instanceof HTMLInputElement) field.value = actualDate;
    };
    return (
        <div className="fh-page">
            <header className="fh-hero">
                <div className="fh-hero-title">
                    <h1>飆股地圖</h1>
                    <p>
                        選一個日期，看哪些產業、哪些股票正在大漲，各漲了多少。
                    </p>
                </div>
                <div className="fh-hero-date">
                    <strong>{renderedDate || "正在準備"}</strong>
                    <span>
                        {view
                            ? `${displayed.length.toLocaleString()} 檔股票 · ${view.industries.length} 個產業`
                            : "2010 年起的歷史行情"}
                        {frame && belowThreshold > 0 && (
                            <small>另有 {belowThreshold} 檔未達門檻</small>
                        )}
                    </span>
                </div>
                <span className="fh-preview-badge">
                    初步辨識，規則未定 · 事後回看
                </span>
            </header>
            {history.metadataError && (
                <div className="fh-error" role="alert">
                    <strong>暫時無法讀取歷史資料</strong>
                    <p>
                        請確認網站與資料服務都已啟動，再重新讀取。若歷史快照驗證失敗，請檢查本機快照並重新啟動資料服務，再重新讀取。
                    </p>
                    <button onClick={history.retry}>重新讀取</button>
                    <a href="#market-preview">開啟八案例預覽</a>
                    <details>
                        <summary>錯誤資訊</summary>
                        {history.metadataError}
                    </details>
                </div>
            )}
            {!metadata && !history.metadataError && (
                <section className="fh-card fh-loading" role="status">
                    <span className="fh-loading-dot" />
                    <div>
                        <h2>正在準備歷史行情</h2>
                        <p>
                            首次啟動會核對保存資料，可能需要數分鐘；完成後即可拖曳日期。
                        </p>
                        {history.startup && (
                            <p>
                                {history.startup.stage}
                                {history.startup.total > 0 &&
                                    ` · ${history.startup.completed.toLocaleString()} / ${history.startup.total.toLocaleString()} 檔`}
                            </p>
                        )}
                    </div>
                </section>
            )}
            {metadata && (
                <>
                    <div className="fh-market">
                        <div className="fh-map-column">
                            <section className="fh-card fh-map">
                                <div className="fh-section-heading">
                                    <div>
                                        <h2>
                                            {renderedDate} 正在大漲的產業與股票
                                        </h2>
                                        <p>
                                            圓越大，代表這波漲得越快。滿一年採年化，未滿一年採實際漲幅。
                                        </p>
                                    </div>
                                    <label className="fh-threshold">
                                        飆股門檻
                                        <select
                                            aria-label="飆股門檻"
                                            value={thresholdPct}
                                            onChange={(event) =>
                                                setThresholdPct(
                                                    Number(event.target.value),
                                                )
                                            }
                                        >
                                            <option value={60}>
                                                至少 +60%
                                            </option>
                                            <option value={80}>
                                                至少 +80%
                                            </option>
                                            <option value={100}>
                                                至少 +100%
                                            </option>
                                            <option value={200}>
                                                至少 +200%
                                            </option>
                                        </select>
                                    </label>
                                </div>
                                {datedComparisons.length === 1 ? (
                                    <div className="fh-phase-legend">
                                        <span>
                                            <i
                                                style={{
                                                    background:
                                                        "var(--compare-1)",
                                                }}
                                            />
                                            當日有持有證據
                                        </span>
                                        <span>
                                            <i className="fh-phase-unknown" />
                                            未持有
                                        </span>
                                        <span>斜線＝持股未知</span>
                                        <small>
                                            顏色只比較這天的持股，尚未比較整波收益。
                                        </small>
                                    </div>
                                ) : (
                                    <div className="fh-phase-legend">
                                        <span>
                                            <i className="fh-phase-rising" />
                                            大漲中
                                        </span>
                                        <span>
                                            <i className="fh-phase-slow" />
                                            慢慢上漲
                                        </span>
                                        <span>
                                            <i className="fh-phase-resting" />
                                            漲多休息
                                        </span>
                                        <span>
                                            <i className="fh-phase-retreat" />
                                            從高點拉回
                                        </span>
                                        <span>
                                            <i className="fh-phase-unknown" />
                                            尚未判斷
                                        </span>
                                        {datedComparisons.length > 1 && (
                                            <small>
                                                彩色小點與右側文字分別對照各策略的當日持股。
                                            </small>
                                        )}
                                    </div>
                                )}
                                <div className="fh-map-frame">
                                    {active && view && displayed.length ? (
                                        <OpportunityMap
                                            fill
                                            view={view}
                                            groupingMode="snapshot"
                                            colorBasis="phase"
                                            comparisons={datedComparisons}
                                            selectedSecurityId={selectedId}
                                            selectedWaveId={selected?.waveId}
                                            onSelect={setSelectedId}
                                            reducedMotion={reducedMotion}
                                            showComparisonDots={
                                                datedComparisons.length > 1
                                            }
                                        />
                                    ) : (
                                        <div className="fh-empty">
                                            <strong>
                                                {!frame
                                                    ? frameStatusMessage(
                                                          frameDisplay,
                                                      )
                                                    : !active
                                                      ? "頁面已暫停"
                                                      : "這天尚無符合顯示條件的候選大漲股"}
                                            </strong>
                                            <p>
                                                {frame
                                                    ? "完整行情保留在時間帶與目錄；也可以先看一個案例日期。"
                                                    : "取得行情後才會判斷哪些股票符合顯示條件。"}
                                            </p>
                                            <div className="fh-controls">
                                                {[
                                                    "2014-06-30",
                                                    "2021-04-29",
                                                    "2024-06-28",
                                                ].map((date) => (
                                                    <button
                                                        key={date}
                                                        onClick={() =>
                                                            history.goToDate(
                                                                date,
                                                            )
                                                        }
                                                    >
                                                        {date.slice(0, 4)} 年
                                                    </button>
                                                ))}
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </section>
                            <section
                                className="fh-card fh-datebar"
                                aria-label="歷史交易日"
                            >
                                <button
                                    className="fh-play"
                                    onClick={() =>
                                        history.setPlaying(!history.playing)
                                    }
                                    disabled={!active || !!history.error}
                                    aria-label={
                                        history.playing
                                            ? "暫停播放"
                                            : "播放歷史變化"
                                    }
                                >
                                    {history.playing ? "Ⅱ" : "▶"}
                                </button>
                                <div className="fh-timebar-track">
                                    <input
                                        aria-label="歷史交易日時間軸"
                                        type="range"
                                        min={0}
                                        max={metadata.dates.length - 1}
                                        value={history.index}
                                        onChange={(e) => {
                                            history.setPlaying(false);
                                            history.navigate(
                                                Number(e.target.value),
                                            );
                                        }}
                                    />
                                    <div className="fh-date-labels">
                                        <span>{metadata.dates[0]}</span>
                                        <span role="status">
                                            {frameStatusMessage(frameDisplay)}
                                        </span>
                                        <span>{metadata.dates.at(-1)}</span>
                                    </div>
                                </div>
                                <div className="fh-timebar-tools">
                                    <form onSubmit={submitDate}>
                                        <input
                                            name="observationDate"
                                            aria-label="前往日期"
                                            type="date"
                                            min={metadata.dates[0]}
                                            max={metadata.dates.at(-1)}
                                            value={dateDraft}
                                            onChange={(e) =>
                                                setDateDraft(e.target.value)
                                            }
                                        />
                                        <button type="submit">前往</button>
                                    </form>
                                    <label className="fh-speed">
                                        播放速度
                                        <select
                                            value={history.step}
                                            onChange={(e) =>
                                                history.setStep(
                                                    Number(e.target.value),
                                                )
                                            }
                                        >
                                            <option value={20}>慢</option>
                                            <option value={40}>中</option>
                                            <option value={60}>快</option>
                                        </select>
                                    </label>
                                </div>
                            </section>
                        </div>
                        <aside className="fh-card fh-aside">
                            <h2>
                                {mode === "launched"
                                    ? "正在大漲的股票"
                                    : "完整行情中的股票"}
                            </h2>
                            {selected && (
                                <div className="fh-stock-card">
                                    <button
                                        className="fh-close"
                                        aria-label="收起股票卡"
                                        onClick={() => setSelectedId(null)}
                                    >
                                        ×
                                    </button>
                                    <h3>
                                        {selected.name}
                                        <small>
                                            {selected.code} ·{" "}
                                            {selected.industry.label}
                                        </small>
                                    </h3>
                                    <small>
                                        {growthBasisLabel(selected.growth)}
                                    </small>
                                    <strong
                                        className="fh-stock-gain"
                                        data-return={
                                            selected.growth?.sizingGainPct ==
                                            null
                                                ? "unknown"
                                                : selected.growth
                                                        .sizingGainPct < 0
                                                  ? "loss"
                                                  : selected.growth
                                                          .sizingGainPct > 0
                                                    ? "profit"
                                                    : "flat"
                                        }
                                    >
                                        {percent(
                                            selected.growth?.sizingGainPct ??
                                                null,
                                        )}
                                    </strong>
                                    <p>
                                        {growthDurationLabel(selected.growth)}
                                    </p>
                                    {selected.growth?.sizingGainPct == null && (
                                        <p>
                                            {growthUnknownExplanation(
                                                selected.growth,
                                            )}
                                        </p>
                                    )}
                                    {frame &&
                                        !appears(
                                            selected,
                                            frame.date,
                                            mode,
                                            thresholdPct,
                                        ) && (
                                            <p>
                                                這檔目前未符合版圖顯示條件；完整行情仍保留供核對。
                                            </p>
                                        )}
                                    <p>
                                        自 {selected.start} 到 {frame?.date}
                                    </p>
                                    <p>
                                        調整收盤價：
                                        {selected.startAdjusted?.toFixed(2) ??
                                            "未知"}{" "}
                                        →{" "}
                                        {selected.adjusted?.toFixed(2) ??
                                            "未知"}{" "}
                                        元
                                    </p>
                                    <dl>
                                        <dt>本波實際總漲幅</dt>
                                        <dd>
                                            {percent(selected.gain)} ·{" "}
                                            {selected.start} 至 {frame?.date}
                                        </dd>
                                        <dt>開始大漲（候選）</dt>
                                        <dd>
                                            {selected.launchCandidate?.date ??
                                                "還沒有明確開始點"}
                                        </dd>
                                        <dt>開始大漲至這天</dt>
                                        <dd>
                                            {percent(
                                                selected.launchGain ?? null,
                                            )}
                                            {selected.launchCandidate &&
                                                ` · 自 ${selected.launchCandidate.date}`}
                                        </dd>
                                        <dt>這波後來最高</dt>
                                        <dd>
                                            {percent(selected.peakGain)} ·{" "}
                                            {selected.peakDate}
                                        </dd>
                                        <dt>當時階段（候選）</dt>
                                        <dd>{phaseLabel(selected.phase)}</dd>
                                        <dt>這波結束</dt>
                                        <dd>
                                            {selected.endConfirmedAt ??
                                                `尚未確認，觀察至 ${selected.observedThrough}`}
                                        </dd>
                                    </dl>
                                    <button
                                        onClick={() =>
                                            detailElement.current?.scrollIntoView(
                                                {
                                                    behavior: reducedMotion
                                                        ? "instant"
                                                        : "smooth",
                                                    block: "start",
                                                },
                                            )
                                        }
                                    >
                                        看這檔的走勢細節 ↓
                                    </button>
                                </div>
                            )}
                            <HistoryRanking
                                rows={displayed}
                                date={frame?.date ?? ""}
                                selectedId={selectedId}
                                onSelect={setSelectedId}
                                comparisons={datedComparisons}
                                display={frameDisplay}
                            />
                            {ended.length > 0 && (
                                <details>
                                    <summary>
                                        最近 30 日結束的行情 · {ended.length} 檔
                                    </summary>
                                    {ended.slice(0, 15).map((row) => (
                                        <button
                                            className="fh-ended-row"
                                            key={row.security.id}
                                            onClick={() =>
                                                setSelectedId(row.security.id)
                                            }
                                        >
                                            {row.security.name}
                                            <span>
                                                {percent(row.gain)} · 結束時保有
                                            </span>
                                        </button>
                                    ))}
                                    <p>
                                        這份清單只列已確認結束的行情。版圖也可能因時間指標未達門檻而縮小或暫時不顯示。
                                    </p>
                                </details>
                            )}
                        </aside>
                    </div>
                    {history.error && (
                        <div className="fh-error" role="alert">
                            讀取 {desiredDate} 暫時失敗。
                            {frame && `地圖仍顯示 ${frame.date}。`}
                            <button onClick={history.retry}>重新讀取</button>
                            <p>
                                若歷史快照驗證失敗，請檢查本機快照並重新啟動資料服務。
                            </p>
                        </div>
                    )}
                    <section className="fh-card fh-options">
                        <div className="fh-compare-toggle">
                            <button
                                aria-expanded={showComparisons}
                                onClick={() => setShowComparisons((v) => !v)}
                            >
                                對照策略／ETF{" "}
                                {comparisons.length
                                    ? `· 已選 ${comparisons.length} 個`
                                    : "→"}
                            </button>
                            <a href="#research">查看策略研究紀錄</a>
                        </div>
                        <div className="fh-growth-rule">
                            <div>
                                <b>把漲幅放回時間裡</b>
                                <p>
                                    滿一年看年化報酬；未滿一年看實際漲幅。圓形大小也用同一指標。
                                </p>
                            </div>
                            <details>
                                <summary>怎麼算、哪些資料保留</summary>
                                {frame && (
                                    <p>
                                        未達 {thresholdPct}%：{belowThreshold}{" "}
                                        檔；漲幅或時間待核對：{unknownGrowth}{" "}
                                        檔。
                                        {mode === "launched" &&
                                            `另有 ${noCandidate} 檔開始點尚未判斷、${notYet} 檔尚未開始，未畫入。`}
                                        資料未知不代表未達門檻。
                                    </p>
                                )}
                                <p>
                                    從本波起點算到觀察日。年化報酬 =（1 +
                                    實際報酬）^(1 ÷ 年數) − 1；一年採 365.25
                                    天，整日資料從第 366
                                    天改用年化。未滿一年不放大短期漲幅。
                                </p>
                                <p>
                                    原始總漲幅與完整波段仍可查；缺價或起點可能截斷時不猜數字。指標兩倍，等效直徑兩倍。年化是這段歷史走勢的換算，不是未來報酬預測。
                                </p>
                            </details>
                            <p className="fh-caption">
                                產業旁數字，是族群內最高指標的那檔股票，不是全產業報酬。階段也是候選標記；產業分類沿用現有資料，當年歸屬仍待補證。
                            </p>
                        </div>
                    </section>
                    {frame && (
                        <div hidden={!showComparisons}>
                            <HistoryComparisons
                                date={frame.date}
                                rows={displayed}
                                catalogId={frame.catalogId}
                                onComparisons={setComparisons}
                            />
                        </div>
                    )}
                    {directory ? (
                        <HistoryTimeline
                            directory={directory}
                            metadata={metadata}
                            frame={frame}
                            selectedId={selectedId}
                            onSelect={setSelectedId}
                            onDate={history.goToDate}
                            comparisons={comparisons}
                            thresholdPct={thresholdPct}
                        />
                    ) : (
                        <section className="fh-card">
                            <h2>各股上漲期間</h2>
                            <p role="status">
                                {history.directoryError
                                    ? "時間帶暫時無法讀取，地圖仍可使用。"
                                    : "正在讀取完整行情目錄…"}
                            </p>
                            {history.directoryError && (
                                <button onClick={history.retry}>
                                    重新讀取時間帶
                                </button>
                            )}
                        </section>
                    )}
                    <div ref={detailElement} className="fh-detail-anchor">
                        {history.detailLoading && (
                            <div className="fh-card" role="status">
                                正在讀取個股走勢與候選標記…
                            </div>
                        )}
                        {history.detailError && (
                            <div className="fh-error" role="alert">
                                個股走勢暫時無法讀取。
                                <button onClick={history.retry}>
                                    重新讀取
                                </button>
                            </div>
                        )}
                        {history.detail && (
                            <HistoryChartDetail
                                key={`${history.detail.catalogId}:${history.detail.sample.id}:${history.detail.date}`}
                                detail={history.detail}
                            />
                        )}
                    </div>
                    <section className="fh-card fh-settings">
                        <h2>顯示方式與完整目錄</h2>
                        <p>
                            下方保留完整波段，包含尚未符合 {thresholdPct}%
                            時間指標的股票。
                        </p>
                        <label>
                            版圖顯示
                            <select
                                value={mode}
                                onChange={(e) =>
                                    setMode(
                                        e.target.value as HistoryDisplayMode,
                                    )
                                }
                            >
                                <option value="launched">
                                    開始大漲後（候選標記）
                                </option>
                                <option value="catalog">
                                    不限制候選開始日（仍套用門檻）
                                </option>
                            </select>
                        </label>
                        <p>
                            預設遵照「開始大漲後才出現」。候選開始點與階段仍待案例確認；切換顯示不會改動原目錄或大小公式。
                        </p>
                        <details>
                            <summary>
                                {frameDisplay.hasFrame
                                    ? `${frameDisplay.renderedDate} 完整行情清單 · ${frameDisplay.rowCount} 檔`
                                    : `完整行情清單 · ${frameStatusMessage(frameDisplay)}`}
                            </summary>
                            <div className="fh-controls">
                                <input
                                    aria-label="搜尋完整行情"
                                    placeholder="股票、代碼或產業"
                                    value={query}
                                    onChange={(e) => setQuery(e.target.value)}
                                />
                            </div>
                            <div className="fh-table-scroll">
                                <table>
                                    <thead>
                                        <tr>
                                            <th>股票</th>
                                            <th>產業</th>
                                            <th>這波開始</th>
                                            <th>至這天已漲</th>
                                            <th>時間調整指標</th>
                                            <th>採用方式／歷時</th>
                                            <th>後來最高</th>
                                            <th>最高日期</th>
                                            <th>開始大漲（候選）</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {!frame && (
                                            <tr>
                                                <td colSpan={9}>
                                                    {frameStatusMessage(
                                                        frameDisplay,
                                                    )}
                                                </td>
                                            </tr>
                                        )}
                                        {allRows.map((row) => (
                                            <tr
                                                key={row.securityId}
                                                aria-selected={
                                                    selectedId ===
                                                    row.securityId
                                                }
                                            >
                                                <td>
                                                    <button
                                                        className="fh-stock-link"
                                                        onClick={() =>
                                                            setSelectedId(
                                                                row.securityId,
                                                            )
                                                        }
                                                    >
                                                        {row.code} {row.name}
                                                    </button>
                                                </td>
                                                <td>{row.industry.label}</td>
                                                <td>{row.start}</td>
                                                <td>{percent(row.gain)}</td>
                                                <td>
                                                    {percent(
                                                        row.growth
                                                            ?.sizingGainPct ??
                                                            null,
                                                    )}
                                                </td>
                                                <td>
                                                    {growthBasisLabel(
                                                        row.growth,
                                                    )}{" "}
                                                    ·{" "}
                                                    {growthDurationLabel(
                                                        row.growth,
                                                    )}
                                                </td>
                                                <td>{percent(row.peakGain)}</td>
                                                <td>{row.peakDate}</td>
                                                <td>
                                                    {row.launchCandidate
                                                        ?.date ?? "待辨識"}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        </details>
                        {frame && (
                            <HistoryMethodOptions
                                catalogId={frame.catalogId}
                                date={frame.date}
                                onDate={history.goToDate}
                            />
                        )}
                    </section>
                    <section className="fh-card fh-limitations">
                        <h2>
                            本版涵蓋 {metadata.coverage.stocks.toLocaleString()}{" "}
                            檔股票 · {metadata.coverage.from} —{" "}
                            {metadata.coverage.to}
                        </h2>
                        <p>
                            這是事後整理的市場機會，開始點、階段與最高漲幅不代表當時能提前知道。
                        </p>
                        <details>
                            <summary>資料範圍、價格與尚待補齊的部分</summary>
                            <p>
                                產業用目前的分類，當年可能不同；沒有分類證據的股票仍保留。
                            </p>
                            <p>{priceExplanation(metadata.basisLabel)}</p>
                            <p>
                                市值調整暫未啟用，因歷史市值仍待核對。大小採時間調整指標：年化／未滿一年實際漲幅兩倍，等效直徑兩倍。
                            </p>
                            <p>
                                另有 {metadata.coverage.excluded}{" "}
                                個資料項目未納入；涵蓋股票數不代表全部曾上市公司。
                            </p>
                            <ul>
                                {metadata.limitations.map((text) => (
                                    <li key={text}>{text}</li>
                                ))}
                            </ul>
                            <p>{metadata.ruleLabel}</p>
                        </details>
                        <details>
                            <summary>研究證據與資料版本</summary>
                            <pre>
                                {JSON.stringify(
                                    {
                                        schema: metadata.schema,
                                        catalogId: metadata.catalogId,
                                        coverage: metadata.coverage,
                                        basisLabel: metadata.basisLabel,
                                        growthRule: "wave-growth-display.v1",
                                        growthThresholdPct: thresholdPct,
                                    },
                                    null,
                                    2,
                                )}
                            </pre>
                        </details>
                    </section>
                </>
            )}
        </div>
    );
}
