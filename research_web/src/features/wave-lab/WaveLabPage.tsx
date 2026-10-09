import { useEffect, useMemo, useState } from "react";
import { priceExplanation } from "../../components/priceExplanation.ts";
import { syntheticCases } from "./synthetic";
import { validateLabBundle } from "./bundle.ts";
import { WaveChart } from "./WaveChart";
import {
    createFeedbackIdentity,
    readyFeedbackIdentity,
} from "./feedbackIdentity";
import type { FeedbackIdentityState } from "./feedbackIdentity";
import {
    observationGain,
    resolveLabLaunch,
    resolveLabWave,
    waveBoundary,
} from "./waveSelection.ts";
import type {
    AnalysisResult,
    LabCase,
    LabWaveBoundary,
    Launch,
    MethodId,
    Scale,
} from "./types";
import "./WaveLabPage.css";

const METHOD: Record<MethodId, string> = {
    segments: "A · 趨勢分段",
    filter: "B · 趨勢濾波",
};
const PHASE = {
    falling: "下跌／轉弱",
    flat: "整理",
    rising: "緩升",
    fast: "快速上升",
};
const KIND = {
    reversal: "跌勢反轉",
    breakout: "整理後上攻",
    acceleration: "緩升後加速",
};
const OUTCOME = {
    continued: "後段延續",
    failed: "後段未延續",
    unresolved: "尾段未定",
};
const RULE_VERSION = "wave-lab-exploratory.v1";
const pct = (n: number | null | undefined) =>
    n == null ? "—" : `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;
const price = (n: number | null | undefined) =>
    n == null ? "—" : n.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
type Feedback = {
    note: string;
    verdict: string;
    start: number | null;
    end: number | null;
};
const EMPTY: Feedback = {
    note: "",
    verdict: "尚未評註",
    start: null,
    end: null,
};
const readFeedback = (): Record<string, Feedback> => {
    try {
        const value = JSON.parse(
            localStorage.getItem("wave-lab.feedback.v1") ?? "{}",
        );
        return value && typeof value === "object" && !Array.isArray(value)
            ? value
            : {};
    } catch {
        return {};
    }
};
function download(value: unknown, filename: string) {
    const url = URL.createObjectURL(
        new Blob([JSON.stringify(value, null, 2)], {
            type: "application/json",
        }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export function WaveLabPage({
    externalCase,
    initialDate,
    onBack,
}: { externalCase?: LabCase; initialDate?: string; onBack?: () => void } = {}) {
    const [historical, setHistorical] = useState<LabCase[]>([]);
    const [dataStatus, setDataStatus] = useState("正在讀取已保存的案例…");
    const [loadError, setLoadError] = useState("");
    const [caseId, setCaseId] = useState(
            externalCase?.id ?? "user-consolidation-relaunch",
        ),
        [scale, setScale] = useState<Scale>("balanced");
    const [results, setResults] = useState<AnalysisResult[]>([]),
        [busy, setBusy] = useState(true),
        [error, setError] = useState("");
    const [visible, setVisible] = useState<MethodId[]>(["segments", "filter"]);
    const [showPhases, setShowPhases] = useState(true),
        [showLaunches, setShowLaunches] = useState(true),
        [showWaves, setShowWaves] = useState(true);
    const [raw, setRaw] = useState(false),
        [logarithmic, setLogarithmic] = useState(true);
    const [cursor, setCursor] = useState(0),
        [range, setRange] = useState<[number, number]>([0, 1]);
    const [selectedLaunch, setSelectedLaunch] = useState<{
        id: string;
        method: MethodId;
    } | null>(null);
    const [selectedWave, setSelectedWave] = useState<{
        sample: LabCase;
        boundary: LabWaveBoundary;
    } | null>(null);
    const [feedback, setFeedback] = useState(readFeedback),
        [storageError, setStorageError] = useState("");
    const [feedbackIdentity, setFeedbackIdentity] =
        useState<FeedbackIdentityState | null>(null);
    const [identityError, setIdentityError] = useState<{
        sample: LabCase;
        message: string;
    } | null>(null);
    const [exportText, setExportText] = useState("");
    const cases = useMemo(
        () =>
            externalCase ? [externalCase] : [...historical, ...syntheticCases],
        [historical, externalCase],
    );
    const sample =
        cases.find((c) => c.id === caseId) ??
        syntheticCases[3] ??
        syntheticCases[0];
    const currentFeedbackKey = readyFeedbackIdentity(feedbackIdentity, sample);
    const currentIdentityError =
        identityError?.sample === sample ? identityError.message : "";
    useEffect(() => {
        let cancelled = false;
        setFeedbackIdentity(null);
        setIdentityError(null);
        createFeedbackIdentity(sample, RULE_VERSION)
            .then((key) => {
                if (!cancelled) setFeedbackIdentity({ sample, key });
            })
            .catch(() => {
                if (!cancelled)
                    setIdentityError({
                        sample,
                        message:
                            "無法核對本次案例內容，暫時不能保存評註或匯出查證。請重新載入頁面再試。",
                    });
            });
        return () => {
            cancelled = true;
        };
    }, [sample]);
    useEffect(() => {
        setLoadError("");
        if (externalCase) {
            setDataStatus(
                "與地圖使用同一份已保存的價格資料；下方標記為方法比較，尚未定案。",
            );
            return;
        }
        const control = new AbortController();
        fetch(`${import.meta.env.BASE_URL}data/wave-lab-cases.json`, {
            signal: control.signal,
        })
            .then(async (r) => {
                if (!r.ok) throw new Error("真實案例資料尚未提供");
                const data = validateLabBundle(await r.json());
                setHistorical(data.cases);
                setDataStatus(
                    `${data.cases.length} 個真實案例 · 同一份已保存價格基礎`,
                );
                setCaseId((current) => current || data.cases[0].id);
            })
            .catch((e) => {
                if (e.name !== "AbortError") {
                    setLoadError(e.message);
                    setDataStatus("歷史案例未載入；合成案例仍可操作。");
                }
            });
        return () => control.abort();
    }, [externalCase]);
    useEffect(() => {
        const selectedIndex = sample.points.findIndex(
            (p) => p.date === initialDate,
        );
        setCursor(
            selectedIndex >= 0
                ? selectedIndex
                : Math.floor((sample.points.length - 1) * 0.75),
        );
        setRange([0, sample.points.length - 1]);
        setSelectedLaunch(null);
        setSelectedWave(null);
        setExportText("");
    }, [sample, initialDate]);
    useEffect(() => {
        setBusy(true);
        setError("");
        setResults([]);
        setSelectedLaunch(null);
        const worker = new Worker(
            new URL("./analysis.worker.ts", import.meta.url),
            { type: "module" },
        );
        worker.onmessage = (
            event: MessageEvent<{ results?: AnalysisResult[]; error?: string }>,
        ) => {
            if (event.data.error) setError(event.data.error);
            else setResults(event.data.results ?? []);
            setBusy(false);
        };
        worker.onerror = () => {
            setError("案例計算未完成，請切換案例重試。");
            setBusy(false);
        };
        worker.postMessage({ sample, scale });
        return () => worker.terminate();
    }, [sample, scale]);
    useEffect(() => {
        if (!currentFeedbackKey) return;
        try {
            localStorage.setItem(
                "wave-lab.feedback.v1",
                JSON.stringify(feedback),
            );
            setStorageError("");
        } catch {
            setStorageError("瀏覽器無法保存評註，請下載紀錄留存。");
        }
    }, [feedback, currentFeedbackKey]);
    const point = sample.points[Math.min(cursor, sample.points.length - 1)];
    const activeMethod =
        selectedLaunch && visible.includes(selectedLaunch.method)
            ? selectedLaunch.method
            : visible[0];
    const activeResult = results.find((r) => r.method === activeMethod);
    const waves = activeResult?.waves ?? [];
    const manualWave =
        selectedWave?.sample === sample ? selectedWave.boundary : null;
    const preferredWave = manualWave ?? sample.selectedOpportunity ?? null;
    const wave = resolveLabWave(sample, waves, preferredWave);
    const followingSavedWave = !!sample.selectedOpportunity && !manualWave;
    const manualLaunch = activeResult?.launches.find(
        (l) =>
            activeMethod === selectedLaunch?.method &&
            l.id === selectedLaunch?.id,
    );
    const launch: Launch | undefined =
        manualLaunch ??
        (followingSavedWave
            ? wave
                ? resolveLabLaunch(
                      sample,
                      activeResult?.launches ?? [],
                      sample.selectedOpportunity!.launch,
                  )
                : undefined
            : preferredWave && !wave
              ? undefined
              : activeResult?.launches.find(
                    (l) =>
                        !wave ||
                        (l.index >= wave.start && l.index <= wave.peak),
                ));
    const withinWave =
        wave &&
        cursor >= wave.start &&
        cursor <=
            Math.min(wave.end ?? wave.observedThrough, wave.observedThrough);
    const currentGain = wave
        ? observationGain(sample, wave.start, cursor, wave)
        : null;
    const launchGain =
        launch && (!preferredWave || wave)
            ? observationGain(sample, launch.index, cursor, wave)
            : null;
    const phase = activeResult?.segments.find(
        (s) => cursor >= s.start && cursor <= s.end,
    );
    const date = (i: number | undefined) =>
        i == null ? "—" : (sample.points[i]?.date ?? "—");
    const note = currentFeedbackKey
        ? (feedback[currentFeedbackKey] ?? EMPTY)
        : EMPTY;
    const changeFeedback = (patch: Partial<Feedback>) => {
        if (!currentFeedbackKey) return;
        setFeedback((old) => ({
            ...old,
            [currentFeedbackKey]: {
                ...(old[currentFeedbackKey] ?? EMPTY),
                ...patch,
            },
        }));
    };
    const selectLaunch = (id: string, method: MethodId) => {
        id = id.startsWith(`${method}:`) ? id.slice(method.length + 1) : id;
        setSelectedLaunch({ id, method });
        const candidate = results
            .find((r) => r.method === method)
            ?.launches.find((l) => l.id === id);
        if (candidate) {
            setCursor(candidate.index);
            if (candidate.index < range[0] || candidate.index > range[1])
                setRange([0, sample.points.length - 1]);
        }
    };
    const selectWave = (id: string) => {
        const candidate = waves.find((value) => value.id === id);
        const boundary = candidate ? waveBoundary(sample, candidate) : null;
        if (!boundary) return;
        setSelectedWave({ sample, boundary });
        setSelectedLaunch(null);
    };
    const setDate = (value: string) => {
        if (!value) return;
        let i = sample.points.findIndex((p) => p.date >= value);
        if (i < 0) i = sample.points.length - 1;
        setCursor(i);
        if (i < range[0] || i > range[1])
            setRange([0, sample.points.length - 1]);
    };
    const exportEvidence = () => {
        if (!currentFeedbackKey || busy) return;
        const evidence = {
            schema: "wave-lab-review.v1",
            ruleVersion: RULE_VERSION,
            feedbackIdentity: currentFeedbackKey,
            exportedAt: new Date().toISOString(),
            sample,
            scale,
            results,
            selectedLaunch,
            range,
            visibleMethods: visible,
            raw,
            logarithmic,
            cursorDate: point.date,
            representativeWaveId: wave?.id ?? null,
            feedback: note,
        };
        setExportText(JSON.stringify(evidence, null, 2));
        download(evidence, `${sample.id}-wave-review.json`);
    };
    const sliceStart = Math.max(
        0,
        Math.min(cursor - 4, sample.points.length - 9),
    );
    return (
        <div className="wave-lab">
            {onBack && (
                <button className="lab-back" onClick={onBack}>
                    ← 返回股票地圖
                </button>
            )}
            <section className="lab-hero">
                <div>
                    <span className="eyebrow">WAVE STUDIES / 走勢細節</span>
                    <h1>
                        {externalCase
                            ? `${externalCase.name}，這一段怎麼漲？`
                            : "一段行情，幾次發車。"}
                    </h1>
                    <p>
                        從完整漲勢，走進啟動、整理與再次上攻。先看價格，再比較標記是否符合你的理解。
                    </p>
                </div>
                <div className="lab-version">
                    <span className="lab-pill">方法試驗 · 事後回看</span>
                    <small>
                        可沒有明確發車點
                        <br />
                        不會改寫地圖已選定的波段
                    </small>
                </div>
            </section>
            <div className="lab-workspace">
                <aside
                    className="lab-library surface"
                    aria-label="波段案例選單"
                >
                    <div className="lab-library-heading">
                        <span className="eyebrow">CASE LIBRARY</span>
                        <h2>選一段走勢</h2>
                        <p>{dataStatus}</p>
                        {loadError && <p role="alert">{loadError}</p>}
                    </div>
                    {(["historical", "synthetic"] as const).map((kind) => (
                        <section key={kind}>
                            <h3>
                                {kind === "historical"
                                    ? "真實市場 / 檢視案例"
                                    : "合成反例 / 驗證方法"}
                            </h3>
                            {cases
                                .filter((c) => c.kind === kind)
                                .map((c, i) => (
                                    <button
                                        key={c.id}
                                        className={`lab-case${c.id === sample.id ? " active" : ""}`}
                                        aria-pressed={c.id === sample.id}
                                        onClick={() => setCaseId(c.id)}
                                    >
                                        <span className="lab-case-number">
                                            {String(i + 1).padStart(2, "0")}
                                        </span>
                                        <span>
                                            <strong>{c.name}</strong>
                                            <small>{c.category}</small>
                                        </span>
                                        <span className="lab-case-arrow">
                                            ↗
                                        </span>
                                    </button>
                                ))}
                        </section>
                    ))}
                    <p className="lab-library-note">
                        案例按檢視問題選入，不代表已被方法判定成功。失敗與沒有訊號的案例也會保留。
                    </p>
                </aside>
                <div className="lab-main">
                    <section className="surface lab-canvas">
                        <div className="lab-case-heading">
                            <div>
                                <span
                                    className={`lab-pill ${sample.kind === "synthetic" ? "synthetic" : ""}`}
                                >
                                    {sample.kind === "historical"
                                        ? "真實價格"
                                        : "合成示意 · 非真實股票"}
                                </span>
                                <h2>
                                    {sample.name}
                                    {sample.code && (
                                        <small>{sample.code}</small>
                                    )}
                                </h2>
                                <p>{sample.question}</p>
                            </div>
                            <button
                                className="lab-secondary"
                                onClick={exportEvidence}
                                disabled={busy || !currentFeedbackKey}
                            >
                                下載本次查證 ↓
                            </button>
                        </div>
                        {!currentFeedbackKey && (
                            <p
                                className="lab-inline-note"
                                role={currentIdentityError ? "alert" : "status"}
                            >
                                {currentIdentityError ||
                                    "正在核對案例內容，完成後可保存評註及下載查證。"}
                            </p>
                        )}
                        {currentFeedbackKey && exportText && (
                            <div className="lab-export">
                                <p role="status">
                                    查證內容已準備。若瀏覽器未開始下載，可點選下方文字後複製留存。
                                </p>
                                <textarea
                                    aria-label="可複製的查證資料"
                                    readOnly
                                    value={exportText}
                                    onFocus={(e) => e.target.select()}
                                    rows={5}
                                />
                                <button
                                    className="lab-text-button"
                                    onClick={() => setExportText("")}
                                >
                                    收起查證內容
                                </button>
                            </div>
                        )}
                        <div className="lab-method-controls">
                            <div className="lab-method-buttons">
                                {(["segments", "filter"] as const).map((m) => (
                                    <button
                                        key={m}
                                        className={`lab-method ${m}`}
                                        aria-pressed={visible.includes(m)}
                                        onClick={() =>
                                            setVisible((v) =>
                                                v.includes(m)
                                                    ? v.filter((x) => x !== m)
                                                    : [...v, m],
                                            )
                                        }
                                    >
                                        <i />
                                        {METHOD[m]}
                                        <span>
                                            {visible.includes(m)
                                                ? "顯示"
                                                : "隱藏"}
                                        </span>
                                    </button>
                                ))}
                            </div>
                            <label>
                                觀察尺度{" "}
                                <select
                                    aria-label="分段觀察尺度"
                                    value={scale}
                                    onChange={(e) =>
                                        setScale(e.target.value as Scale)
                                    }
                                >
                                    <option value="fine">
                                        細緻 · 看短期變化
                                    </option>
                                    <option value="balanced">
                                        均衡 · 比較轉折
                                    </option>
                                    <option value="coarse">
                                        寬廣 · 看長期主線
                                    </option>
                                </select>
                            </label>
                        </div>
                        <div className="lab-layer-controls">
                            <label>
                                <input
                                    type="checkbox"
                                    checked={showLaunches}
                                    onChange={(e) =>
                                        setShowLaunches(e.target.checked)
                                    }
                                />
                                發車區間
                            </label>
                            <label>
                                <input
                                    type="checkbox"
                                    checked={showPhases}
                                    onChange={(e) =>
                                        setShowPhases(e.target.checked)
                                    }
                                />
                                行情階段
                            </label>
                            <label>
                                <input
                                    type="checkbox"
                                    checked={showWaves}
                                    onChange={(e) =>
                                        setShowWaves(e.target.checked)
                                    }
                                />
                                大小波段
                            </label>
                            <span className="lab-control-spacer" />
                            <label>
                                價格{" "}
                                <select
                                    aria-label="價格顯示口徑"
                                    value={raw ? "raw" : "adjusted"}
                                    onChange={(e) =>
                                        setRaw(e.target.value === "raw")
                                    }
                                >
                                    <option value="adjusted">調整收盤</option>
                                    <option value="raw">原始收盤</option>
                                </select>
                            </label>
                            <label>
                                縱軸{" "}
                                <select
                                    aria-label="價格縱軸"
                                    value={logarithmic ? "log" : "linear"}
                                    onChange={(e) =>
                                        setLogarithmic(e.target.value === "log")
                                    }
                                >
                                    <option value="log">等比例 · 對數</option>
                                    <option value="linear">
                                        等價差 · 線性
                                    </option>
                                </select>
                            </label>
                        </div>
                        {[...new Set(results.flatMap((r) => r.warnings))].map(
                            (warning) => (
                                <p key={warning} className="lab-inline-note">
                                    {warning}
                                </p>
                            ),
                        )}
                        {raw && (
                            <p className="lab-inline-note">
                                原始收盤供核對；方法與漲幅仍使用調整收盤。擬合線暫時隱藏，避免混用兩種價格。
                            </p>
                        )}
                        {results.some((r) => !r.diagnostics.converged) && (
                            <p className="lab-inline-note" role="status">
                                本例有方法尚未數值收斂，線條與標記僅供診斷，不能當作穩定結果。
                            </p>
                        )}
                        {sample.selectedOpportunity && (
                            <p className="lab-inline-note">
                                地圖選定：{sample.selectedOpportunity.start}{" "}
                                開始，
                                {sample.selectedOpportunity.peakDate} 最高；
                                {sample.selectedOpportunity.endConfirmedAt
                                    ? `${sample.selectedOpportunity.endConfirmedAt} 確認結束`
                                    : `尚未確認結束，資料至 ${sample.selectedOpportunity.observedThrough}`}
                                。 發動：
                                {sample.selectedOpportunity.launch?.date ??
                                    "未指定"}
                                。
                                {manualWave && (
                                    <button
                                        onClick={() => {
                                            setSelectedWave(null);
                                            setSelectedLaunch(null);
                                        }}
                                    >
                                        回到地圖選定波段
                                    </button>
                                )}
                            </p>
                        )}
                        {!busy && !error && preferredWave && !wave && (
                            <p className="lab-inline-note" role="status">
                                目前方法與尺度找不到邊界完全相符的選定波段；尚未改選其他波段。
                                可切換方法或尺度，或在下方明確選擇另一波。
                            </p>
                        )}
                        {!busy &&
                            !error &&
                            followingSavedWave &&
                            wave &&
                            !manualLaunch &&
                            !launch &&
                            sample.selectedOpportunity?.launch && (
                                <p className="lab-inline-note" role="status">
                                    目前方法沒有與地圖記錄日期及範圍相符的發動候選；尚未改選其他發動點。
                                </p>
                            )}
                        {busy ? (
                            <div className="lab-loading" role="status">
                                <span className="lab-loading-orbit" />
                                正在對照這段走勢的兩種解釋…
                            </div>
                        ) : error ? (
                            <div className="lab-error" role="alert">
                                {error}
                            </div>
                        ) : (
                            <WaveChart
                                sample={sample}
                                results={results.filter((r) =>
                                    visible.includes(r.method),
                                )}
                                waves={waves}
                                cursor={cursor}
                                onCursor={setCursor}
                                range={range}
                                onRange={setRange}
                                raw={raw}
                                logarithmic={logarithmic}
                                showPhases={showPhases}
                                showLaunches={showLaunches}
                                showWaves={showWaves}
                                selectedLaunch={
                                    launch && activeResult
                                        ? `${activeResult.method}:${launch.id}`
                                        : null
                                }
                                onLaunch={selectLaunch}
                                selectedWave={wave?.id ?? null}
                                onWave={selectWave}
                            />
                        )}
                        <div className="lab-date-bar">
                            <label>
                                觀察日{" "}
                                <input
                                    type="date"
                                    aria-label="波段觀察日"
                                    min={sample.points[0].date}
                                    max={sample.points.at(-1)?.date}
                                    value={point.date}
                                    onChange={(e) => setDate(e.target.value)}
                                />
                            </label>
                            <span>
                                原始 {price(point.raw)} 元 · 調整{" "}
                                {price(point.adjusted)} 元
                            </span>
                            <strong>
                                {phase ? PHASE[phase.phase] : "資料／階段未定"}
                            </strong>
                        </div>
                        <input
                            className="lab-time-slider"
                            type="range"
                            aria-label="波段觀察時間軸"
                            min={0}
                            max={sample.points.length - 1}
                            value={cursor}
                            onChange={(e) => {
                                const i = Number(e.target.value);
                                setCursor(i);
                                if (i < range[0] || i > range[1])
                                    setRange([0, sample.points.length - 1]);
                            }}
                        />
                        {!!point.flags.length && (
                            <p className="lab-inline-note">
                                此日來源標記：{point.flags.join("、")}
                                。跨越缺口的報酬保留未知。
                            </p>
                        )}
                    </section>
                    <section
                        className="lab-metrics"
                        aria-label="起點與漲幅對照"
                    >
                        <div className="surface">
                            <small>本波 → 觀察日</small>
                            <strong>{pct(currentGain)}</strong>
                            <span>
                                {wave
                                    ? `${date(wave.start)} → ${point.date}`
                                    : preferredWave
                                      ? "目前方法與尺度尚未匹配選定波段"
                                      : "本例尚無符合試驗門檻的波段"}
                            </span>
                            <em>
                                {wave && !withinWave
                                    ? "觀察日不在選定波段內"
                                    : "固定波段起點，不隨發車重設"}
                            </em>
                        </div>
                        <div className="surface">
                            <small>發車 → 觀察日</small>
                            <strong>{pct(launchGain)}</strong>
                            <span>
                                {launch
                                    ? `${date(launch.index)} → ${point.date}`
                                    : "沒有可辨識的發車候選"}
                            </span>
                            <em>
                                {wave && !withinWave
                                    ? "觀察日不在選定波段內"
                                    : launch && cursor < launch.index
                                      ? "尚未到所選發車日"
                                      : "依所選方法及候選代表日"}
                            </em>
                        </div>
                        <div className="surface">
                            <small>事後整波最高</small>
                            <strong>{pct(wave?.gain)}</strong>
                            <span>
                                {wave
                                    ? `${date(wave.start)} → ${date(wave.peak)}`
                                    : "保留原始走勢供人工檢視"}
                            </span>
                            <em>
                                {wave?.rightCensored
                                    ? "波段未完結 · 目前觀察到的最高"
                                    : "未計現金股利再投入"}
                            </em>
                        </div>
                    </section>
                    <section className="surface lab-evidence">
                        <div className="lab-section-heading">
                            <div>
                                <span className="eyebrow">LAUNCH EVIDENCE</span>
                                <h2>這個發車標記，說了什麼？</h2>
                                <p>
                                    各項證據分開看；跨尺度一致程度不是成功機率，後段延續也不等於整波成功。
                                </p>
                            </div>
                            <span className="lab-pill">
                                {activeResult
                                    ? METHOD[activeResult.method]
                                    : "尚未選擇"}
                            </span>
                        </div>
                        <div
                            className="lab-candidate-list"
                            aria-label="發車候選清單"
                        >
                            {results
                                .filter((r) => visible.includes(r.method))
                                .flatMap((r) =>
                                    r.launches.map((l) => (
                                        <button
                                            className={
                                                launch?.id === l.id &&
                                                activeResult?.method ===
                                                    r.method
                                                    ? "selected"
                                                    : ""
                                            }
                                            key={`${r.method}:${l.id}`}
                                            onClick={() =>
                                                selectLaunch(l.id, r.method)
                                            }
                                            aria-pressed={
                                                launch?.id === l.id &&
                                                activeResult?.method ===
                                                    r.method
                                            }
                                        >
                                            <small>
                                                {r.method === "segments"
                                                    ? "A"
                                                    : "B"}
                                            </small>
                                            <strong>{date(l.index)}</strong>
                                            <span>{KIND[l.kind]}</span>
                                        </button>
                                    )),
                                )}
                            {!results.some(
                                (r) =>
                                    visible.includes(r.method) &&
                                    r.launches.length,
                            ) && (
                                <p className="lab-empty">
                                    這個尺度沒有清楚的發車候選。行情仍保留，不強迫指定一天。
                                </p>
                            )}
                        </div>
                        {launch && (
                            <>
                                <div className="lab-launch-summary">
                                    <div>
                                        <small>候選發車區間</small>
                                        <strong>
                                            {date(launch.rangeStart)} —{" "}
                                            {date(launch.rangeEnd)}
                                        </strong>
                                        <span>
                                            代表日 {date(launch.index)} ·{" "}
                                            {KIND[launch.kind]}
                                        </span>
                                    </div>
                                    <div>
                                        <small>跨尺度相近候選</small>
                                        <strong>
                                            {launch.support} / 3 尺度
                                        </strong>
                                        <span>
                                            {launch.support >= 3
                                                ? "位置較集中"
                                                : "邊界對尺度敏感"}{" "}
                                            · 非信心機率
                                        </span>
                                    </div>
                                </div>
                                <div className="lab-evidence-grid">
                                    <div>
                                        <small>每交易日上升速度</small>
                                        <b>
                                            {pct(
                                                Math.expm1(launch.preSlope) *
                                                    100,
                                            )}{" "}
                                            →{" "}
                                            {pct(
                                                Math.expm1(launch.postSlope) *
                                                    100,
                                            )}
                                        </b>
                                    </div>
                                    <div>
                                        <small>後段持續觀測</small>
                                        <b>
                                            {launch.sustainSessions}{" "}
                                            個交易日間隔
                                        </b>
                                    </div>
                                    <div>
                                        <small>速度變化 ÷ 日常波動</small>
                                        <b>
                                            {launch.relativeStrength == null
                                                ? "未知"
                                                : `${launch.relativeStrength.toFixed(2)} 倍`}
                                        </b>
                                    </div>
                                    <div>
                                        <small>後段起訖漲幅</small>
                                        <b>{pct(launch.forwardGain)}</b>
                                        <span>
                                            {date(launch.index)} →{" "}
                                            {date(launch.forwardEnd)}
                                        </span>
                                    </div>
                                    <div>
                                        <small>後段最大回撤</small>
                                        <b>
                                            {launch.drawdown == null
                                                ? "未知"
                                                : `${launch.drawdown.toFixed(1)}%`}
                                        </b>
                                    </div>
                                    <div>
                                        <small>後段描述</small>
                                        <b>{OUTCOME[launch.outcome]}</b>
                                        <span>以後段末漲幅 +5% 作試驗分界</span>
                                    </div>
                                </div>
                            </>
                        )}
                        <details>
                            <summary>查看大小波段與結束確認</summary>
                            <p>
                                試驗收錄門檻為整波 +60%；回撤尺度{" "}
                                {scale === "fine"
                                    ? "15% / 30%"
                                    : scale === "balanced"
                                      ? "25% / 40%"
                                      : "35% / 50%"}
                                。這些是可比較設定，尚未定案。點選一波會固定其起點作為上方比較基準。父子以起點至結束確認的完整區間判定；截尾可能來自案例邊界、缺值或跳價，起點不是確定的真實起漲日。
                            </p>
                            <div className="lab-wave-table">
                                <table>
                                    <thead>
                                        <tr>
                                            <th>尺度</th>
                                            <th>起點 → 最高點</th>
                                            <th>最高漲幅</th>
                                            <th>結束確認</th>
                                            <th>邊界</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {waves.map((w) => (
                                            <tr
                                                key={w.id}
                                                className={
                                                    wave?.id === w.id
                                                        ? "selected"
                                                        : ""
                                                }
                                            >
                                                <td>
                                                    <button
                                                        onClick={() =>
                                                            selectWave(w.id)
                                                        }
                                                    >
                                                        {w.scale === "large"
                                                            ? "大波"
                                                            : "小波"}
                                                        {w.parentId
                                                            ? " · 子波"
                                                            : ""}
                                                    </button>
                                                </td>
                                                <td>
                                                    {date(w.start)} →{" "}
                                                    {date(w.peak)}
                                                </td>
                                                <td>{pct(w.gain)}</td>
                                                <td>
                                                    {w.end == null
                                                        ? "未確認"
                                                        : date(w.end)}
                                                </td>
                                                <td>
                                                    {w.leftCensored
                                                        ? "起點可能截斷"
                                                        : ""}
                                                    {w.rightCensored
                                                        ? " · 未完結"
                                                        : ""}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                                {!waves.length && (
                                    <p>
                                        沒有達到本次試驗收錄門檻的波段；發車候選仍獨立保留。
                                    </p>
                                )}
                            </div>
                        </details>
                    </section>
                    <section
                        className="surface lab-feedback"
                        aria-label="我的波段評註"
                    >
                        <div className="lab-section-heading">
                            <div>
                                <span className="eyebrow">YOUR READING</span>
                                <h2>你眼中的發車，在哪裡？</h2>
                                <p>
                                    移動圖上游標設定區間，留下你覺得太早、太晚或不合理的地方。
                                </p>
                            </div>
                            <span className="lab-pill">僅存在此瀏覽器</span>
                        </div>
                        <div className="lab-annotation-actions">
                            <button
                                className="lab-secondary"
                                disabled={!currentFeedbackKey}
                                onClick={() =>
                                    changeFeedback({ start: cursor })
                                }
                            >
                                以 {point.date} 為標記起點
                            </button>
                            <button
                                className="lab-secondary"
                                disabled={!currentFeedbackKey}
                                onClick={() => changeFeedback({ end: cursor })}
                            >
                                以此日為標記終點
                            </button>
                            <span>
                                {note.start == null
                                    ? "尚未標記"
                                    : date(note.start)}{" "}
                                →{" "}
                                {note.end == null ? "尚未標記" : date(note.end)}
                            </span>
                            <button
                                className="lab-text-button"
                                disabled={!currentFeedbackKey}
                                onClick={() =>
                                    changeFeedback({ start: null, end: null })
                                }
                            >
                                清除區間
                            </button>
                        </div>
                        {note.start != null &&
                            note.end != null &&
                            note.end < note.start && (
                                <p className="lab-inline-note">
                                    終點早於起點，請重新指定。
                                </p>
                            )}
                        <div className="lab-feedback-form">
                            <label>
                                你的判斷
                                <select
                                    aria-label="標記評價"
                                    disabled={!currentFeedbackKey}
                                    value={note.verdict}
                                    onChange={(e) =>
                                        changeFeedback({
                                            verdict: e.target.value,
                                        })
                                    }
                                >
                                    {[
                                        "尚未評註",
                                        "大致符合",
                                        "發車太早",
                                        "發車太晚",
                                        "切得太碎",
                                        "漏掉一波",
                                        "不應有發車",
                                        "其他意見",
                                    ].map((v) => (
                                        <option key={v}>{v}</option>
                                    ))}
                                </select>
                            </label>
                            <label>
                                想調整的地方
                                <textarea
                                    aria-label="波段評註"
                                    disabled={!currentFeedbackKey}
                                    value={note.note}
                                    onChange={(e) =>
                                        changeFeedback({ note: e.target.value })
                                    }
                                    placeholder="例如：這裡只是反彈，我認為要到下一段才算再次啟動。"
                                    rows={3}
                                />
                            </label>
                        </div>
                        <p className="lab-save-state">
                            {currentIdentityError ||
                                (!currentFeedbackKey &&
                                    "正在核對案例內容，完成後才會讀取及保存本例評註。") ||
                                storageError ||
                                "評註自動保存在本機瀏覽器；下載本次查證可將價格、方法結果與評註一起留存。"}
                        </p>
                    </section>
                    <section className="surface lab-data">
                        <details>
                            <summary>逐日價格與計算依據 · {point.date}</summary>
                            <p>
                                表格跟隨游標；原始價與調整價均來自同一份案例。點選日期可查看當日。
                            </p>
                            <div className="lab-wave-table">
                                <table>
                                    <thead>
                                        <tr>
                                            <th>日期</th>
                                            <th>原始收盤</th>
                                            <th>調整收盤</th>
                                            <th>來源標記</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {sample.points
                                            .slice(sliceStart, sliceStart + 9)
                                            .map((p, i) => (
                                                <tr
                                                    key={p.date}
                                                    className={
                                                        sliceStart + i ===
                                                        cursor
                                                            ? "selected"
                                                            : ""
                                                    }
                                                >
                                                    <td>
                                                        <button
                                                            onClick={() =>
                                                                setCursor(
                                                                    sliceStart +
                                                                        i,
                                                                )
                                                            }
                                                        >
                                                            {p.date}
                                                        </button>
                                                    </td>
                                                    <td>{price(p.raw)}</td>
                                                    <td>{price(p.adjusted)}</td>
                                                    <td>
                                                        {p.flags.join("、") ||
                                                            (p.adjusted == null
                                                                ? "缺報價"
                                                                : "—")}
                                                    </td>
                                                </tr>
                                            ))}
                                    </tbody>
                                </table>
                            </div>
                        </details>
                        <details>
                            <summary>資料來源、範圍與試驗方法</summary>
                            <dl>
                                <dt>價格來源</dt>
                                <dd>
                                    {sample.kind === "synthetic"
                                        ? "互動示意用的模擬價格"
                                        : "已保存的歷史價格"}
                                </dd>
                                <dt>本例範圍</dt>
                                <dd>
                                    {sample.source.from} → {sample.source.to}
                                </dd>
                                <dt>價格如何計算</dt>
                                <dd>
                                    {priceExplanation(sample.source.priceBasis)}
                                </dd>
                            </dl>
                            <ul>
                                {sample.source.limitations.map((l) => (
                                    <li key={l}>{l}</li>
                                ))}
                            </ul>
                            <p>
                                新版全量目標是 2010
                                年起的本機可用歷史。本比較台先使用已保存的少量案例，尚未完成早年公司行動、下市與分類覆蓋核對。
                            </p>
                            <p>
                                A 使用帶切段代價的最小平方分段直線；B
                                使用一階趨勢濾波。兩者以調整後對數價格計算，不要求固定天數內翻倍。各尺度的發車區間是一致程度描述，不是統計信賴區間。只有收盤價時不宣稱識別了開盤跳空。
                            </p>
                            <p>
                                方法資料：
                                <a
                                    href="https://arxiv.org/abs/1304.2986"
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    趨勢濾波
                                </a>{" "}
                                ·{" "}
                                <a
                                    href="https://arxiv.org/abs/1101.1438"
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    變化點分析（本版 A 未使用 PELT）
                                </a>
                            </p>
                            {results.map((r) => (
                                <p key={r.method}>
                                    {METHOD[r.method]}：
                                    {r.diagnostics.converged
                                        ? "數值求解完成"
                                        : "尚未收斂，僅供診斷"}
                                    ；{r.diagnostics.iterations} 次迭代。
                                    {r.warnings.join("；")}
                                </p>
                            ))}
                        </details>
                    </section>
                </div>
            </div>
        </div>
    );
}
