import { useEffect, useMemo, useState } from "react";
import { readArtifact } from "../../api/artifacts";
import { validateResearchBundle } from "../../domain/opportunities/research.ts";
import type {
    SavedResearchBundle,
    SavedResearchRun,
} from "../../domain/opportunities/research.ts";
import { ResearchPage } from "./ResearchPage";
import { eventLabel, researchName, researchText } from "./researchDisplay";
import "../opportunities/OpportunityPage.css";
import "./ResearchLibraryPage.css";
import { currencyMoney } from "../strategies/format";

const number = (v: number) =>
    v.toLocaleString("zh-TW", { maximumFractionDigits: 2 });
const status = {
    exploratory: "研究中，尚未採用",
    failed: "已淘汰",
    incomplete: "檢查未完成",
    accepted: "已接受 · 查看適用條件",
};

export function ResearchLibraryPage() {
    const [data, setData] = useState<SavedResearchBundle | null>(null),
        [error, setError] = useState(""),
        [id, setId] = useState("");
    const [legacy, setLegacy] = useState(false);
    useEffect(() => {
        const control = new AbortController();
        readArtifact("saved-research-runs", control.signal)
            .then((value) => {
                setData(validateResearchBundle(value));
            })
            .catch((e) => {
                if (e.name !== "AbortError") setError(e.message);
            });
        return () => control.abort();
    }, []);
    const run = data?.runs.find((r) => r.id === id) ?? data?.runs[0];
    return (
        <div className="op-page research-library">
            {data?.runs.some(
                (run) => run.method.parameters.synthetic === true,
            ) && (
                <p className="op-notice">
                    合成示範：帳戶、價格與交易均為虛構，不代表真實研究結果。
                </p>
            )}
            <section className="op-hero">
                <div>
                    <h1>策略研究</h1>
                    <p>
                        查看每個策略的規則、帳戶淨值與每筆交易，也保留已淘汰策略的研究結果。
                    </p>
                </div>
                <span className="op-badge">已保存結果 · 未重新執行策略</span>
            </section>
            {error && <p className="op-notice">{error}</p>}
            {!data && !error && <p role="status">正在讀取已保存的研究…</p>}
            {data && (
                <div className="research-run-choices">
                    {data.runs.map((r) => (
                        <button
                            key={r.id}
                            aria-pressed={r.id === run?.id}
                            onClick={() => setId(r.id)}
                        >
                            <small>{status[r.method.status]}</small>
                            <strong>{researchName(r.name)}</strong>
                            <span>
                                {(r.netReturn * 100).toFixed(2)}%{" "}
                                <small>整段累積淨報酬</small>
                            </span>
                            <small>
                                {r.from} — {r.through}
                            </small>
                        </button>
                    ))}
                </div>
            )}
            {run && <SavedRun key={run.id} run={run} />}
            <details className="op-card op-provenance-details research-tools">
                <summary>研究者工具</summary>
                {run && data && (
                    <section>
                        <h2>資料來源與版本</h2>
                        <p>
                            快照 {data.asOf}
                            ；下方檔案指紋用來核對保存版本。核對輸出不等於重新驗證策略。
                        </p>
                        {data.sources
                            .filter((s) => run.sourceIds.includes(s.id))
                            .map((s) => (
                                <div key={s.id}>
                                    <strong>{s.label}</strong>
                                    <code>{s.path}</code>
                                    <code>{s.hash}</code>
                                </div>
                            ))}
                    </section>
                )}
                <div>
                    <button
                        onClick={() => setLegacy((v) => !v)}
                        aria-expanded={legacy}
                    >
                        {legacy ? "收起" : "開啟"}舊研究 API 查詢器
                    </button>
                    <p className="op-footnote">
                        查詢原有研究任務，需要啟動本機研究
                        API；其中也可能包含範例或功能測試任務。
                    </p>
                </div>
                {legacy && <ResearchPage />}
            </details>
        </div>
    );
}

function SavedRun({ run }: { run: SavedResearchRun }) {
    const [cursor, setCursor] = useState(run.nav.length - 1),
        [query, setQuery] = useState(""),
        [kind, setKind] = useState("all"),
        [page, setPage] = useState(0),
        [eventId, setEventId] = useState<string | null>(null);
    const [onlyDate, setOnlyDate] = useState(false);
    const point = run.nav[cursor];
    const events = useMemo(
        () =>
            run.events.filter(
                (e) =>
                    (kind === "all" || e.action === kind) &&
                    `${e.code ?? ""} ${e.id} ${e.date}`.includes(query) &&
                    (!onlyDate || e.date.slice(0, 10) === point.date),
            ),
        [run, kind, query, onlyDate, point.date],
    );
    const pageCount = Math.max(1, Math.ceil(events.length / 20));
    const event = run.events.find((e) => e.id === eventId);
    const min = Math.min(run.initialCapital, ...run.nav.map((p) => p.equity)),
        max = Math.max(...run.nav.map((p) => p.equity));
    const xy = (i: number) => ({
        x: 55 + (i / Math.max(1, run.nav.length - 1)) * 865,
        y: 230 - ((run.nav[i].equity - min) / (max - min || 1)) * 195,
    });
    const line = run.nav
        .map((_, i) => `${i ? "L" : "M"}${xy(i).x},${xy(i).y}`)
        .join(" ");
    const selected = xy(cursor);
    const filter = (callback: () => void) => {
        callback();
        setPage(0);
    };
    return (
        <>
            <section className="op-card research-run-method">
                <div className="op-section-title">
                    <h2>{researchName(run.name)}</h2>
                    <span className={`research-status ${run.method.status}`}>
                        {status[run.method.status]}
                    </span>
                </div>
                <p>{researchText(run.method.conclusion)}</p>
                <ol>
                    {run.method.rules.map((r, i) => (
                        <li key={i}>{researchText(r)}</li>
                    ))}
                </ol>
                <details>
                    <summary>研究限制</summary>
                    <ul>
                        {[
                            ...new Set([
                                ...run.limitations,
                                ...run.method.limitations,
                            ]),
                        ].map((l, i) => (
                            <li key={i}>{researchText(l)}</li>
                        ))}
                    </ul>
                </details>
            </section>
            <section className="op-card research-nav-card">
                <div className="op-section-title">
                    <div>
                        <h2>帳戶淨值走勢</h2>
                    </div>
                    <div className="research-nav-value">
                        <strong>
                            {currencyMoney(point.equity, run.currency)}
                        </strong>
                        <small>
                            {point.date} · 相對起始{" "}
                            {(
                                100 *
                                (point.equity / run.initialCapital - 1)
                            ).toFixed(2)}
                            %
                        </small>
                    </div>
                </div>
                <svg
                    viewBox="0 0 950 270"
                    role="img"
                    aria-label={`${researchName(run.name)} ${run.from} 至 ${run.through} 的帳戶淨值`}
                    onPointerDown={(e) => {
                        const b = e.currentTarget.getBoundingClientRect();
                        setCursor(
                            Math.max(
                                0,
                                Math.min(
                                    run.nav.length - 1,
                                    Math.round(
                                        ((((e.clientX - b.left) / b.width) *
                                            950 -
                                            55) /
                                            865) *
                                            (run.nav.length - 1),
                                    ),
                                ),
                            ),
                        );
                        setPage(0);
                    }}
                >
                    {[0, 0.5, 1].map((t) => (
                        <g key={t}>
                            <line
                                x1="55"
                                x2="920"
                                y1={230 - 195 * t}
                                y2={230 - 195 * t}
                                stroke="var(--line)"
                            />
                            <text x="50" y={234 - 195 * t} textAnchor="end">
                                {((min + (max - min) * t) / 10000).toFixed(0)}萬
                            </text>
                        </g>
                    ))}
                    <path
                        d={`${line}L920,230L55,230Z`}
                        fill="var(--accent-soft)"
                        opacity=".6"
                    />
                    <path
                        d={line}
                        stroke="var(--accent)"
                        fill="none"
                        strokeWidth="2"
                    />
                    <line
                        x1={selected.x}
                        x2={selected.x}
                        y1="25"
                        y2="235"
                        stroke="var(--accent)"
                        strokeDasharray="3 3"
                    />
                    <circle
                        cx={selected.x}
                        cy={selected.y}
                        r="4"
                        fill="var(--accent)"
                    />
                    <text x="55" y="255">
                        {run.from}
                    </text>
                    <text x="920" y="255" textAnchor="end">
                        {run.through}
                    </text>
                </svg>
                <input
                    type="range"
                    aria-label="帳戶淨值觀察日期"
                    min="0"
                    max={run.nav.length - 1}
                    value={cursor}
                    onChange={(e) => {
                        setCursor(Number(e.target.value));
                        setPage(0);
                    }}
                />
                <div className="research-account-facts">
                    <span>
                        起始{" "}
                        <b>{currencyMoney(run.initialCapital, run.currency)}</b>
                    </span>
                    <span>
                        期末{" "}
                        <b>{currencyMoney(run.finalEquity, run.currency)}</b>
                    </span>
                    <span>
                        模型成本 <b>{currencyMoney(run.costs, run.currency)}</b>
                    </span>
                    <span>
                        總報酬 <b>{(run.netReturn * 100).toFixed(2)}%</b>
                        <small>累積，非年化</small>
                    </span>
                </div>
                <p className="op-footnote">
                    每天記錄一次帳戶價值；成交是模擬的，不是真實帳戶。
                </p>
            </section>
            <section className="op-card research-events">
                <div className="op-section-title">
                    <div>
                        <h2>交易與公司事件</h2>
                    </div>
                    <p>
                        保存 {run.events.length} 筆 · 篩選後 {events.length} 筆
                    </p>
                </div>
                <div className="research-event-filters">
                    <input
                        aria-label="搜尋研究交易事件"
                        value={query}
                        placeholder="股票代號、日期或事件 ID"
                        onChange={(e) => filter(() => setQuery(e.target.value))}
                    />
                    <select
                        aria-label="事件類型"
                        value={kind}
                        onChange={(e) => filter(() => setKind(e.target.value))}
                    >
                        <option value="all">所有事件</option>
                        {[...new Set(run.events.map((e) => e.action))].map(
                            (k) => (
                                <option key={k} value={k}>
                                    {eventLabel(k)}
                                </option>
                            ),
                        )}
                    </select>
                    <label>
                        <input
                            type="checkbox"
                            checked={onlyDate}
                            onChange={(e) =>
                                filter(() => setOnlyDate(e.target.checked))
                            }
                        />
                        只看 {point.date}
                    </label>
                </div>
                <div className="op-table-scroll">
                    <table>
                        <thead>
                            <tr>
                                <th>日期</th>
                                <th>事件</th>
                                <th>股票</th>
                                <th>股數</th>
                                <th>成交價</th>
                                <th>現金流</th>
                                <th>證據</th>
                            </tr>
                        </thead>
                        <tbody>
                            {events
                                .slice(page * 20, page * 20 + 20)
                                .map((e) => (
                                    <tr key={e.id}>
                                        <td>
                                            <time
                                                dateTime={e.date}
                                                title={e.date}
                                            >
                                                {e.date.slice(0, 10)}
                                            </time>
                                        </td>
                                        <td>{eventLabel(e.action)}</td>
                                        <td>{e.code ?? "—"}</td>
                                        <td>
                                            {e.quantity === null
                                                ? "—"
                                                : number(e.quantity)}
                                        </td>
                                        <td>
                                            {e.price === null
                                                ? "—"
                                                : number(e.price)}
                                        </td>
                                        <td>
                                            {e.cashFlow === null
                                                ? "未提供"
                                                : number(e.cashFlow)}
                                        </td>
                                        <td>
                                            <button
                                                onClick={() => setEventId(e.id)}
                                            >
                                                查看原始紀錄
                                            </button>
                                        </td>
                                    </tr>
                                ))}
                        </tbody>
                    </table>
                </div>
                {!events.length && (
                    <p className="op-empty">這個篩選下沒有已保存事件。</p>
                )}
                <div className="research-pagination">
                    <button
                        disabled={page === 0}
                        onClick={() => setPage((p) => p - 1)}
                    >
                        上一頁
                    </button>
                    <span>
                        {page + 1} / {pageCount}
                    </span>
                    <button
                        disabled={page + 1 >= pageCount}
                        onClick={() => setPage((p) => p + 1)}
                    >
                        下一頁
                    </button>
                </div>
                {event && (
                    <section className="research-event-detail">
                        <div>
                            <strong>{event.id}</strong>
                            <button onClick={() => setEventId(null)}>
                                關閉紀錄
                            </button>
                        </div>
                        <p className="op-footnote">
                            來自原始事件，不補造當時沒有記錄的決策理由。查證時請搭配來源版本與完整訂單。
                        </p>
                        <p>
                            完整時間：
                            <time dateTime={event.date}>{event.date}</time> ·
                            原始事件類型：<code>{event.action}</code>
                        </p>
                        <pre>{JSON.stringify(event.original, null, 2)}</pre>
                    </section>
                )}
            </section>
            <details className="op-card op-provenance-details research-tools">
                <summary>研究者工具：策略參數與原始說明</summary>
                <p>
                    規則版本 <code>{run.method.ruleVersion}</code>
                </p>
                <code>{run.method.missionPath}</code>
                <code>{run.method.reportPath}</code>
                <pre>
                    {JSON.stringify(
                        {
                            parameters: run.method.parameters,
                            rules: run.method.rules,
                            conclusion: run.method.conclusion,
                            valuationBasis: run.valuationBasis,
                            limitations: [
                                ...new Set([
                                    ...run.limitations,
                                    ...run.method.limitations,
                                ]),
                            ],
                        },
                        null,
                        2,
                    )}
                </pre>
            </details>
        </>
    );
}
