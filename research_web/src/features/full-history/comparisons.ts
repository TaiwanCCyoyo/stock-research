import { readArtifact } from "../../api/artifacts.ts";
import {
    getHoldingState,
    validateBundle,
} from "../../domain/opportunities/model.ts";
import type {
    CapitalView,
    OpportunityBundle,
    OpportunityPortfolio,
    PortfolioComparison,
    StockParticipation,
} from "../../domain/opportunities/types.ts";
import type { HistoryRow } from "./types.ts";

const STOCK_ID = /^TW:(?!00)\d{4}$/;

export async function readComparisonBundle(
    signal: AbortSignal,
): Promise<OpportunityBundle> {
    const bundle = validateBundle(
        await readArtifact("opportunity-explorer", signal),
    );
    if (bundle.kind === "synthetic")
        throw new Error("不能使用合成範例資料比較實際持有狀態。");
    return bundle;
}

function registeredPortfolioSourceIds(
    bundle: OpportunityBundle,
    portfolio: OpportunityPortfolio,
): Set<string> {
    const registered = new Set(bundle.sources.map((source) => source.id));
    return new Set(
        portfolio.sourceIds.filter((sourceId) => registered.has(sourceId)),
    );
}

function stockRows(rows: HistoryRow[]): Map<string, HistoryRow> {
    const result = new Map<string, HistoryRow>();
    for (const row of rows) {
        if (STOCK_ID.test(row.securityId) && !result.has(row.securityId))
            result.set(row.securityId, row);
    }
    return result;
}

function sourceLabel(bundle: OpportunityBundle, sourceId: string): string {
    return (
        bundle.sources.find((source) => source.id === sourceId)?.label ??
        sourceId
    );
}

/** A missing quantity preserves the holding interval's recorded ownership state. */
export function supportedHoldingSegments(
    comparison: PortfolioComparison,
    securityId: string,
    firstDate: string,
    lastDate: string,
) {
    const portfolio = comparison.portfolio;
    const ownedSources = new Set(portfolio.sourceIds);
    return portfolio.holdings.flatMap((holding, holdingIndex) => {
        const quantity = holding.quantity;
        if (
            holding.securityId !== securityId ||
            (quantity !== undefined &&
                (!Number.isFinite(quantity) || quantity <= 0)) ||
            !ownedSources.has(holding.sourceId)
        )
            return [];

        return portfolio.coverage.flatMap((coverage, coverageIndex) => {
            if (!ownedSources.has(coverage.sourceId)) return [];
            const from = [holding.from, coverage.from, firstDate]
                .sort()
                .at(-1)!;
            const untilExclusive = [
                holding.untilExclusive,
                coverage.untilExclusive,
                lastDate,
            ].sort()[0];
            if (from >= untilExclusive) return [];
            return [
                {
                    key: `${portfolio.id}:${holdingIndex}:${coverageIndex}`,
                    holding,
                    coverage,
                    from,
                    untilExclusive,
                },
            ];
        });
    });
}

function capitalPreview(
    bundle: OpportunityBundle,
    date: string,
    activeRows: Map<string, HistoryRow>,
    portfolio: OpportunityPortfolio,
): CapitalView {
    const empty: CapitalView = {
        status: "unknown",
        opportunityWeight: null,
        otherWeight: null,
        cashWeight: null,
        otherAssetsWeight: null,
        unknownWeight: 1,
        industries: [],
        reason: "沒有同日配置快照",
        sourceId: null,
    };
    const snapshot = portfolio.allocations.find(
        (allocation) => allocation.date === date,
    );
    if (!snapshot) return empty;

    const allowedSources = registeredPortfolioSourceIds(bundle, portfolio);
    if (!allowedSources.has(snapshot.sourceId))
        return {
            ...empty,
            reason: "配置來源未列入策略來源清單",
            sourceId: snapshot.sourceId,
        };

    const securities = new Map(
        bundle.securities.map((security) => [security.id, security]),
    );
    const industryWeights = new Map<
        string,
        { id: string; label: string; weight: number }
    >();
    const hasCompleteDirectory = bundle.catalogCoverage === "declared-universe";
    let opportunityWeight = 0;
    let classifiedOtherWeight = 0;
    for (const position of snapshot.positions) {
        const active = activeRows.get(position.securityId);
        if (active) {
            opportunityWeight += position.weight;
            const industry = industryWeights.get(active.industry.id) ?? {
                id: active.industry.id,
                label: active.industry.label,
                weight: 0,
            };
            industry.weight += position.weight;
            industryWeights.set(industry.id, industry);
            continue;
        }
        const security = securities.get(position.securityId);
        if (hasCompleteDirectory && security && STOCK_ID.test(security.id))
            classifiedOtherWeight += position.weight;
    }

    const otherWeight = hasCompleteDirectory ? classifiedOtherWeight : null;
    const cashWeight = snapshot.cashWeight;
    // An omitted other-assets bucket is unknown. Never infer it to be zero.
    const otherAssetsWeight = snapshot.otherAssetsWeight ?? null;
    const unknownWeight = Math.max(
        0,
        1 -
            opportunityWeight -
            (otherWeight ?? 0) -
            (cashWeight ?? 0) -
            (otherAssetsWeight ?? 0),
    );
    return {
        status: "partial",
        opportunityWeight,
        otherWeight,
        cashWeight,
        otherAssetsWeight,
        unknownWeight,
        industries: [...industryWeights.values()].sort(
            (a, b) => b.weight - a.weight || a.id.localeCompare(b.id),
        ),
        reason: "本日配置快照預覽；不代表其他日期的持有狀態",
        sourceId: snapshot.sourceId,
    };
}

function stockPreviews(
    bundle: OpportunityBundle,
    date: string,
    rows: Map<string, HistoryRow>,
    portfolio: OpportunityPortfolio,
): StockParticipation[] {
    const allowedSources = registeredPortfolioSourceIds(bundle, portfolio);
    const sameDateCoverage = portfolio.coverage.filter(
        (interval) =>
            interval.from <= date &&
            date < interval.untilExclusive &&
            allowedSources.has(interval.sourceId),
    );
    const sameDateHoldings = portfolio.holdings.filter(
        (holding) =>
            holding.from <= date &&
            date < holding.untilExclusive &&
            allowedSources.has(holding.sourceId),
    );
    const datePortfolio: OpportunityPortfolio = {
        ...portfolio,
        coverage: sameDateCoverage,
        holdings: sameDateHoldings,
    };
    return [...rows.values()].map((row) => {
        const held = getHoldingState(datePortfolio, row.securityId, date);
        const evidenceSourceIds = [
            ...new Set([
                ...sameDateCoverage.map((item) => item.sourceId),
                ...sameDateHoldings
                    .filter((item) => item.securityId === row.securityId)
                    .map((item) => item.sourceId),
            ]),
        ];
        const evidence = evidenceSourceIds.length
            ? `；來源：${evidenceSourceIds.map((id) => sourceLabel(bundle, id)).join("、")}`
            : "；沒有可核對的當日來源證據";
        return {
            securityId: row.securityId,
            waveId: row.waveId,
            held,
            positiveMoveShare: null,
            heldDayShare: null,
            knownDays: held === "unknown" ? 0 : 1,
            totalDays: 1,
            reason: `僅呈現 ${date} 的持有狀態；不計算過去漲幅${evidence}`,
        };
    });
}

export function buildPortfolioComparisons(
    bundle: OpportunityBundle,
    date: string,
    rows: HistoryRow[],
): PortfolioComparison[] {
    if (bundle.kind === "synthetic")
        throw new Error("不能使用合成範例資料比較實際持有狀態。");
    const activeRows = stockRows(rows);
    return bundle.portfolios.map((portfolio) => {
        const stocks = stockPreviews(bundle, date, activeRows, portfolio);
        const knownCount = stocks.filter(
            (stock) => stock.held !== "unknown",
        ).length;
        return {
            portfolio,
            date,
            capital: capitalPreview(bundle, date, activeRows, portfolio),
            stocks,
            averagePositiveMoveShare: null,
            knownCount,
            unknownCount: stocks.length - knownCount,
            heldCount: stocks.filter((stock) => stock.held === "held").length,
        };
    });
}

/** Rank observed account weights only; unknown evidence remains unranked. */
export function rankCapitalComparisons(comparisons: PortfolioComparison[]) {
    return [...comparisons].sort((a, b) => {
        const left = a.capital.opportunityWeight;
        const right = b.capital.opportunityWeight;
        if (left == null && right != null) return 1;
        if (left != null && right == null) return -1;
        return (
            (right ?? 0) - (left ?? 0) ||
            a.portfolio.id.localeCompare(b.portfolio.id)
        );
    });
}
