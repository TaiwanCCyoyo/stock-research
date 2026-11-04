import { useId, useState } from "react";
import { CELLS, GROUP_LABELS, casePage, currentSelection } from "./model.ts";
import type {
    CaseFilter,
    CaseRequest,
    Horizon,
    QuestionRequest,
    ReadState,
    Selection,
    Summary,
} from "./model.ts";
import "./comparison.css";
import { L1Evidence, L1Provenance } from "./L1Evidence";

export interface ConditionComparisonProps {
    state: ReadState;
    selection?: Selection;
    onSelectionChange: (selection: Selection) => void;
    onOpenCase?: (request: CaseRequest) => void;
    onDiscuss?: (request: QuestionRequest) => void;
    onRetry?: () => void;
}
const labels = {
    hit: "成功（hit）",
    loss: "下跌（loss）",
    "flat-win": "未命中（flat-win）",
    unknown: "未知（unknown）",
};
function Statistics({ summary }: { summary?: Summary }) {
    if (!summary?.counts) return <p>尚未評估</p>;
    const n = (value?: number) =>
        value === undefined ? "缺欄位" : value.toLocaleString("zh-TW");
    return (
        <>
            {summary.status === "not-evaluated" && (
                <p>
                    尚未評估 · {summary.reason}
                    。以下為保存計數，不代表研究結論。
                </p>
            )}
            <dl className="cc-counts">
                <div>
                    <dt>命中 / 已知分母</dt>
                    <dd>
                        {n(summary.counts.hit)} / {n(summary.counts.known)}
                    </dd>
                </div>
                <div>
                    <dt>股票數</dt>
                    <dd>{n(summary.counts.stocks)}</dd>
                </div>
                <div>
                    <dt>未知 unknown</dt>
                    <dd>{n(summary.counts.unknown)}</dd>
                </div>
                <div>
                    <dt>觀察不足 censored</dt>
                    <dd>{n(summary.counts.censored)}</dd>
                </div>
            </dl>
            {summary.saved && (
                <>
                    <p>
                        事件數：{summary.saved.event_n}；命中率：
                        {summary.saved.hit_rate === null
                            ? "無分母（null）"
                            : `${(summary.saved.hit_rate * 100).toFixed(2)}%`}
                    </p>
                    <details>
                        <summary>保存的完整計數、界限與分母</summary>
                        <pre>{JSON.stringify(summary.saved, null, 2)}</pre>
                    </details>
                </>
            )}
        </>
    );
}
export function ConditionComparison(props: ConditionComparisonProps) {
    const id = useId();
    const [draft, setDraft] = useState({ resultId: "", text: "" });
    if (props.state.status === "loading")
        return (
            <section className="condition-comparison" aria-busy="true">
                <p role="status">正在讀取保存的比較…</p>
            </section>
        );
    if (props.state.status === "error")
        return (
            <section className="condition-comparison">
                <p role="alert">讀取失敗：{props.state.message}</p>
                {props.onRetry && (
                    <button onClick={props.onRetry}>重試讀取</button>
                )}
            </section>
        );
    const view = props.state.value;
    const question = draft.resultId === view.id ? draft.text : "";
    const selection = currentSelection(view, props.selection);
    const window = view.windows[selection.horizon];
    const page = casePage(window, selection);
    const update = (patch: Partial<Selection>) =>
        props.onSelectionChange({
            ...selection,
            page: 0,
            eventId: undefined,
            ...patch,
        });
    return (
        <section
            className="condition-comparison"
            aria-labelledby={`${id}-title`}
        >
            <h2 id={`${id}-title`}>保存的條件比較</h2>
            {view.producer && (
                <p className="cc-warning">
                    範圍：{view.producer.scope}；
                    {view.producer.scope === "full"
                        ? "僅歷史描述，非策略批准"
                        : "尚未完成正式研究評估"}
                    。股票數不可跨格相加，已選股票可包含零事件股票。
                </p>
            )}
            {view.synthetic && (
                <p className="cc-warning" role="note">
                    <strong>合成展示資料 — 非研究結果、非選股建議。</strong>{" "}
                    數字與個案只供操作測試。
                </p>
            )}
            <p>
                同一批固定冷卻突破事件，交叉比較事前量縮與當日放量；保留全部四格與共同對照。
            </p>
            <p>
                事前量縮：VOL_a prior10 / prior60 ≤ 0.7；當日放量：G today /
                prior20 ≥ 1.5。
            </p>
            <label htmlFor={`${id}-horizon`}>觀察視窗 </label>
            <select
                id={`${id}-horizon`}
                value={selection.horizon}
                onChange={(e) =>
                    update({ horizon: Number(e.target.value) as Horizon })
                }
            >
                <option value={126}>H126</option>
                <option value={252}>H252</option>
            </select>
            <p role="status">
                目前 H{selection.horizon}
                ；各視窗使用各自保存的分母，不跨視窗相加。
            </p>
            <p>
                命中 / 已知分母沿用保存結果的資格規則。unknown 與 censored
                可能重疊，不能相加；未評估不等於零。
            </p>
            <article className="cc-card">
                <h3>共同母體 A</h3>
                <Statistics summary={window?.all} />
                <button
                    data-comparison-group="all"
                    aria-pressed={selection.group === "all"}
                    onClick={() => update({ group: "all" })}
                >
                    {view.producer ? "檢視共同母體" : "查看共同母體個案"}
                </button>
            </article>
            <div className="cc-grid">
                {CELLS.map((cell) => (
                    <article className="cc-card" key={cell}>
                        <h3>{GROUP_LABELS[cell]}</h3>
                        <Statistics summary={window?.cells[cell]} />
                        <details>
                            <summary>對照：其餘母體 A∖B（排除此格）</summary>
                            <Statistics summary={window?.complements[cell]} />
                        </details>
                        <button
                            data-comparison-group={cell}
                            aria-pressed={selection.group === cell}
                            onClick={() => update({ group: cell })}
                        >
                            查看{GROUP_LABELS[cell]}
                            {view.producer ? "追溯指標" : "個案"}
                        </button>
                    </article>
                ))}
            </div>
            {view.producer && window && (
                <L1Evidence window={window} selection={selection} />
            )}
            {!view.producer && (
                <>
                    <h3>個案：{GROUP_LABELS[selection.group]}</h3>
                    <p>{window?.caseCoverage ?? "此視窗尚無保存結果"}</p>
                    <div className="cc-controls">
                        <label>
                            結果{" "}
                            <select
                                value={selection.filter}
                                onChange={(e) =>
                                    update({
                                        filter: e.target.value as CaseFilter,
                                    })
                                }
                            >
                                <option value="all">全部</option>
                                <option value="hit">成功（hit）</option>
                                <option value="not-hit">
                                    未成功（loss / flat-win）
                                </option>
                                <option value="unknown">未知</option>
                            </select>
                        </label>
                        <label>
                            排序{" "}
                            <select
                                value={selection.sort}
                                onChange={(e) =>
                                    update({
                                        sort: e.target
                                            .value as Selection["sort"],
                                    })
                                }
                            >
                                <option value="date-desc">
                                    事件日期：新到舊
                                </option>
                                <option value="date-asc">
                                    事件日期：舊到新
                                </option>
                            </select>
                        </label>
                    </div>
                    <p>
                        同日依事件 ID
                        排序；未成功包含下跌與未達目標，未知不算失敗。個案清單不拿來重算上方統計。
                    </p>
                    {page.total === 0 ? (
                        <p role="status">
                            此選取沒有可讀個案；不表示事件數為零。
                        </p>
                    ) : (
                        <ol className="cc-cases" start={page.page * 5 + 1}>
                            {page.rows.map((item) => (
                                <li
                                    key={item.eventId}
                                    aria-current={
                                        selection.eventId === item.eventId
                                            ? "true"
                                            : undefined
                                    }
                                >
                                    <strong>
                                        {item.securityId} · {item.date}
                                    </strong>
                                    <p>
                                        {labels[item.effectiveLabel]} ·{" "}
                                        {item.eventMainEligible
                                            ? "納入主分母"
                                            : "未納入主分母"}{" "}
                                        ·{" "}
                                        {item.censored
                                            ? "觀察不足"
                                            : "觀察完整"}
                                    </p>
                                    <p>
                                        {item.reasons.join("；") ||
                                            "無附加原因"}
                                    </p>
                                    {item.readerRef && props.onOpenCase ? (
                                        <button
                                            data-comparison-event={item.eventId}
                                            onClick={() => {
                                                const next = {
                                                    ...selection,
                                                    page: page.page,
                                                    eventId: item.eventId,
                                                };
                                                props.onSelectionChange(next);
                                                props.onOpenCase?.({
                                                    source: view.source,
                                                    synthetic: view.synthetic,
                                                    selection: next,
                                                    item,
                                                    readerRef: item.readerRef!,
                                                });
                                            }}
                                        >
                                            查看個案 {item.securityId}
                                        </button>
                                    ) : (
                                        <span>個案 reader 尚未提供</span>
                                    )}
                                </li>
                            ))}
                        </ol>
                    )}
                    <nav aria-label="個案分頁" className="cc-controls">
                        <button
                            disabled={page.page === 0}
                            onClick={() => update({ page: page.page - 1 })}
                        >
                            上一頁
                        </button>
                        <span>
                            第 {page.page + 1} / {page.pages} 頁 · 清單{" "}
                            {page.total} 筆
                        </span>
                        <button
                            disabled={page.page + 1 === page.pages}
                            onClick={() => update({ page: page.page + 1 })}
                        >
                            下一頁
                        </button>
                    </nav>
                </>
            )}
            {view.producer && <L1Provenance producer={view.producer} />}
            <details>
                <summary>來源與設定</summary>
                <dl>
                    {Object.entries(view.source).map(([key, value]) => (
                        <div key={key}>
                            <dt>{key}</dt>
                            <dd>{value}</dd>
                        </div>
                    ))}
                </dl>
            </details>
            <form
                onSubmit={(e) => {
                    e.preventDefault();
                    if (question.trim())
                        props.onDiscuss?.({
                            source: view.source,
                            synthetic: view.synthetic,
                            selection,
                            question: question.trim(),
                            intent: "discussion-only",
                            producer: view.producer,
                        });
                }}
            >
                <label htmlFor={`${id}-question`}>仍未回答的問題</label>
                <textarea
                    id={`${id}-question`}
                    value={question}
                    onChange={(e) =>
                        setDraft({ resultId: view.id, text: e.target.value })
                    }
                />
                <p>
                    只把問題、來源及設定版本帶入討論，不代表批准研究，也不啟動計算。
                </p>
                <button disabled={!props.onDiscuss || !question.trim()}>
                    帶來源討論下一步
                </button>
            </form>
        </section>
    );
}
