import { useEffect, useMemo, useRef, useState } from "react";
import type { PortfolioComparison } from "../../domain/opportunities/types.ts";
import { CapitalCards } from "../opportunities/evidence.tsx";
import { researchName, researchText } from "../research/researchDisplay.ts";
import {
    buildPortfolioComparisons,
    readComparisonBundle,
    rankCapitalComparisons,
} from "./comparisons.ts";
import type { HistoryRow } from "./types.ts";
import "../opportunities/OpportunityPage.css";
import "./HistoryComparisons.css";

type PortfolioKind = "all" | "strategy" | "tw-etf" | "us-etf";
type HoldingFilter = "held" | "all" | "unknown";
const MAX_SELECTION = 4;
const INITIAL_HOLDING_ROWS = 25;
const kindLabels: Record<Exclude<PortfolioKind, "all">, string> = {
    strategy: "研究策略",
    "tw-etf": "台灣 ETF",
    "us-etf": "美國 ETF",
};
const holdingLabels = {
    held: "有持有",
    "not-held": "未持有",
    unknown: "資料不足",
} as const;
const methodStatusLabels = {
    exploratory: "探索中",
    failed: "未通過",
    incomplete: "尚未完成",
    accepted: "已接受",
} as const;

function pinnedStorageKey(catalogId: string) {
    return `stock-history-comparisons:${catalogId}`;
}

function readPinned(catalogId: string): string[] {
    if (!catalogId || typeof window === "undefined") return [];
    try {
        const stored = window.localStorage.getItem(pinnedStorageKey(catalogId));
        if (!stored) return [];
        const parsed: unknown = JSON.parse(stored);
        return Array.isArray(parsed)
            ? parsed
                  .filter((value): value is string => typeof value === "string")
                  .slice(0, MAX_SELECTION)
            : [];
    } catch {
        return [];
    }
}

export function HistoryComparisons({
    date,
    rows,
    catalogId,
    onComparisons,
}: {
    date: string;
    rows: HistoryRow[];
    catalogId: string;
    onComparisons?: (comparisons: PortfolioComparison[]) => void;
}) {
    const [bundle, setBundle] = useState<Awaited<
        ReturnType<typeof readComparisonBundle>
    > | null>(null);
    const [loadError, setLoadError] = useState("");
    const [selection, setSelection] = useState(() => ({
        catalogId,
        ids: readPinned(catalogId),
    }));
    const [query, setQuery] = useState("");
    const [kind, setKind] = useState<PortfolioKind>("all");
    const [stockQuery, setStockQuery] = useState("");
    const [holdingFilter, setHoldingFilter] = useState<HoldingFilter>("held");
    const [visibleCounts, setVisibleCounts] = useState<Record<string, number>>(
        {},
    );
    const callbackRef = useRef(onComparisons);

    useEffect(() => {
        callbackRef.current = onComparisons;
    }, [onComparisons]);

    useEffect(() => {
        const controller = new AbortController();
        setLoadError("");
        readComparisonBundle(controller.signal)
            .then((data) => {
                if (!controller.signal.aborted) setBundle(data);
            })
            .catch((cause: unknown) => {
                if (!controller.signal.aborted)
                    setLoadError(
                        cause instanceof Error ? cause.message : String(cause),
                    );
            });
        return () => controller.abort();
    }, []);

    const portfolios = bundle?.portfolios ?? [];
    const selectedIds =
        selection.catalogId === catalogId
            ? selection.ids
            : readPinned(catalogId);
    const portfolioById = useMemo(
        () => new Map(portfolios.map((portfolio) => [portfolio.id, portfolio])),
        [portfolios],
    );
    useEffect(() => {
        if (!bundle) return;
        setSelection((current) => {
            const ids =
                current.catalogId === catalogId
                    ? current.ids
                    : readPinned(catalogId);
            return {
                catalogId,
                ids: ids
                    .filter((id) => portfolioById.has(id))
                    .slice(0, MAX_SELECTION),
            };
        });
    }, [bundle, catalogId, portfolioById]);
    useEffect(() => {
        if (!catalogId || selection.catalogId !== catalogId) return;
        try {
            window.localStorage.setItem(
                pinnedStorageKey(catalogId),
                JSON.stringify(selection.ids.slice(0, MAX_SELECTION)),
            );
        } catch {
            // Browsers may disable persistent storage; comparisons still work for this visit.
        }
    }, [catalogId, selection]);

    const rowsKey = rows
        .map(
            (row) =>
                `${row.securityId}:${row.waveId}:${row.industry.id}:${row.industry.label}`,
        )
        .join("|");
    const rowsRef = useRef(rows);
    const rowsKeyRef = useRef(rowsKey);
    if (rowsKeyRef.current !== rowsKey) {
        rowsKeyRef.current = rowsKey;
        rowsRef.current = rows;
    }

    const allComparisons = useMemo(
        () =>
            bundle
                ? buildPortfolioComparisons(bundle, date, rowsRef.current)
                : [],
        [bundle, date, rowsKey],
    );
    const selectedComparisons = useMemo(() => {
        const byId = new Map(
            allComparisons.map((comparison) => [
                comparison.portfolio.id,
                comparison,
            ]),
        );
        return selectedIds.flatMap((id) => {
            const comparison = byId.get(id);
            return comparison ? [comparison] : [];
        });
    }, [allComparisons, selectedIds]);
    const selectedKey = selectedComparisons
        .map((comparison) => comparison.portfolio.id)
        .join("|");
    const rowsById = useMemo(
        () => new Map(rows.map((row) => [row.securityId, row])),
        [rows],
    );
    const stockNeedle = stockQuery.trim().toLocaleLowerCase();
    useEffect(
        () => setVisibleCounts({}),
        [date, selectedKey, stockQuery, holdingFilter],
    );
    const comparisonGroups = useMemo(
        () =>
            selectedComparisons.map((comparison) => {
                const stocks = comparison.stocks
                    .map((stock) => ({
                        stock,
                        row: rowsById.get(stock.securityId),
                    }))
                    .filter(({ stock, row }) => {
                        const matchesState =
                            holdingFilter === "all" ||
                            (holdingFilter === "unknown"
                                ? stock.held === "unknown"
                                : stock.held === "held");
                        const matchesQuery =
                            !stockNeedle ||
                            `${row?.code ?? stock.securityId} ${row?.name ?? ""} ${row?.industry.label ?? ""}`
                                .toLocaleLowerCase()
                                .includes(stockNeedle);
                        return matchesState && matchesQuery;
                    })
                    .sort((a, b) => {
                        const gainA = a.row?.gain;
                        const gainB = b.row?.gain;
                        const rankA =
                            gainA === null || gainA === undefined
                                ? -Infinity
                                : gainA;
                        const rankB =
                            gainB === null || gainB === undefined
                                ? -Infinity
                                : gainB;
                        return (
                            rankB - rankA ||
                            (a.row?.code ?? a.stock.securityId).localeCompare(
                                b.row?.code ?? b.stock.securityId,
                            )
                        );
                    });
                const heldCount = comparison.stocks.filter(
                    (stock) => stock.held === "held",
                ).length;
                const unknownCount = comparison.stocks.filter(
                    (stock) => stock.held === "unknown",
                ).length;
                const notHeldCount = comparison.stocks.filter(
                    (stock) => stock.held === "not-held",
                ).length;
                return {
                    comparison,
                    stocks,
                    heldCount,
                    unknownCount,
                    notHeldCount,
                    visibleCount:
                        visibleCounts[comparison.portfolio.id] ??
                        INITIAL_HOLDING_ROWS,
                };
            }),
        [
            selectedComparisons,
            rowsById,
            holdingFilter,
            stockNeedle,
            visibleCounts,
        ],
    );
    useEffect(() => {
        callbackRef.current?.(selectedComparisons);
    }, [selectedComparisons]);

    const filteredPortfolios = useMemo(() => {
        const needle = query.trim().toLocaleLowerCase();
        return portfolios.filter((portfolio) => {
            const matchesKind = kind === "all" || portfolio.kind === kind;
            const matchesQuery =
                !needle ||
                `${portfolio.name} ${portfolio.description} ${portfolio.method?.taskId ?? ""}`
                    .toLocaleLowerCase()
                    .includes(needle);
            return matchesKind && matchesQuery;
        });
    }, [kind, portfolios, query]);

    function togglePortfolio(id: string) {
        setSelection((selectionState) => {
            const current =
                selectionState.catalogId === catalogId
                    ? selectionState.ids
                    : readPinned(catalogId);
            if (current.includes(id))
                return {
                    catalogId,
                    ids: current.filter((item) => item !== id),
                };
            if (current.length >= MAX_SELECTION) return selectionState;
            return { catalogId, ids: [...current, id] };
        });
    }

    return (
        <section
            className="fh-card fh-comparisons"
            aria-labelledby="fh-comparisons-title"
        >
            <div className="fh-section-heading">
                <div>
                    <h2 id="fh-comparisons-title">
                        這天各策略、ETF 持有哪些飆股
                    </h2>
                    <p>{date} · 選取策略或 ETF，對照持股與資金配置。</p>
                </div>
                <span>
                    {selectedIds.length}/{MAX_SELECTION} 已釘選
                </span>
            </div>

            {loadError ? (
                <p className="fh-comp-error" role="alert">
                    讀取已保存研究帳本失敗：{loadError}
                </p>
            ) : !bundle ? (
                <p role="status">正在讀取已保存的研究策略與 ETF 帳本…</p>
            ) : (
                <>
                    <section
                        className="fh-capital-ranking"
                        aria-label="誰跟得最好"
                    >
                        <h3>誰跟得最好</h3>
                        <p>
                            依這天已核對的帳戶資金放在飆股的比例排序；不是策略報酬。資料未齊時不能判定完整名次。
                        </p>
                        <ol>
                            {rankCapitalComparisons(allComparisons).map(
                                (comparison) => (
                                    <li key={comparison.portfolio.id}>
                                        <span>
                                            {researchName(
                                                comparison.portfolio.name,
                                            )}
                                        </span>
                                        <strong>
                                            {comparison.capital
                                                .opportunityWeight == null
                                                ? "資料不足 · 不排名"
                                                : `${(comparison.capital.opportunityWeight * 100).toFixed(1)}%`}
                                        </strong>
                                        {comparison.capital.opportunityWeight !=
                                            null &&
                                            comparison.capital.unknownWeight >
                                                1e-9 && (
                                                <small>
                                                    另有{" "}
                                                    {(
                                                        comparison.capital
                                                            .unknownWeight * 100
                                                    ).toFixed(1)}
                                                    % 資金待核對；已知比例
                                                </small>
                                            )}
                                    </li>
                                ),
                            )}
                        </ol>
                    </section>
                    <div className="fh-comp-controls">
                        <label>
                            <span>搜尋</span>
                            <input
                                aria-label="搜尋策略或 ETF"
                                placeholder="輸入名稱、說明或研究任務"
                                value={query}
                                onChange={(event) =>
                                    setQuery(event.target.value)
                                }
                            />
                        </label>
                        <label>
                            <span>分組</span>
                            <select
                                aria-label="依帳本類型分組"
                                value={kind}
                                onChange={(event) =>
                                    setKind(event.target.value as PortfolioKind)
                                }
                            >
                                <option value="all">全部類型</option>
                                <option value="strategy">研究策略</option>
                                <option value="tw-etf">台灣 ETF</option>
                                <option value="us-etf">美國 ETF</option>
                            </select>
                        </label>
                    </div>

                    <div className="fh-comp-browser">
                        <div
                            className="fh-comp-list"
                            aria-label="可釘選的策略與 ETF"
                        >
                            {filteredPortfolios.map((portfolio) => {
                                const selected = selectedIds.includes(
                                    portfolio.id,
                                );
                                const atLimit =
                                    !selected &&
                                    selectedIds.length >= MAX_SELECTION;
                                return (
                                    <button
                                        type="button"
                                        className="fh-comp-option"
                                        key={portfolio.id}
                                        aria-pressed={selected}
                                        disabled={atLimit}
                                        onClick={() =>
                                            togglePortfolio(portfolio.id)
                                        }
                                    >
                                        <span className="fh-comp-option-top">
                                            <strong>
                                                {researchName(portfolio.name)}
                                            </strong>
                                            <span>
                                                {kindLabels[portfolio.kind]}
                                            </span>
                                        </span>
                                        <small>
                                            {researchText(
                                                portfolio.description,
                                            )}
                                        </small>
                                        <span className="fh-comp-option-foot">
                                            {selected
                                                ? "已釘選"
                                                : atLimit
                                                  ? "最多比較四項"
                                                  : "加入比較"}
                                            <span>
                                                {portfolio.sourceIds.length}{" "}
                                                個來源
                                            </span>
                                        </span>
                                    </button>
                                );
                            })}
                            {!filteredPortfolios.length && (
                                <p className="fh-empty">
                                    找不到符合條件的帳本。
                                </p>
                            )}
                        </div>

                        <aside
                            className="fh-comp-selected"
                            aria-label="已選擇的比較項目"
                        >
                            <h3>本次比較</h3>
                            {selectedComparisons.length ? (
                                <ul>
                                    {selectedComparisons.map((comparison) => (
                                        <li key={comparison.portfolio.id}>
                                            <span>
                                                {researchName(
                                                    comparison.portfolio.name,
                                                )}
                                            </span>
                                            <button
                                                type="button"
                                                aria-label={`取消釘選 ${researchName(comparison.portfolio.name)}`}
                                                onClick={() =>
                                                    togglePortfolio(
                                                        comparison.portfolio.id,
                                                    )
                                                }
                                            >
                                                移除
                                            </button>
                                        </li>
                                    ))}
                                </ul>
                            ) : (
                                <p>從左側選取最多四個策略或 ETF。</p>
                            )}
                        </aside>
                    </div>

                    <details className="fh-comp-evidence">
                        <summary>研究資料與方法版本</summary>
                        <p>帳本：{bundle.label}</p>
                        <p>帳本識別碼：{bundle.id}</p>
                        {selectedComparisons.map((comparison) => (
                            <section key={comparison.portfolio.id}>
                                <h3>
                                    {researchName(comparison.portfolio.name)}
                                </h3>
                                {comparison.portfolio.method ? (
                                    <>
                                        <dl>
                                            <dt>任務代號</dt>
                                            <dd>
                                                {
                                                    comparison.portfolio.method
                                                        .taskId
                                                }
                                            </dd>
                                            <dt>方法版本</dt>
                                            <dd>
                                                {
                                                    comparison.portfolio.method
                                                        .ruleVersion
                                                }
                                            </dd>
                                            <dt>研究狀態</dt>
                                            <dd>
                                                {
                                                    methodStatusLabels[
                                                        comparison.portfolio
                                                            .method.status
                                                    ]
                                                }
                                            </dd>
                                        </dl>
                                        <p>
                                            {researchText(
                                                comparison.portfolio.method
                                                    .conclusion,
                                            )}
                                        </p>
                                        {comparison.portfolio.method.rules
                                            .length > 0 && (
                                            <ul>
                                                {comparison.portfolio.method.rules.map(
                                                    (rule, index) => (
                                                        <li key={index}>
                                                            {researchText(rule)}
                                                        </li>
                                                    ),
                                                )}
                                            </ul>
                                        )}
                                    </>
                                ) : (
                                    <p>
                                        {researchText(
                                            comparison.portfolio.description,
                                        )}
                                    </p>
                                )}
                                {comparison.portfolio.limitations.length >
                                    0 && (
                                    <ul>
                                        {comparison.portfolio.limitations.map(
                                            (limitation, index) => (
                                                <li key={index}>
                                                    {researchText(limitation)}
                                                </li>
                                            ),
                                        )}
                                    </ul>
                                )}
                            </section>
                        ))}
                    </details>

                    {selectedComparisons.length > 0 && (
                        <div className="op-page fh-comp-capital">
                            <CapitalCards
                                comparisons={selectedComparisons.map(
                                    (comparison) => ({
                                        ...comparison,
                                        capital: {
                                            ...comparison.capital,
                                            reason: null,
                                        },
                                    }),
                                )}
                                scopeLabel="本日預覽"
                            />
                        </div>
                    )}

                    {selectedComparisons.length > 0 && (
                        <div className="fh-comp-stock-controls">
                            <label>
                                <span>搜尋股票</span>
                                <input
                                    aria-label="搜尋比較股票"
                                    placeholder="輸入代碼、名稱或產業"
                                    value={stockQuery}
                                    onChange={(event) =>
                                        setStockQuery(event.target.value)
                                    }
                                />
                            </label>
                            <label>
                                <span>顯示持股狀態</span>
                                <select
                                    aria-label="篩選持股狀態"
                                    value={holdingFilter}
                                    onChange={(event) =>
                                        setHoldingFilter(
                                            event.target.value as HoldingFilter,
                                        )
                                    }
                                >
                                    <option value="held">有持有</option>
                                    <option value="all">全部</option>
                                    <option value="unknown">未知</option>
                                </select>
                            </label>
                        </div>
                    )}

                    <div className="fh-comp-holdings">
                        {comparisonGroups.map((group) => {
                            const { comparison } = group;
                            const shownStocks = group.stocks.slice(
                                0,
                                group.visibleCount,
                            );
                            const sourceLabels =
                                comparison.portfolio.sourceIds.map(
                                    (id) =>
                                        bundle.sources.find(
                                            (source) => source.id === id,
                                        )?.label ?? "未保存來源名稱",
                                );
                            const capitalSource = comparison.capital.sourceId
                                ? (bundle.sources.find(
                                      (source) =>
                                          source.id ===
                                          comparison.capital.sourceId,
                                  )?.label ?? "未保存來源名稱")
                                : null;
                            const coveredSources = comparison.portfolio.coverage
                                .filter(
                                    (interval) =>
                                        interval.from <= comparison.date &&
                                        comparison.date <
                                            interval.untilExclusive,
                                )
                                .map(
                                    (interval) =>
                                        bundle.sources.find(
                                            (source) =>
                                                source.id === interval.sourceId,
                                        )?.label ?? "未保存來源名稱",
                                );
                            return (
                                <section key={comparison.portfolio.id}>
                                    <div className="fh-section-heading">
                                        <h3>
                                            {researchName(
                                                comparison.portfolio.name,
                                            )}
                                        </h3>
                                        <span>{comparison.date}</span>
                                    </div>
                                    <p className="fh-comp-holding-summary">
                                        有持有 {group.heldCount} 檔 · 未持有{" "}
                                        {group.notHeldCount} 檔 · 資料不足{" "}
                                        {group.unknownCount} 檔
                                    </p>
                                    {shownStocks.length ? (
                                        <ul>
                                            {shownStocks.map(
                                                ({ stock, row }) => (
                                                    <li
                                                        key={`${comparison.portfolio.id}:${stock.securityId}:${stock.waveId}`}
                                                    >
                                                        <span
                                                            className={`fh-holding-state state-${stock.held}`}
                                                        >
                                                            {
                                                                holdingLabels[
                                                                    stock.held
                                                                ]
                                                            }
                                                        </span>
                                                        <strong>
                                                            {row?.code ??
                                                                stock.securityId}{" "}
                                                            {researchName(
                                                                row?.name ?? "",
                                                            )}
                                                        </strong>
                                                        <span className="fh-comp-stock-gain">
                                                            {row?.gain ==
                                                                null ||
                                                            !Number.isFinite(
                                                                row.gain,
                                                            )
                                                                ? "當日漲幅未知"
                                                                : `本波至這天 ${row.gain >= 0 ? "+" : ""}${row.gain.toFixed(1)}%`}
                                                        </span>
                                                    </li>
                                                ),
                                            )}
                                        </ul>
                                    ) : (
                                        <p className="fh-comp-no-holdings">
                                            {stockNeedle
                                                ? "找不到符合條件的股票。"
                                                : holdingFilter === "held"
                                                  ? "這天沒有可確認有持有的股票。"
                                                  : holdingFilter === "unknown"
                                                    ? "這天沒有資料不足的股票。"
                                                    : "這天沒有可比較的股票。"}
                                        </p>
                                    )}
                                    {group.stocks.length >
                                        group.visibleCount && (
                                        <button
                                            type="button"
                                            className="fh-comp-show-more"
                                            onClick={() =>
                                                setVisibleCounts((current) => ({
                                                    ...current,
                                                    [comparison.portfolio.id]:
                                                        group.visibleCount +
                                                        INITIAL_HOLDING_ROWS,
                                                }))
                                            }
                                        >
                                            再顯示{" "}
                                            {Math.min(
                                                INITIAL_HOLDING_ROWS,
                                                group.stocks.length -
                                                    group.visibleCount,
                                            )}{" "}
                                            檔
                                        </button>
                                    )}
                                    <details className="fh-comp-holding-evidence">
                                        <summary>持股證據與來源</summary>
                                        <p>
                                            資料日期：{comparison.date}
                                            。只依這一天有涵蓋的來源確認持股；來源沒有涵蓋，或沒有個股證據時，會標為資料不足。
                                        </p>
                                        {sourceLabels.length > 0 && (
                                            <p>
                                                策略來源：
                                                {sourceLabels.join("、")}
                                            </p>
                                        )}
                                        <p>
                                            這天有涵蓋的來源：
                                            {coveredSources.length
                                                ? [
                                                      ...new Set(
                                                          coveredSources,
                                                      ),
                                                  ].join("、")
                                                : "沒有來源聲明涵蓋這一天"}
                                        </p>
                                        {capitalSource && (
                                            <p>配置來源：{capitalSource}</p>
                                        )}
                                        {comparison.capital.reason && (
                                            <p>
                                                配置資料說明：
                                                {comparison.capital.reason}
                                            </p>
                                        )}
                                        {shownStocks.length > 0 ? (
                                            <ul>
                                                {shownStocks.map(
                                                    ({ stock, row }) => (
                                                        <li
                                                            key={`${comparison.portfolio.id}:evidence:${stock.securityId}:${stock.waveId}`}
                                                        >
                                                            <strong>
                                                                {row?.code ??
                                                                    stock.securityId}{" "}
                                                                {researchName(
                                                                    row?.name ??
                                                                        "",
                                                                )}
                                                            </strong>
                                                            <small>
                                                                持股證據：
                                                                {stock.reason ??
                                                                    "沒有額外說明"}
                                                            </small>
                                                            {row?.industry && (
                                                                <small>
                                                                    分類依據：
                                                                    {row
                                                                        .industry
                                                                        .basis ===
                                                                    "current-snapshot"
                                                                        ? `現有分類快照${row.industry.snapshotAt ? `（${row.industry.snapshotAt}）` : ""}`
                                                                        : "未知"}
                                                                </small>
                                                            )}
                                                            {row?.reason && (
                                                                <small>
                                                                    行情資料說明：
                                                                    {row.reason}
                                                                </small>
                                                            )}
                                                        </li>
                                                    ),
                                                )}
                                            </ul>
                                        ) : (
                                            <p>
                                                目前篩選條件下沒有股票證據可列出；調整上方篩選可查看其他狀態。
                                            </p>
                                        )}
                                        {group.stocks.length >
                                            group.visibleCount && (
                                            <p>
                                                尚有{" "}
                                                {group.stocks.length -
                                                    group.visibleCount}{" "}
                                                筆未顯示；可使用上方「再顯示」查看。
                                            </p>
                                        )}
                                    </details>
                                </section>
                            );
                        })}
                    </div>
                </>
            )}
        </section>
    );
}
