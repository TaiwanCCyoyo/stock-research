import { useEffect, useMemo, useState } from "react";
import { useStudioTrade } from "../../api/strategyStudio";
import type { StudioRun } from "../../domain/strategies/types";
import { TradeCandles } from "./StrategyCharts";
import { fillLabel, tradeMarks, validCandles } from "./auditModel";
import { money, percentage } from "./format";
import { walkthroughTrades, type WalkthroughRole } from "./model";
import { StudioState } from "./shared";

const stages = [
    { title: "挑股票", description: "看決定日晚上的候選名單" },
    { title: "試單", description: "先買小量，看看能否跟上" },
    { title: "加碼", description: "上漲達條件後再增加部位" },
    { title: "賣出", description: "依出場規則，結束這筆持有" },
];
const roleLabels: Record<WalkthroughRole, string> = {
    only: "唯一示範",
    best: "最賺",
    median: "中間值",
    worst: "最賠",
};
export function StrategyWalkthrough({
    run,
    onAudit,
}: {
    run: StudioRun;
    onAudit: (id: string) => void;
}) {
    const picks = useMemo(
        () => walkthroughTrades(run.positions),
        [run.positions],
    );
    const [selection, setSelection] = useState(0),
        [step, setStep] = useState(0),
        [playing, setPlaying] = useState(false);
    const activeSelection = selection < picks.length ? selection : 0;
    const picked = picks[activeSelection];
    const resource = useStudioTrade(run.id, picked?.trade.id ?? null),
        trade = resource.data;
    useEffect(() => {
        if (!playing) return;
        const timer = window.setTimeout(() => {
            if (step >= 3) setPlaying(false);
            else setStep((value) => value + 1);
        }, 2500);
        return () => window.clearTimeout(timer);
    }, [playing, step]);
    const entry = trade?.fills.find((fill) => fill.action === "BUY");
    const add = trade?.fills.find(
        (fill) =>
            fill.action === "BUY" &&
            (fill.kind === "add" || fill.kind === "retry"),
    );
    const sell = trade?.fills.findLast((fill) => fill.action === "SELL");
    const through = !entry
        ? null
        : step === 0
          ? (entry.decisionDate ?? entry.date)
          : step === 1
            ? entry.date
            : step === 2
              ? (add?.date ?? entry.date)
              : null;
    return (
        <section className="ss-card">
            <h2>用一筆實際回測交易，看懂策略</h2>
            <p className="ss-muted">
                每一步都有保存的成交或決策紀錄。按播放，或直接選一個步驟。
            </p>
            <p className="ss-small ss-muted">
                {picks.length === 0
                    ? "四步示範需要候選、試單、加碼與賣出的完整紀錄。"
                    : picks.length === 1
                      ? "目前只有一筆四步紀錄完整的交易，以下呈現這筆唯一示範。"
                      : picks.length === 2
                        ? "目前有兩筆四步紀錄完整的交易，依整筆損益呈現最賺與最賠。"
                        : "從四步紀錄完整的交易中，依整筆損益選出最賺、中間順位與最賠。"}
            </p>
            {!picks.length ? (
                <p className="ss-warning">
                    這份研究沒有保存同時含候選、試單、加碼與賣出的完整交易，不能編造四步示範。
                </p>
            ) : (
                <>
                    <div
                        className="ss-pills"
                        role="group"
                        aria-label="示範交易選擇"
                    >
                        {picks.map((pick, index) => (
                            <button
                                className="ss-chip"
                                key={pick.trade.id}
                                aria-pressed={activeSelection === index}
                                onClick={() => {
                                    setSelection(index);
                                    setStep(0);
                                    setPlaying(false);
                                }}
                            >
                                {roleLabels[pick.role]} · {pick.trade.name}
                            </button>
                        ))}
                    </div>
                    <div className="ss-walk">
                        <div className="ss-steps">
                            {stages.map((stage, index) => (
                                <button
                                    className="ss-step"
                                    key={stage.title}
                                    aria-current={
                                        step === index ? "step" : undefined
                                    }
                                    onClick={() => {
                                        setStep(index);
                                        setPlaying(false);
                                    }}
                                >
                                    <small>第 {index + 1} 步</small>
                                    <strong>{stage.title}</strong>
                                    <span className="ss-small">
                                        {stage.description}
                                    </span>
                                </button>
                            ))}
                        </div>
                        <div className="ss-stage">
                            {!trade ? (
                                <StudioState {...resource} />
                            ) : (
                                <>
                                    <TradeCandles
                                        candles={validCandles(trade.candles)}
                                        marks={tradeMarks(trade)}
                                        through={through}
                                        threshold={
                                            step === 2 && entry?.price
                                                ? entry.price * 1.1
                                                : null
                                        }
                                    />
                                    <div className="ss-stage-text">
                                        {step === 0 && (
                                            <>
                                                <b>
                                                    {entry?.decisionDate ??
                                                        "決定日期未保存"}{" "}
                                                    晚上
                                                </b>
                                                <p>
                                                    從保存的前段候選中，檢查一張是否買得起。
                                                </p>
                                                <div className="ss-candidates">
                                                    {entry?.entryCandidates?.map(
                                                        (candidate) => (
                                                            <span
                                                                key={
                                                                    candidate.code
                                                                }
                                                                className={
                                                                    candidate.affordability.includes(
                                                                        "unaffordable",
                                                                    )
                                                                        ? "ss-unaffordable"
                                                                        : ""
                                                                }
                                                            >
                                                                {candidate.code}
                                                                {candidate.code ===
                                                                trade.code
                                                                    ? ` ${trade.name}`
                                                                    : ""}{" "}
                                                                ·{" "}
                                                                {candidate.affordability.includes(
                                                                    "unaffordable",
                                                                )
                                                                    ? "一張買不起"
                                                                    : candidate.affordability.includes(
                                                                            "affordable",
                                                                        )
                                                                      ? "一張買得起"
                                                                      : "可負擔性未知"}
                                                            </span>
                                                        ),
                                                    )}
                                                </div>
                                            </>
                                        )}
                                        {step === 1 && (
                                            <>
                                                <b>
                                                    {entry?.date}{" "}
                                                    {entry
                                                        ? fillLabel(entry)
                                                        : "試單"}
                                                </b>
                                                <p>
                                                    {entry?.quantity?.toLocaleString()}{" "}
                                                    股 · 成交{" "}
                                                    {entry?.price ?? "未知"} 元
                                                    · 現金支出{" "}
                                                    {money(
                                                        entry?.cashFlow == null
                                                            ? null
                                                            : -entry.cashFlow,
                                                        true,
                                                    )}
                                                    。
                                                </p>
                                            </>
                                        )}
                                        {step === 2 &&
                                            (add ? (
                                                <>
                                                    <b>
                                                        {add.decisionDate ??
                                                            "決定日期未保存"}{" "}
                                                        決定加碼
                                                    </b>
                                                    <p>
                                                        {add.addSignal
                                                            ?.economicReturn ==
                                                        null
                                                            ? "沒有保存這筆加碼條件的核對紀錄，無法逐筆確認。"
                                                            : `原紀錄的經濟報酬 ${percentage(add.addSignal.economicReturn)}，包含公司權益；一般加碼門檻是 +10%。`}{" "}
                                                        {add.date}{" "}
                                                        {add.retry
                                                            ? "重試加碼"
                                                            : "加碼"}{" "}
                                                        {add.quantity?.toLocaleString()}{" "}
                                                        股，成交{" "}
                                                        {add.price ?? "未知"}{" "}
                                                        元。
                                                        {add.retry &&
                                                            " 這是先前加碼單的重試，須連同原訂單條件看待。"}
                                                    </p>
                                                    <small className="ss-muted">
                                                        日 K
                                                        線是不含權益的股價；虛線只是試單價＋10%的價格參考，不能當作實際觸發價。
                                                    </small>
                                                </>
                                            ) : (
                                                <p>這筆沒有加碼紀錄。</p>
                                            ))}
                                        {step === 3 && (
                                            <>
                                                <b>
                                                    {sell?.decisionDate ??
                                                        "決定日期未保存"}{" "}
                                                    決定賣出
                                                </b>
                                                <p>
                                                    {sell?.dailyRank != null
                                                        ? `當日持股排名第 ${sell.dailyRank} 名。`
                                                        : "依規則應退出，但沒有保存當日排名，無法逐筆確認。"}{" "}
                                                    {sell?.date} 成交{" "}
                                                    {sell?.price ?? "未知"}{" "}
                                                    元；整筆損益{" "}
                                                    <span
                                                        className={
                                                            trade.pnl !==
                                                                null &&
                                                            trade.pnl > 0
                                                                ? "ss-gain"
                                                                : "ss-loss"
                                                        }
                                                    >
                                                        {money(trade.pnl)}（
                                                        {percentage(
                                                            trade.return,
                                                        )}
                                                        ）
                                                    </span>
                                                    。
                                                </p>
                                            </>
                                        )}
                                    </div>
                                </>
                            )}
                            <div className="ss-pills">
                                <button
                                    className="ss-button ss-button-primary"
                                    disabled={!trade}
                                    onClick={() => {
                                        if (!playing && step === 3) setStep(0);
                                        setPlaying((value) => !value);
                                    }}
                                >
                                    {playing ? "暫停" : "▶ 播放"}
                                </button>
                                <button
                                    className="ss-button"
                                    disabled={step === 0}
                                    onClick={() => {
                                        setPlaying(false);
                                        setStep((value) =>
                                            Math.max(0, value - 1),
                                        );
                                    }}
                                >
                                    上一步
                                </button>
                                <button
                                    className="ss-button"
                                    disabled={step === 3}
                                    onClick={() => {
                                        setPlaying(false);
                                        setStep((value) =>
                                            Math.min(3, value + 1),
                                        );
                                    }}
                                >
                                    下一步
                                </button>
                                <button
                                    className="ss-button"
                                    onClick={() => {
                                        setPlaying(false);
                                        if (picked) onAudit(picked.trade.id);
                                    }}
                                >
                                    完整交易明細
                                </button>
                            </div>
                        </div>
                    </div>
                </>
            )}
            <details>
                <summary>研究用的原始規則</summary>
                <ol>
                    {run.method.rules.map((rule, index) => (
                        <li key={index}>{rule}</li>
                    ))}
                </ol>
            </details>
        </section>
    );
}
