import { useState } from "react";
import { WaveChart } from "../wave-lab/WaveChart";
import type { HistoryDetail } from "./types.ts";
import { priceExplanation } from "../../components/priceExplanation.ts";
import type { Launch, Wave } from "../wave-lab/types.ts";
import { growthBasisLabel, growthDurationLabel } from "./growthDisplay.ts";

const priceLabel = (value: number | null | undefined) =>
    value == null
        ? "未知"
        : `${value.toLocaleString("zh-TW", { maximumFractionDigits: 2 })} 元`;
const percentLabel = (value: number | null | undefined) =>
    value == null ? "未知" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
const launchKindLabel: Record<Launch["kind"], string> = {
    reversal: "跌勢反轉",
    breakout: "整理後上攻",
    acceleration: "緩升後加速",
};
const launchOutcomeLabel: Record<Launch["outcome"], string> = {
    continued: "後段延續",
    failed: "後段未延續",
    unresolved: "後段尚未定案",
};
const methodLabel = { segments: "趨勢分段", filter: "趨勢濾波" } as const;
const scaleLabel = { fine: "細", balanced: "中", coarse: "粗" } as const;

export function HistoryChartDetail({ detail }: { detail: HistoryDetail }) {
    const { sample, results } = detail;
    const [raw, setRaw] = useState(false),
        [logarithmic, setLogarithmic] = useState(false);
    const [phases, setPhases] = useState(true),
        [waves, setWaves] = useState(true),
        [candidates, setCandidates] = useState(true);
    const [method, setMethod] = useState(results[0]?.method ?? "segments");
    const [scale, setScale] = useState(
        results.some(
            (r) =>
                r.method === (results[0]?.method ?? "segments") &&
                r.scale === "balanced",
        )
            ? "balanced"
            : (results[0]?.scale ?? "balanced"),
    );
    const [cursor, setCursor] = useState(
        Math.max(
            0,
            sample.points.findIndex((p) => p.date === detail.date),
        ),
    );
    const [range, setRange] = useState<[number, number]>([
        0,
        Math.max(0, sample.points.length - 1),
    ]);
    const [selectedWave, setSelectedWave] = useState<string | null>(null);
    const [selectedLaunch, setSelectedLaunch] = useState<string | null>(null);
    const saved = results.find(
        (result) => result.scale === scale && result.method === method,
    );
    const shown = saved ? [saved] : [];
    const selectedWaveDetails = saved?.waves.find(
        (wave) => wave.id === selectedWave,
    );
    const selectedLaunchId = selectedLaunch?.startsWith(`${method}:`)
        ? selectedLaunch.slice(method.length + 1)
        : null;
    const selectedLaunchDetails = saved?.launches.find(
        (launch) => launch.id === selectedLaunchId,
    );

    function renderWaveDetails(wave: Wave) {
        const start = detail.sample.points[wave.start];
        const peak = detail.sample.points[wave.peak];
        const endIndex = wave.end ?? wave.observedThrough;
        const end = detail.sample.points[endIndex];
        return (
            <div className="fh-chart-evidence-grid">
                <div>
                    <small>波段起點</small>
                    <strong>{start?.date ?? "未知"}</strong>
                    <span>調整收盤 {priceLabel(start?.adjusted)}</span>
                </div>
                <div>
                    <small>事後峰值</small>
                    <strong>{peak?.date ?? "未知"}</strong>
                    <span>調整收盤 {priceLabel(peak?.adjusted)}</span>
                </div>
                <div>
                    <small>
                        {wave.end === null ? "目前觀察截止" : "結束確認"}
                    </small>
                    <strong>{end?.date ?? "未知"}</strong>
                    <span>調整收盤 {priceLabel(end?.adjusted)}</span>
                </div>
                <div>
                    <small>起點到峰值最高漲幅</small>
                    <strong>{percentLabel(wave.gain)}</strong>
                    <span>
                        {wave.scale === "large" ? "大波段" : "小波段"}
                        {wave.leftCensored ? " · 起點可能截斷" : " · 起點保留"}
                        {wave.rightCensored ? " · 尚未確認結束" : ""}
                    </span>
                </div>
            </div>
        );
    }

    function renderLaunchDetails(launch: Launch) {
        const dateAt = (index: number) =>
            detail.sample.points[index]?.date ?? "未知";
        const perDay = (slope: number) => percentLabel(Math.expm1(slope) * 100);
        return (
            <>
                <div className="fh-chart-evidence-grid">
                    <div>
                        <small>候選代表日</small>
                        <strong>{dateAt(launch.index)}</strong>
                        <span>{launchKindLabel[launch.kind]}</span>
                    </div>
                    <div className="fh-chart-span-note">
                        <small>後續上攻分段</small>
                        <strong>
                            {dateAt(launch.rangeStart)} 至{" "}
                            {dateAt(launch.rangeEnd)}
                        </strong>
                        <span>
                            這是候選發車後的上攻分段，不是起點日期不確定範圍。
                        </span>
                    </div>
                    <div>
                        <small>分段前後每日漲幅</small>
                        <strong>
                            {perDay(launch.preSlope)} →{" "}
                            {perDay(launch.postSlope)}
                        </strong>
                        <span>保存的速度變化</span>
                    </div>
                    <div>
                        <small>後段持續觀測</small>
                        <strong>{launch.sustainSessions} 個交易日間隔</strong>
                        <span>自 {dateAt(launch.index)} 起</span>
                    </div>
                    <div>
                        <small>速度變化 ÷ 日常波動</small>
                        <strong>
                            {launch.relativeStrength == null
                                ? "未知"
                                : `${launch.relativeStrength.toFixed(2)} 倍`}
                        </strong>
                        <span>原保存指標，不是信心機率</span>
                    </div>
                    <div>
                        <small>後續起訖漲幅</small>
                        <strong>{percentLabel(launch.forwardGain)}</strong>
                        <span>
                            {dateAt(launch.index)} 至{" "}
                            {dateAt(launch.forwardEnd)}
                        </span>
                    </div>
                    <div>
                        <small>後續最大回撤</small>
                        <strong>
                            {launch.drawdown == null
                                ? "未知"
                                : `${launch.drawdown.toFixed(1)}%`}
                        </strong>
                    </div>
                    <div>
                        <small>保存的後續結果</small>
                        <strong>{launchOutcomeLabel[launch.outcome]}</strong>
                        <span>原研究以後段末漲幅 +5% 作分界</span>
                    </div>
                    <div>
                        <small>跨尺度相近候選</small>
                        <strong>{launch.support} / 3 個尺度</strong>
                        <span>位置接近程度，不是信心分數</span>
                    </div>
                </div>
                <p className="fh-chart-evidence-note">
                    以上是資料中已保存的後續結果與原有指標；不是實際持倉報酬，也沒有另外合成分數。
                </p>
            </>
        );
    }
    return (
        <section className="fh-card fh-detail" aria-label="個股保存研究圖表">
            <div className="fh-section-heading">
                <div>
                    <span className="fh-eyebrow">這檔股票怎麼漲上來</span>
                    <h2>
                        {sample.code} {sample.name}
                    </h2>
                </div>
                <strong>{detail.date}</strong>
            </div>
            <p>
                {priceExplanation(sample.source.priceBasis)}
                開始點與階段是候選標記，最高點是事後回看；切換下方方法，看日期是否符合你的理解。
            </p>
            {detail.row && (
                <p className="fh-detail-compare-note">
                    版圖指標：{growthBasisLabel(detail.row.growth)}{" "}
                    {percentLabel(detail.row.growth?.sizingGainPct)}。
                    本波實際總漲幅 {percentLabel(detail.row.gain)}；
                    {detail.row.start} 至 {detail.date}，
                    {growthDurationLabel(detail.row.growth)}。
                    下方切換方法是在比較保存波段，不會偷偷改版圖使用的代表波段。
                </p>
            )}
            <div className="fh-controls">
                <label>
                    價格{" "}
                    <select
                        value={raw ? "raw" : "adjusted"}
                        onChange={(e) => setRaw(e.target.value === "raw")}
                    >
                        <option value="adjusted">調整價格</option>
                        <option value="raw">原始價格</option>
                    </select>
                </label>
                <label>
                    座標{" "}
                    <select
                        value={logarithmic ? "log" : "linear"}
                        onChange={(e) =>
                            setLogarithmic(e.target.value === "log")
                        }
                    >
                        <option value="linear">線性</option>
                        <option value="log">對數</option>
                    </select>
                </label>
                <label>
                    比較方法{" "}
                    <select
                        value={method}
                        onChange={(e) => {
                            const next = e.target.value as typeof method;
                            setMethod(next);
                            setSelectedWave(null);
                            setSelectedLaunch(null);
                            const available = results.filter(
                                (r) => r.method === next,
                            );
                            setScale(
                                available.some((r) => r.scale === scale)
                                    ? scale
                                    : (available.find(
                                          (r) => r.scale === "balanced",
                                      )?.scale ??
                                          available[0]?.scale ??
                                          "balanced"),
                            );
                        }}
                    >
                        {[...new Set(results.map((r) => r.method))].map((m) => (
                            <option key={m} value={m}>
                                {
                                    {
                                        segments: "分段方法",
                                        filter: "濾波方法",
                                    }[m]
                                }
                            </option>
                        ))}
                    </select>
                </label>
                <label>
                    波段尺度{" "}
                    <select
                        value={scale}
                        onChange={(e) => {
                            setScale(e.target.value as typeof scale);
                            setSelectedWave(null);
                            setSelectedLaunch(null);
                        }}
                    >
                        {[
                            ...new Set(
                                results
                                    .filter((r) => r.method === method)
                                    .map((r) => r.scale),
                            ),
                        ].map((s) => (
                            <option key={s} value={s}>
                                {
                                    {
                                        fine: "細",
                                        balanced: "中",
                                        coarse: "粗",
                                    }[s]
                                }
                            </option>
                        ))}
                    </select>
                </label>
                <label>
                    <input
                        type="checkbox"
                        checked={phases}
                        onChange={(e) => setPhases(e.target.checked)}
                    />
                    分段
                </label>
                <label>
                    <input
                        type="checkbox"
                        checked={waves}
                        onChange={(e) => setWaves(e.target.checked)}
                    />
                    波段
                </label>
                <label>
                    <input
                        type="checkbox"
                        checked={candidates}
                        onChange={(e) => setCandidates(e.target.checked)}
                    />
                    開始大漲（候選）
                </label>
            </div>
            {sample.points.length > 1 ? (
                <>
                    <WaveChart
                        sample={sample}
                        results={shown}
                        waves={saved?.waves ?? []}
                        cursor={cursor}
                        onCursor={setCursor}
                        range={range}
                        onRange={setRange}
                        raw={raw}
                        logarithmic={logarithmic}
                        showPhases={phases}
                        showLaunches={candidates}
                        showWaves={waves}
                        selectedLaunch={selectedLaunch}
                        onLaunch={(id) => {
                            setSelectedLaunch(id);
                            setSelectedWave(null);
                        }}
                        selectedWave={selectedWave}
                        onWave={(id) => {
                            setSelectedWave(id);
                            setSelectedLaunch(null);
                        }}
                    />
                    <label className="fh-chart-date">
                        圖表日期{" "}
                        <input
                            type="date"
                            min={sample.points[0].date}
                            max={sample.points.at(-1)?.date}
                            value={sample.points[cursor]?.date ?? ""}
                            onChange={(e) => {
                                const index = sample.points.findLastIndex(
                                    (p) => p.date <= e.target.value,
                                );
                                const next = Math.max(0, index);
                                setCursor(next);
                                setRange((previous) => [
                                    Math.min(previous[0], next),
                                    Math.max(previous[1], next),
                                ]);
                            }}
                        />
                    </label>
                    <section
                        className="fh-chart-selection"
                        aria-label="已選取的波段或候選啟動明細"
                    >
                        <div className="fh-section-heading">
                            <h3>圖上選取明細</h3>
                            <span>
                                {methodLabel[method]} · {scaleLabel[scale]}尺度
                            </span>
                        </div>
                        {selectedWaveDetails ? (
                            renderWaveDetails(selectedWaveDetails)
                        ) : selectedLaunchDetails ? (
                            renderLaunchDetails(selectedLaunchDetails)
                        ) : (
                            <p role="status">
                                點選圖上的波段或候選發車，查看保存的日期、調整價格與後續結果。
                            </p>
                        )}
                    </section>
                </>
            ) : (
                <p role="status">這檔股票尚無足夠的保存價格可繪圖。</p>
            )}
            {sample.source.limitations.length > 0 && (
                <ul>
                    {sample.source.limitations
                        .filter(
                            (text) =>
                                text !==
                                "全市場 ETF 與策略持股比較尚未接入，不能把未知視為未持有。",
                        )
                        .map((text) => (
                            <li key={text}>{text}</li>
                        ))}
                </ul>
            )}
            <p className="fh-detail-compare-note">
                比較目前只示範已保存帳本中有證據與覆蓋的持股期間，不代表全市場持股結果。
            </p>
            <details>
                <summary>研究證據與資料版本</summary>
                <pre>
                    {JSON.stringify(
                        {
                            schema: detail.schema,
                            catalogId: detail.catalogId,
                            source: sample.source,
                            row: detail.row,
                            evidence: detail.evidence,
                            savedResults: results.map((r) => ({
                                method: r.method,
                                scale: r.scale,
                                warnings: r.warnings,
                                diagnostics: r.diagnostics,
                            })),
                        },
                        null,
                        2,
                    )}
                </pre>
            </details>
        </section>
    );
}
