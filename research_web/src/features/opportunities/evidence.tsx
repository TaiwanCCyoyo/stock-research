import { useMemo } from "react";
import { getHoldingState } from "../../domain/opportunities/model.ts";
import type {
    MarketView,
    OpportunityBundle,
    OpportunityPortfolio,
    OpportunitySecurity,
    OpportunityWave,
    PortfolioComparison,
} from "../../domain/opportunities/types.ts";
import { reasonText, seriesColor, share } from "./evidenceFormat.ts";
import { classificationLabel } from "./classificationDisplay.ts";
import { researchName } from "../research/researchDisplay.ts";

export function Sparkline({
    security,
    wave,
    date,
    portfolios = [],
    large = false,
}: {
    security: OpportunitySecurity;
    wave: OpportunityWave;
    date: string;
    portfolios?: OpportunityPortfolio[];
    large?: boolean;
}) {
    const through = date < wave.observedThrough ? date : wave.observedThrough;
    const chart = useMemo(() => {
        const points = security.prices.filter(
            (p) => p.date >= wave.start && p.date <= through,
        );
        const valid = points.filter((p) => p.close != null && !p.flags.length);
        if (valid.length < 2) return null;
        const values = valid.map((p) => p.close!);
        const min = Math.min(...values),
            max = Math.max(...values),
            w = 400,
            h = large ? 180 : 76;
        const xy = (i: number) => [
            6 + (i / Math.max(1, points.length - 1)) * (w - 12),
            h - 6 - ((points[i].close! - min) / (max - min || 1)) * (h - 14),
        ];
        let line = "",
            pen = false;
        const held: { path: string; index: number }[] = [];
        points.forEach((p, i) => {
            if (p.close == null || p.flags.length) {
                pen = false;
                return;
            }
            const [x, y] = xy(i);
            line += `${pen ? "L" : "M"}${x},${y}`;
            if (pen)
                portfolios.forEach((portfolio, index) => {
                    if (
                        getHoldingState(portfolio, security.id, p.date) ===
                        "held"
                    ) {
                        const [a, b] = xy(i - 1);
                        held.push({ index, path: `M${a},${b}L${x},${y}` });
                    }
                });
            pen = true;
        });
        return { line, held, h };
    }, [security, wave, through, portfolios, large]);
    return chart ? (
        <svg
            className={`op-spark ${large ? "is-large" : ""}`}
            viewBox={`0 0 400 ${chart.h}`}
            role="img"
            aria-label={`${security.name}，${wave.start} 至 ${through} 的收盤走勢；彩色段是有持股紀錄的日期`}
        >
            <path
                d={chart.line}
                fill="none"
                stroke="var(--muted)"
                strokeOpacity=".5"
                strokeWidth={large ? 2 : 3}
            />
            {chart.held.map((h, i) => (
                <path
                    key={i}
                    d={h.path}
                    fill="none"
                    stroke={seriesColor(h.index)}
                    strokeWidth={large ? 3 : 4}
                />
            ))}
        </svg>
    ) : (
        <span className="op-muted">尚無完整走勢</span>
    );
}

export function CapitalCards({
    comparisons,
    scopeLabel,
}: {
    comparisons: PortfolioComparison[];
    scopeLabel: string;
}) {
    if (!comparisons.length) return null;
    return (
        <section className="op-card op-capital" aria-label="資金放在哪裡">
            <div className="op-section-title">
                <div>
                    <h2>資金放在哪裡？</h2>
                </div>
                <p>{scopeLabel} · 整條代表帳戶全部資產</p>
            </div>
            {comparisons.map((comparison, index) => {
                const c = comparison.capital;
                return (
                    <div
                        className="op-capital-row"
                        key={comparison.portfolio.id}
                    >
                        <div className="op-capital-name">
                            <span
                                className="op-series-dot"
                                style={{ background: seriesColor(index) }}
                            />
                            <strong>
                                {researchName(comparison.portfolio.name)}
                            </strong>
                            <small>{comparison.date}</small>
                        </div>
                        <div className="op-capital-number">
                            <b>{share(c.opportunityWeight)}</b>
                            <span>
                                {c.status === "partial"
                                    ? "已知至少放在大漲股"
                                    : "放在大漲股"}
                            </span>
                        </div>
                        <div className="op-capital-chart">
                            <div
                                className="op-allocation"
                                role="img"
                                aria-label={`${researchName(comparison.portfolio.name)}：大漲股 ${share(c.opportunityWeight)}，其他股票 ${share(c.otherWeight)}，現金 ${share(c.cashWeight)}，其他已知資產 ${share(c.otherAssetsWeight)}，未知 ${share(c.unknownWeight)}`}
                            >
                                {c.industries.map((industry, j) => (
                                    <span
                                        key={industry.id}
                                        className={`op-allocation-industry tone-${j % 4}`}
                                        style={{
                                            width: `${industry.weight * 100}%`,
                                        }}
                                        title={`${industry.label} ${share(industry.weight)}`}
                                    >
                                        {industry.weight > 0.08
                                            ? `${industry.label} ${Math.round(industry.weight * 100)}%`
                                            : ""}
                                    </span>
                                ))}
                                {c.otherWeight != null && c.otherWeight > 0 && (
                                    <span
                                        className="op-allocation-other"
                                        style={{
                                            width: `${c.otherWeight * 100}%`,
                                        }}
                                        title={`其他股票 ${share(c.otherWeight)}`}
                                    >
                                        {c.otherWeight > 0.12 ? "其他股票" : ""}
                                    </span>
                                )}
                                {c.cashWeight != null && c.cashWeight > 0 && (
                                    <span
                                        className="op-allocation-cash"
                                        style={{
                                            width: `${c.cashWeight * 100}%`,
                                        }}
                                        title={`現金 ${share(c.cashWeight)}`}
                                    >
                                        {c.cashWeight > 0.12 ? "現金" : ""}
                                    </span>
                                )}
                                {c.otherAssetsWeight != null &&
                                    c.otherAssetsWeight > 0 && (
                                        <span
                                            className="op-allocation-assets"
                                            style={{
                                                width: `${c.otherAssetsWeight * 100}%`,
                                            }}
                                            title={`未付權益／其他已知資產 ${share(c.otherAssetsWeight)}`}
                                        >
                                            {c.otherAssetsWeight > 0.12
                                                ? "其他資產"
                                                : ""}
                                        </span>
                                    )}
                                {c.unknownWeight > 0 && (
                                    <span
                                        className="op-hatch"
                                        style={{
                                            width: `${c.unknownWeight * 100}%`,
                                        }}
                                        title={`未知資金 ${share(c.unknownWeight)}`}
                                    >
                                        {c.unknownWeight > 0.18
                                            ? "未知資金"
                                            : ""}
                                    </span>
                                )}
                            </div>
                            {c.reason && <small>{reasonText(c.reason)}</small>}
                            <details className="op-comparison-notes">
                                <summary>這個對照的範圍與限制</summary>
                                <p>{comparison.portfolio.description}</p>
                                <ul>
                                    {comparison.portfolio.limitations.map(
                                        (text, i) => (
                                            <li key={i}>{text}</li>
                                        ),
                                    )}
                                </ul>
                            </details>
                        </div>
                    </div>
                );
            })}
            <div className="op-inline-legend">
                <span>
                    <i className="rise" />
                    大漲股
                </span>
                <span>
                    <i className="other" />
                    其他股票
                </span>
                <span>
                    <i className="cash" />
                    現金
                </span>
                <span>
                    <i className="assets" />
                    其他資產
                </span>
                <span>
                    <i className="op-hatch" />
                    未知資金
                </span>
            </div>
        </section>
    );
}

export function OpportunityTimeline({
    bundle,
    view,
    selectedPortfolios,
    selectedSecurityId,
    onSelect,
}: {
    bundle: OpportunityBundle;
    view: MarketView;
    selectedPortfolios: OpportunityPortfolio[];
    selectedSecurityId: string | null;
    onSelect: (id: string, date: string) => void;
}) {
    const rows = useMemo(() => {
        const groups = new Map(view.industries.map((g) => [g.id, g.gainSum]));
        return [...view.rows]
            .filter(
                (r, i, all) =>
                    all.findIndex((a) => a.security.id === r.security.id) === i,
            )
            .sort((a, b) => {
                const aActive = groups.get(a.industry.id) ?? 0,
                    bActive = groups.get(b.industry.id) ?? 0;
                if (aActive !== bActive) return bActive - aActive;
                if (a.industry.id !== b.industry.id)
                    return a.industry.label.localeCompare(
                        b.industry.label,
                        "zh-TW",
                    );
                if (a.state === "active" || b.state === "active")
                    return (
                        (b.state === "active" ? (b.gain ?? 0) : -1) -
                        (a.state === "active" ? (a.gain ?? 0) : -1)
                    );
                return (b.wave.endConfirmedAt ?? "").localeCompare(
                    a.wave.endConfirmedAt ?? "",
                );
            });
    }, [view]);
    const min = Date.parse(bundle.dates[0]),
        max = Date.parse(bundle.dates.at(-1)!);
    const x = (d: string) =>
        Math.max(
            0,
            Math.min(100, ((Date.parse(d) - min) / (max - min || 1)) * 100),
        );
    const cursor = x(view.date);
    const jump = (ratio: number) => {
        const t = min + ratio * (max - min);
        const nearest = bundle.dates.reduce((best, d) =>
            Math.abs(Date.parse(d) - t) < Math.abs(Date.parse(best) - t)
                ? d
                : best,
        );
        return nearest;
    };
    return (
        <section
            className="op-card op-timeline-card"
            aria-label="每檔股票的歷史時間帶"
        >
            <div className="op-section-title">
                <div>
                    <h2>各股上漲期間</h2>
                </div>
                <p>點時間帶移動日期 · 彩色細線為持有紀錄</p>
            </div>
            <div className="op-timeline-scroll">
                <div className="op-timeline-inner">
                    <div className="op-band-axis">
                        <span>{bundle.dates[0]}</span>
                        <b>{view.date}</b>
                        <span>{bundle.dates.at(-1)}</span>
                    </div>
                    <div
                        className="op-band-rows"
                        style={{ height: rows.length * 48 }}
                    >
                        {rows.map((row, index) => (
                            <div
                                key={row.security.id}
                                className={`op-band-row ${row.state === "active" ? "" : "quiet"} ${selectedSecurityId === row.security.id ? "selected" : ""}`}
                                style={{
                                    transform: `translateY(${index * 48}px)`,
                                }}
                            >
                                <button
                                    className="op-band-name"
                                    onClick={() =>
                                        onSelect(row.security.id, view.date)
                                    }
                                >
                                    <strong>{row.security.name}</strong>
                                    <small>{classificationLabel(row)}</small>
                                </button>
                                <div
                                    className="op-band-track"
                                    role="slider"
                                    tabIndex={0}
                                    aria-label={`${row.security.name} 的歷史日期`}
                                    aria-valuemin={0}
                                    aria-valuemax={bundle.dates.length - 1}
                                    aria-valuenow={bundle.dates.indexOf(
                                        view.date,
                                    )}
                                    aria-valuetext={view.date}
                                    onPointerDown={(e) => {
                                        const r =
                                            e.currentTarget.getBoundingClientRect();
                                        const targetDate = jump(
                                            Math.max(
                                                0,
                                                Math.min(
                                                    1,
                                                    (e.clientX - r.left) /
                                                        r.width,
                                                ),
                                            ),
                                        );
                                        onSelect(row.security.id, targetDate);
                                    }}
                                    onKeyDown={(e) => {
                                        const i = bundle.dates.indexOf(
                                            view.date,
                                        );
                                        if (
                                            [
                                                "ArrowLeft",
                                                "ArrowRight",
                                                "Home",
                                                "End",
                                            ].includes(e.key)
                                        ) {
                                            e.preventDefault();
                                            onSelect(
                                                row.security.id,
                                                bundle.dates[
                                                    e.key === "Home"
                                                        ? 0
                                                        : e.key === "End"
                                                          ? bundle.dates
                                                                .length - 1
                                                          : Math.max(
                                                                0,
                                                                Math.min(
                                                                    bundle.dates
                                                                        .length -
                                                                        1,
                                                                    i +
                                                                        (e.key ===
                                                                        "ArrowLeft"
                                                                            ? -1
                                                                            : 1),
                                                                ),
                                                            )
                                                ],
                                            );
                                        }
                                    }}
                                >
                                    {bundle.waves
                                        .filter(
                                            (w) =>
                                                w.securityId ===
                                                    row.security.id &&
                                                bundle.representatives.some(
                                                    (r) => r.waveId === w.id,
                                                ),
                                        )
                                        .map((w) => (
                                            <span
                                                className="op-wave-band"
                                                key={w.id}
                                                style={{
                                                    left: `${x(w.start)}%`,
                                                    width: `${Math.max(0.15, x(w.endConfirmedAt ?? w.observedThrough) - x(w.start))}%`,
                                                }}
                                                title={`${w.start} → ${w.endConfirmedAt ?? `${w.observedThrough}（尚未結束）`}`}
                                            >
                                                {w.phases.map((p, i) => (
                                                    <i
                                                        key={i}
                                                        className={`phase-${p.kind}`}
                                                        style={{
                                                            left: `${((x(p.from) - x(w.start)) / Math.max(0.01, x(w.endConfirmedAt ?? w.observedThrough) - x(w.start))) * 100}%`,
                                                            width: `${((x(p.untilExclusive) - x(p.from)) / Math.max(0.01, x(w.endConfirmedAt ?? w.observedThrough) - x(w.start))) * 100}%`,
                                                        }}
                                                    />
                                                ))}
                                            </span>
                                        ))}
                                    {row.wave.launch && (
                                        <i
                                            className="op-launch-tick"
                                            style={{
                                                left: `${x(row.wave.launch.date)}%`,
                                            }}
                                            title={`開始大漲：${row.wave.launch.date}`}
                                        />
                                    )}
                                    {selectedPortfolios.flatMap((p, i) =>
                                        p.holdings
                                            .filter(
                                                (h) =>
                                                    h.securityId ===
                                                    row.security.id,
                                            )
                                            .flatMap((h, j) =>
                                                p.coverage.map((c, k) => {
                                                    const from =
                                                            h.from > c.from
                                                                ? h.from
                                                                : c.from,
                                                        until =
                                                            h.untilExclusive <
                                                            c.untilExclusive
                                                                ? h.untilExclusive
                                                                : c.untilExclusive;
                                                    return from < until ? (
                                                        <i
                                                            key={`${p.id}-${j}-${k}`}
                                                            className="op-held-band"
                                                            style={{
                                                                left: `${x(from)}%`,
                                                                width: `${x(until) - x(from)}%`,
                                                                top: 28 + i * 3,
                                                                background:
                                                                    seriesColor(
                                                                        i,
                                                                    ),
                                                            }}
                                                            title={`${p.name}：${from} ≤ 日期 < ${until}`}
                                                        />
                                                    ) : null;
                                                }),
                                            ),
                                    )}
                                    <i
                                        className="op-date-line"
                                        style={{ left: `${cursor}%` }}
                                    />
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
            {bundle.waves.some((wave) => wave.phases.length > 0) && (
                <div className="op-inline-legend">
                    <span>
                        <i className="slow" />
                        慢慢漲
                    </span>
                    <span>
                        <i className="rise" />
                        大漲中
                    </span>
                    <span>
                        <i className="rest" />
                        漲多休息
                    </span>
                    <span>
                        <i className="retreat" />
                        從最高點拉回
                    </span>
                </div>
            )}
            <p className="op-footnote">
                每一條是一檔股票的上漲期間，事後回看才畫得出來。排序依當天族群內股票漲幅加總；淡色列是當天未在大漲中的股票。彩色細線表示有持股紀錄的日期，不代表股票上漲或實際盈虧。
            </p>
        </section>
    );
}
