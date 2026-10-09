import type {
    CapitalView,
    HoldingState,
    IndustryMembership,
    MarketView,
    OpportunityBundle,
    OpportunityPortfolio,
    OpportunityRow,
    OpportunitySecurity,
    OpportunityWave,
    PortfolioComparison,
    PricePoint,
    StockParticipation,
} from "./types.ts";

/** 收盤持倉與上漲日重疊率: descriptive overlap, not investment profit. */
export const POSITIVE_MOVE_SHARE_VERSION =
    "close_exposure_positive_return_overlap.v1";
export const POSITIVE_MOVE_SHARE_LABEL = "收盤持倉與上漲日重疊率";
const WEIGHT_TOLERANCE = 1e-6;
const DAY_MS = 86_400_000;
const UNKNOWN_INDUSTRY = { id: "unknown", label: "產業資料未知" } as const;

function inInterval(
    date: string,
    interval: { from: string; untilExclusive: string | null },
): boolean {
    return (
        interval.from <= date &&
        (interval.untilExclusive === null || date < interval.untilExclusive)
    );
}

function validPrice(
    price: PricePoint | undefined,
): price is PricePoint & { close: number } {
    return (
        price !== undefined &&
        price.close !== null &&
        Number.isFinite(price.close) &&
        price.close > 0 &&
        price.flags.length === 0
    );
}

function unknownIndustry(date: string): IndustryMembership {
    return {
        ...UNKNOWN_INDUSTRY,
        from: date,
        untilExclusive: null,
        basis: "unknown",
        sourceId: "",
    };
}

function industryAt(
    security: OpportunitySecurity,
    date: string,
): IndustryMembership {
    for (const basis of ["historical", "document-period"] as const) {
        const matches = security.industry.filter(
            (membership) =>
                membership.basis === basis && inInterval(date, membership),
        );
        if (matches.length > 0)
            return matches.length === 1 ? matches[0] : unknownIndustry(date);
    }
    return unknownIndustry(date);
}

function wavePrices(
    bundle: OpportunityBundle,
    security: OpportunitySecurity,
    wave: OpportunityWave,
    date: string,
) {
    const prices = new Map(security.prices.map((price) => [price.date, price]));
    return intervalPrices(bundle.dates, prices, wave.start, date);
}

function intervalPrices(
    calendar: string[],
    prices: ReadonlyMap<string, PricePoint>,
    start: string,
    through: string,
) {
    const dates = calendar.filter((day) => start <= day && day <= through);
    const points = dates.map((day) => prices.get(day));
    const complete =
        dates[0] === start &&
        dates.at(-1) === through &&
        points.every(validPrice);
    return { dates, points, complete };
}

function makeRow(
    bundle: OpportunityBundle,
    security: OpportunitySecurity,
    wave: OpportunityWave,
    date: string,
    representative: boolean,
): OpportunityRow {
    const series = wavePrices(bundle, security, wave, date);
    const last = series.points.at(-1);
    const first = series.points[0];
    const inObservation = date <= wave.observedThrough;
    const inWaveObservation =
        inObservation &&
        (wave.endConfirmedAt === null || date <= wave.endConfirmedAt);
    const gain =
        inWaveObservation &&
        series.complete &&
        validPrice(first) &&
        validPrice(last)
            ? (last.close / first.close - 1) * 100
            : null;
    // This catalog intentionally includes retrospective wave labels. Keep that
    // labeled peak distinct from the selected date's start-to-date gain.
    const peakSeries = wavePrices(bundle, security, wave, wave.observedThrough);
    const peakStart = peakSeries.points[0];
    const peak = security.prices.find((point) => point.date === wave.peakDate);
    const peakGain =
        peakSeries.complete &&
        validPrice(peakStart) &&
        validPrice(peak) &&
        peakSeries.points.every(
            (point) => validPrice(point) && point.close <= peak.close,
        )
            ? (peak.close / peakStart.close - 1) * 100
            : null;
    const confirmation =
        wave.endConfirmedAt !== null && date >= wave.endConfirmedAt
            ? wavePrices(bundle, security, wave, wave.endConfirmedAt)
            : null;
    const endStart = confirmation?.points[0];
    const endPrice = confirmation?.points.at(-1);
    const endGain =
        confirmation?.complete && validPrice(endStart) && validPrice(endPrice)
            ? (endPrice.close / endStart.close - 1) * 100
            : null;
    const launchPrice = wave.launch
        ? security.prices.find((point) => point.date === wave.launch!.date)
        : undefined;
    const launchGain =
        inWaveObservation &&
        wave.launch &&
        date >= wave.launch.date &&
        series.complete &&
        validPrice(launchPrice) &&
        validPrice(last)
            ? (last.close / launchPrice.close - 1) * 100
            : null;
    let state: OpportunityRow["state"];
    let reason: string | null = null;
    if (date < wave.start) state = "outside";
    else if (!representative) {
        state = "unknown";
        reason = "missing-representative-interval";
    } else if (wave.endConfirmedAt !== null && date >= wave.endConfirmedAt) {
        // A confirmed exit survives the observation cutoff. Price loss alone
        // still cannot create an exit: the confirmation interval must be valid.
        state = confirmation?.complete ? "ended" : "unknown";
        reason = confirmation?.complete ? null : "missing-or-flagged-price";
    } else if (!inObservation) {
        state = "unknown";
        reason = "after-observed-through";
    } else if (!series.complete) {
        state = "unknown";
        reason = "missing-or-flagged-price";
    } else if (wave.launch === null || date < wave.launch.date) {
        state = "unlaunched";
        reason =
            wave.launch === null ? wave.launchMissingReason : "before-launch";
    } else state = "active";
    const phase = inObservation
        ? (wave.phases.find((interval) => inInterval(date, interval))?.kind ??
          null)
        : null;
    return {
        security,
        wave,
        industry: industryAt(security, date),
        gain,
        launchGain,
        peakGain,
        endGain,
        price: inObservation && validPrice(last) ? last.close : null,
        phase,
        state,
        // This absolute area scale must remain identical across observation dates.
        weight: gain === null ? 0 : (Math.max(0, gain) / 100) ** 2,
        reason,
    };
}

/** Requires an exact calendar observation; no nearest-date or price filling. */
export function buildMarketView(
    bundle: OpportunityBundle,
    date: string,
): MarketView {
    if (!bundle.dates.includes(date))
        throw new Error(`Observation date is not in bundle calendar: ${date}`);
    const rows: OpportunityRow[] = [];
    for (const security of bundle.securities) {
        const representatives = bundle.representatives.filter(
            (interval) =>
                interval.securityId === security.id &&
                inInterval(date, interval),
        );
        if (representatives.length > 1)
            throw new Error(
                `Overlapping representatives for ${security.id} on ${date}`,
            );
        const representative = representatives[0];
        const waves = bundle.waves.filter(
            (wave) =>
                wave.securityId === security.id &&
                (!representative || wave.id === representative.waveId),
        );
        for (const wave of waves)
            rows.push(
                makeRow(
                    bundle,
                    security,
                    wave,
                    date,
                    representative !== undefined,
                ),
            );
    }
    const active = rows
        .filter((row) => row.state === "active")
        .sort(
            (a, b) =>
                (b.gain ?? 0) - (a.gain ?? 0) ||
                a.security.id.localeCompare(b.security.id),
        );
    const industries = new Map<string, MarketView["industries"][number]>();
    for (const row of active) {
        const industry = industries.get(row.industry.id) ?? {
            id: row.industry.id,
            label: row.industry.label,
            gainSum: 0,
            maxGain: row.gain!,
            rows: [],
        };
        industry.gainSum += row.gain!;
        industry.maxGain = Math.max(industry.maxGain, row.gain!);
        industry.rows.push(row);
        industries.set(industry.id, industry);
    }
    return {
        date,
        rows,
        active,
        unlaunched: rows.filter((row) => row.state === "unlaunched"),
        ended: rows.filter((row) => row.state === "ended"),
        unknown: rows.filter((row) => row.state === "unknown"),
        industries: [...industries.values()].sort(
            (a, b) => b.gainSum - a.gainSum || a.id.localeCompare(b.id),
        ),
    };
}

/** Coverage and holdings are independently half-open; no evidence extends beyond coverage. */
export function getHoldingState(
    portfolio: OpportunityPortfolio,
    securityId: string,
    date: string,
): HoldingState {
    const coverage = portfolio.coverage.filter((interval) =>
        inInterval(date, interval),
    );
    if (coverage.length === 0) return "unknown";
    if (
        portfolio.holdings.some(
            (holding) =>
                holding.securityId === securityId &&
                inInterval(date, holding) &&
                (holding.quantity === undefined || holding.quantity > 0),
        )
    )
        return "held";
    return coverage.some((interval) => interval.completeness === "full")
        ? "not-held"
        : "unknown";
}

/** Sweep the validated, increasing calendar once; never cache mutable portfolio inputs. */
function holdingStates(
    portfolio: OpportunityPortfolio,
    securityId: string,
    dates: string[],
): HoldingState[] {
    if (dates.length === 0) return [];
    type Event = { date: string; covered: number; full: number; held: number };
    const events: Event[] = [];
    const first = dates[0];
    const last = dates.at(-1)!;
    const add = (
        interval: { from: string; untilExclusive: string | null },
        covered: number,
        full: number,
        held: number,
    ) => {
        const until = interval.untilExclusive;
        if (
            interval.from > last ||
            (until !== null && (until <= first || until <= interval.from))
        )
            return;
        events.push({
            date: interval.from < first ? first : interval.from,
            covered,
            full,
            held,
        });
        if (until !== null && until <= last)
            events.push({
                date: until,
                covered: -covered,
                full: -full,
                held: -held,
            });
    };
    for (const interval of portfolio.coverage)
        add(interval, 1, interval.completeness === "full" ? 1 : 0, 0);
    for (const interval of portfolio.holdings) {
        if (
            interval.securityId === securityId &&
            (interval.quantity === undefined || interval.quantity > 0)
        )
            add(interval, 0, 0, 1);
    }
    events.sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
    let index = 0,
        covered = 0,
        full = 0,
        held = 0;
    return dates.map((day) => {
        // Apply every start/end on this day before querying: ends are exclusive.
        while (index < events.length && events[index].date <= day) {
            const event = events[index++];
            covered += event.covered;
            full += event.full;
            held += event.held;
        }
        return covered === 0
            ? "unknown"
            : held > 0
              ? "held"
              : full > 0
                ? "not-held"
                : "unknown";
    });
}

/**
 * Sum positive daily simple returns from the wave start through D, attributing a
 * move to the holding evidence at that day's close. This deliberately makes no
 * execution-price, position-size or actual-profit claim. Keep this definition in
 * one function so research can explicitly version any later semantic change.
 */
export function calculateParticipation(
    bundle: OpportunityBundle,
    row: OpportunityRow,
    portfolio: OpportunityPortfolio,
    date: string,
): StockParticipation {
    const { dates, points, complete } = wavePrices(
        bundle,
        row.security,
        row.wave,
        date,
    );
    const states = holdingStates(portfolio, row.security.id, dates);
    const knownDays = states.filter((state) => state !== "unknown").length;
    const heldDays = states.filter((state) => state === "held").length;
    const bounded =
        date >= row.wave.start &&
        date <= row.wave.observedThrough &&
        (row.wave.endConfirmedAt === null || date <= row.wave.endConfirmedAt);
    let positiveTotal = 0;
    let positiveHeld = 0;
    let unknownPositiveDay = false;
    for (let i = 1; i < points.length; i++) {
        const previous = points[i - 1];
        const current = points[i];
        if (!validPrice(previous) || !validPrice(current)) continue;
        const positive = Math.max(0, current.close / previous.close - 1);
        positiveTotal += positive;
        if (positive > 0 && states[i] === "held") positiveHeld += positive;
        if (positive > 0 && states[i] === "unknown") unknownPositiveDay = true;
    }
    const reason = !bounded
        ? "outside-wave-observation"
        : !complete
          ? "missing-or-flagged-price"
          : unknownPositiveDay
            ? "unknown-holding-on-positive-day"
            : positiveTotal === 0
              ? "no-positive-price-moves"
              : knownDays !== dates.length
                ? "partial-holding-coverage"
                : null;
    return {
        securityId: row.security.id,
        waveId: row.wave.id,
        held: !bounded
            ? "unknown"
            : dates.at(-1) === date
              ? states.at(-1)!
              : getHoldingState(portfolio, row.security.id, date),
        positiveMoveShare:
            bounded && complete && !unknownPositiveDay && positiveTotal > 0
                ? positiveHeld / positiveTotal
                : null,
        heldDayShare:
            bounded &&
            complete &&
            dates.length > 0 &&
            knownDays === dates.length
                ? heldDays / dates.length
                : null,
        knownDays,
        totalDays: dates.length,
        reason,
    };
}

function capitalAt(
    bundle: OpportunityBundle,
    view: MarketView,
    portfolio: OpportunityPortfolio,
): CapitalView {
    const snapshots = portfolio.allocations.filter(
        (allocation) => allocation.date === view.date,
    );
    if (snapshots.length > 1)
        throw new Error(
            `Duplicate allocation date for ${portfolio.id}: ${view.date}`,
        );
    const snapshot = snapshots[0];
    const empty: CapitalView = {
        status: "unknown",
        opportunityWeight: null,
        otherWeight: null,
        cashWeight: null,
        otherAssetsWeight: null,
        unknownWeight: 1,
        industries: [],
        reason: "no-same-date-allocation",
        sourceId: null,
    };
    if (!snapshot) return empty;
    const active = new Map(view.active.map((row) => [row.security.id, row]));
    const industries = new Map<
        string,
        { id: string; label: string; weight: number }
    >();
    const seen = new Set<string>();
    let opportunityWeight = 0;
    let otherWeight = 0;
    let classifiedPosition = false;
    for (const position of snapshot.positions) {
        if (seen.has(position.securityId))
            throw new Error(
                `Duplicate allocation position: ${position.securityId}`,
            );
        seen.add(position.securityId);
        const row = active.get(position.securityId);
        if (row) {
            classifiedPosition = true;
            opportunityWeight += position.weight;
            const industry = industries.get(row.industry.id) ?? {
                id: row.industry.id,
                label: row.industry.label,
                weight: 0,
            };
            industry.weight += position.weight;
            industries.set(industry.id, industry);
        } else {
            const security = bundle.securities.find(
                (item) => item.id === position.securityId,
            );
            const reliable =
                bundle.catalogCoverage === "declared-universe" &&
                security &&
                validPrice(
                    security.prices.find((price) => price.date === view.date),
                ) &&
                !view.rows.some(
                    (item) =>
                        item.security.id === position.securityId &&
                        item.state === "unknown",
                );
            if (reliable) {
                classifiedPosition = true;
                otherWeight += position.weight;
            }
        }
    }
    const stockAndCash = snapshot.positions.reduce(
        (sum, position) => sum + position.weight,
        snapshot.cashWeight ?? 0,
    );
    // Legacy snapshots may omit this bucket. Only a reconciled 100% stock/cash
    // total proves it is zero; an unaccounted residual must remain unknown.
    const otherAssetsWeight =
        snapshot.otherAssetsWeight ??
        (Math.abs(stockAndCash - 1) <= WEIGHT_TOLERANCE ? 0 : null);
    const unknownWeight = Math.max(
        0,
        1 -
            opportunityWeight -
            otherWeight -
            (snapshot.cashWeight ?? 0) -
            (otherAssetsWeight ?? 0),
    );
    const total = stockAndCash + (otherAssetsWeight ?? 0);
    const known =
        snapshot.completeness === "full" &&
        snapshot.cashWeight !== null &&
        otherAssetsWeight !== null &&
        Math.abs(total - 1) <= WEIGHT_TOLERANCE &&
        unknownWeight <= WEIGHT_TOLERANCE;
    if (
        !classifiedPosition &&
        snapshot.cashWeight === null &&
        otherAssetsWeight === null
    )
        return {
            ...empty,
            reason: "allocation-assets-outside-reliable-catalog",
            sourceId: snapshot.sourceId,
        };
    return {
        status: known ? "known" : "partial",
        opportunityWeight,
        otherWeight,
        cashWeight: snapshot.cashWeight,
        otherAssetsWeight,
        unknownWeight: unknownWeight <= WEIGHT_TOLERANCE ? 0 : unknownWeight,
        industries: [...industries.values()].sort(
            (a, b) => b.weight - a.weight || a.id.localeCompare(b.id),
        ),
        reason: known
            ? null
            : snapshot.completeness === "partial"
              ? "partial-allocation"
              : snapshot.cashWeight === null
                ? "unknown-cash-weight"
                : "unclassified-or-unobserved-capital",
        sourceId: snapshot.sourceId,
    };
}

export function comparePortfolio(
    bundle: OpportunityBundle,
    view: MarketView,
    portfolio: OpportunityPortfolio,
): PortfolioComparison {
    if (!bundle.dates.includes(view.date))
        throw new Error(
            `Observation date is not in bundle calendar: ${view.date}`,
        );
    const stocks = view.active.map((row) =>
        calculateParticipation(bundle, row, portfolio, view.date),
    );
    const known = stocks.filter((stock) => stock.positiveMoveShare !== null);
    return {
        portfolio,
        date: view.date,
        capital: capitalAt(bundle, view, portfolio),
        stocks,
        averagePositiveMoveShare:
            known.length > 0
                ? known.reduce(
                      (sum, stock) => sum + stock.positiveMoveShare!,
                      0,
                  ) / known.length
                : null,
        knownCount: known.length,
        unknownCount: stocks.length - known.length,
        heldCount: stocks.filter((stock) => stock.held === "held").length,
    };
}

type ObjectValue = Record<string, unknown>;
function fail(path: string, message: string): never {
    throw new Error(`Invalid opportunity bundle at ${path}: ${message}`);
}
function object(value: unknown, path: string): ObjectValue {
    if (value === null || typeof value !== "object" || Array.isArray(value))
        fail(path, "expected object");
    return value as ObjectValue;
}
function array(value: unknown, path: string): unknown[] {
    if (!Array.isArray(value)) fail(path, "expected array");
    return value;
}
function string(value: unknown, path: string): string {
    if (typeof value !== "string" || value.trim().length === 0)
        fail(path, "expected non-empty string");
    return value;
}
function strings(value: unknown, path: string): void {
    array(value, path).forEach((entry, i) => string(entry, `${path}[${i}]`));
}
function number(
    value: unknown,
    path: string,
    min: number,
    max = Infinity,
): number {
    if (
        typeof value !== "number" ||
        !Number.isFinite(value) ||
        value < min ||
        value > max
    )
        fail(path, `expected finite number in [${min}, ${max}]`);
    return value;
}
function date(value: unknown, path: string): string {
    const result = string(value, path);
    if (
        !/^\d{4}-\d{2}-\d{2}$/.test(result) ||
        !Number.isFinite(Date.parse(`${result}T00:00:00Z`)) ||
        new Date(`${result}T00:00:00Z`).toISOString().slice(0, 10) !== result
    )
        fail(path, "expected valid YYYY-MM-DD date");
    return result;
}
function choice(
    value: unknown,
    choices: readonly string[],
    path: string,
): void {
    if (typeof value !== "string" || !choices.includes(value))
        fail(path, `expected one of ${choices.join(", ")}`);
}
function bool(value: unknown, path: string): void {
    if (typeof value !== "boolean") fail(path, "expected boolean");
}
function unique(
    records: ObjectValue[],
    key: string,
    path: string,
): Set<string> {
    const seen = new Set<string>();
    for (const record of records) {
        const id = string(record[key], `${path}.${key}`);
        if (seen.has(id)) fail(path, `duplicate ${key}: ${id}`);
        seen.add(id);
    }
    return seen;
}
function records(value: unknown, path: string): ObjectValue[] {
    return array(value, path).map((entry, i) => object(entry, `${path}[${i}]`));
}
function reference(value: unknown, ids: Set<string>, path: string): void {
    if (!ids.has(string(value, path)))
        fail(path, `unknown reference: ${value}`);
}
function interval(value: ObjectValue, path: string, nullable = false): void {
    const from = date(value.from, `${path}.from`);
    if (nullable && value.untilExclusive === null) return;
    if (date(value.untilExclusive, `${path}.untilExclusive`) <= from)
        fail(path, "interval must be non-empty and half-open");
}
function nonOverlapping(
    values: ObjectValue[],
    groupKey: string | null,
    path: string,
): void {
    const groups = new Map<unknown, ObjectValue[]>();
    for (const entry of values) {
        const key = groupKey ? entry[groupKey] : "all";
        const group = groups.get(key) ?? [];
        group.push(entry);
        groups.set(key, group);
    }
    for (const group of groups.values()) {
        const sorted = [...group].sort((a, b) =>
            String(a.from).localeCompare(String(b.from)),
        );
        for (let i = 1; i < sorted.length; i++)
            if (
                sorted[i - 1].untilExclusive === null ||
                String(sorted[i].from) < String(sorted[i - 1].untilExclusive)
            )
                fail(path, "overlapping intervals");
    }
}

/** Validate untrusted JSON before either browser or CLI calculation. */
export function validateBundle(value: unknown): OpportunityBundle {
    const bundle = object(value, "bundle");
    choice(bundle.schema, ["opportunity-explorer.v1"], "schema");
    for (const key of [
        "id",
        "label",
        "priceBasis",
        "ruleVersion",
        "selectionPolicy",
        "classificationVersion",
    ])
        string(bundle[key], key);
    choice(
        bundle.kind,
        ["synthetic", "historical-preview", "historical"],
        "kind",
    );
    choice(
        bundle.catalogCoverage,
        ["declared-universe", "case-slice"],
        "catalogCoverage",
    );
    date(bundle.asOf, "asOf");
    strings(bundle.limitations, "limitations");
    const dates = array(bundle.dates, "dates").map((entry, i) =>
        date(entry, `dates[${i}]`),
    );
    if (
        dates.length === 0 ||
        dates.some((day, i) => i > 0 && dates[i - 1] >= day)
    )
        fail("dates", "calendar must be non-empty, unique and increasing");
    if (dates.at(-1)! > String(bundle.asOf))
        fail("dates", "calendar exceeds bundle asOf");
    const calendar = new Set(dates);
    const calendarDate = (entry: unknown, path: string) => {
        const day = date(entry, path);
        if (!calendar.has(day)) fail(path, "date is not in bundle calendar");
        return day;
    };
    const sources = records(bundle.sources, "sources");
    const sourceIds = unique(sources, "id", "sources");
    for (const source of sources) {
        string(source.label, "source.label");
        for (const key of ["path", "url", "hash", "publishedAt"])
            if (source[key] !== undefined) string(source[key], `source.${key}`);
    }
    const securities = records(bundle.securities, "securities");
    const securityIds = unique(securities, "id", "securities");
    for (const security of securities) {
        for (const key of ["code", "name", "market", "currency"])
            string(security[key], `security.${key}`);
        if (security.detailCaseId !== undefined)
            string(security.detailCaseId, "security.detailCaseId");
        if (security.classificationSnapshot !== undefined) {
            const snapshot = object(
                security.classificationSnapshot,
                "security.classificationSnapshot",
            );
            string(snapshot.label, "classificationSnapshot.label");
            if (snapshot.observedAt !== null) {
                const observedAt = string(
                    snapshot.observedAt,
                    "classificationSnapshot.observedAt",
                );
                const observedDay = date(
                    observedAt.slice(0, 10),
                    "classificationSnapshot.observedAt",
                );
                if (
                    observedAt !== observedDay &&
                    (!/^\d{4}-\d{2}-\d{2}T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d+)?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(
                        observedAt,
                    ) ||
                        !Number.isFinite(Date.parse(observedAt)))
                )
                    fail(
                        "classificationSnapshot.observedAt",
                        "expected a date or timestamp with explicit timezone",
                    );
            }
            reference(
                snapshot.sourceId,
                sourceIds,
                "classificationSnapshot.sourceId",
            );
        }
        if (security.classificationReferences !== undefined) {
            const references = records(
                security.classificationReferences,
                "security.classificationReferences",
            );
            unique(references, "id", "security.classificationReferences");
            for (const item of references) {
                string(item.label, "classificationReference.label");
                choice(
                    item.layer,
                    [
                        "official-value-chain",
                        "research-group",
                        "business-role",
                        "business-group",
                        "business-sector",
                    ],
                    "classificationReference.layer",
                );
                choice(
                    item.temporalScope,
                    [
                        "snapshot",
                        "retrospective-period-summary",
                        "retrospective-event-context",
                        "undated-reference",
                        "dated-profile-reference",
                    ],
                    "classificationReference.temporalScope",
                );
                if (item.from !== null || item.untilExclusive !== null)
                    interval(item, "classificationReference");
                const ids = array(
                    item.sourceIds,
                    "classificationReference.sourceIds",
                );
                if (ids.length === 0)
                    fail(
                        "classificationReference.sourceIds",
                        "at least one source is required",
                    );
                for (const id of ids)
                    reference(
                        id,
                        sourceIds,
                        "classificationReference.sourceIds",
                    );
            }
        }
        const memberships = records(security.industry, "security.industry");
        for (const membership of memberships) {
            string(membership.id, "industry.id");
            string(membership.label, "industry.label");
            interval(membership, "industry", true);
            choice(
                membership.basis,
                [
                    "historical",
                    "document-period",
                    "current-snapshot",
                    "unknown",
                ],
                "industry.basis",
            );
            if (
                membership.id === UNKNOWN_INDUSTRY.id &&
                (membership.basis !== "unknown" ||
                    membership.label !== UNKNOWN_INDUSTRY.label)
            )
                fail(
                    "industry.id",
                    "reserved unknown industry id requires the unknown basis and canonical unknown label",
                );
            reference(membership.sourceId, sourceIds, "industry.sourceId");
        }
        nonOverlapping(
            memberships.filter(
                (membership) =>
                    membership.basis === "historical" ||
                    membership.basis === "document-period",
            ),
            "basis",
            "industry",
        );
        const prices = records(security.prices, "security.prices");
        let previous = "";
        for (const price of prices) {
            const day = calendarDate(price.date, "price.date");
            if (day <= previous)
                fail("prices", "dates must be unique and increasing");
            previous = day;
            for (const key of ["close", "raw", "marketCap"])
                if (
                    price[key] !== null &&
                    (key === "close" || price[key] !== undefined)
                ) {
                    if (number(price[key], `price.${key}`, 0) === 0)
                        fail(`price.${key}`, "must be positive or null");
                }
            strings(price.flags, "price.flags");
        }
    }
    const membershipsById = new Map<string, IndustryMembership[]>();
    for (const security of securities) {
        // Membership fields and intervals have all been validated above.
        for (const membership of security.industry as IndustryMembership[]) {
            const previous = membershipsById.get(membership.id) ?? [];
            if (
                previous.some(
                    (item) =>
                        item.label !== membership.label &&
                        (membership.untilExclusive === null ||
                            item.from < membership.untilExclusive) &&
                        (item.untilExclusive === null ||
                            membership.from < item.untilExclusive),
                )
            )
                fail(
                    "industry",
                    `overlapping group label conflict: ${membership.id}`,
                );
            previous.push(membership);
            membershipsById.set(membership.id, previous);
        }
    }
    const waves = records(bundle.waves, "waves");
    const waveIds = unique(waves, "id", "waves");
    const pricesBySecurity = new Map(
        securities.map((security) => [
            security.id,
            new Map(
                (security.prices as PricePoint[]).map((point) => [
                    point.date,
                    point,
                ]),
            ),
        ]),
    );
    for (const wave of waves) {
        reference(wave.securityId, securityIds, "wave.securityId");
        reference(wave.sourceId, sourceIds, "wave.sourceId");
        const start = calendarDate(wave.start, "wave.start");
        const observed = calendarDate(
            wave.observedThrough,
            "wave.observedThrough",
        );
        const peak = calendarDate(wave.peakDate, "wave.peakDate");
        if (start > observed || peak < start || peak > observed)
            fail("wave", "start/peak/observation dates are inconsistent");
        const prices = pricesBySecurity.get(wave.securityId)!;
        const peakPrice = prices.get(peak);
        const observedPrices = intervalPrices(dates, prices, start, observed);
        // A partial series remains readable, with an unknown peak return. Even
        // there, a known higher quote must not be labelled below the maximum.
        if (
            validPrice(peakPrice) &&
            observedPrices.points.some(
                (point) => validPrice(point) && point.close > peakPrice.close,
            )
        )
            fail("wave.peakDate", "declared peak is not an interval maximum");
        bool(wave.leftCensored, "wave.leftCensored");
        bool(wave.rightCensored, "wave.rightCensored");
        string(wave.scale, "wave.scale");
        if (wave.parentId !== null) {
            reference(wave.parentId, waveIds, "wave.parentId");
            const parent = waves.find((entry) => entry.id === wave.parentId)!;
            if (
                wave.parentId === wave.id ||
                parent.securityId !== wave.securityId
            )
                fail(
                    "wave.parentId",
                    "parent must be another wave of the same security",
                );
        }
        if (wave.launch === null)
            string(wave.launchMissingReason, "wave.launchMissingReason");
        else {
            const launch = object(wave.launch, "wave.launch");
            const launched = calendarDate(launch.date, "wave.launch.date");
            const from = calendarDate(
                launch.rangeFrom,
                "wave.launch.rangeFrom",
            );
            const until = calendarDate(
                launch.rangeUntil,
                "wave.launch.rangeUntil",
            );
            if (
                launched < start ||
                launched > observed ||
                from > launched ||
                until < launched
            )
                fail("wave.launch", "launch date/range is inconsistent");
            reference(launch.sourceId, sourceIds, "wave.launch.sourceId");
            if (wave.launchMissingReason !== null)
                string(wave.launchMissingReason, "wave.launchMissingReason");
        }
        if (wave.endConfirmedAt !== null) {
            const end = calendarDate(
                wave.endConfirmedAt,
                "wave.endConfirmedAt",
            );
            if (
                end <= start ||
                end < peak ||
                end > observed ||
                (wave.launch !== null &&
                    end <= String(object(wave.launch, "wave.launch").date))
            )
                fail(
                    "wave.endConfirmedAt",
                    "end confirmation must follow start/launch, be at or after peak, and be observed",
                );
        }
        const phaseEndExclusive =
            wave.endConfirmedAt === null
                ? new Date(Date.parse(`${observed}T00:00:00Z`) + 86400000)
                      .toISOString()
                      .slice(0, 10)
                : String(wave.endConfirmedAt);
        const phases = records(wave.phases, "wave.phases");
        for (const phase of phases) {
            interval(phase, "phase");
            choice(
                phase.kind,
                ["slow", "rising", "resting", "retreat"],
                "phase.kind",
            );
            if (String(phase.from) < start)
                fail("phase.from", "phase precedes wave start");
            if (String(phase.from) >= phaseEndExclusive)
                fail("phase.from", "phase starts beyond wave observation/end");
            if (String(phase.untilExclusive) > phaseEndExclusive)
                fail(
                    "phase.untilExclusive",
                    "phase exceeds wave observation/end",
                );
        }
        nonOverlapping(phases, null, "phases");
    }
    // A cycle cannot encode an auditable parent/child scale relationship.
    for (const wave of waves) {
        const visited = new Set<unknown>([wave.id]);
        let parent = wave.parentId;
        while (parent !== null) {
            if (visited.has(parent))
                fail("wave.parentId", "cycle in wave hierarchy");
            visited.add(parent);
            parent = waves.find((entry) => entry.id === parent)!.parentId;
        }
    }
    const representatives = records(bundle.representatives, "representatives");
    for (const representative of representatives) {
        interval(representative, "representative");
        reference(
            representative.securityId,
            securityIds,
            "representative.securityId",
        );
        reference(representative.waveId, waveIds, "representative.waveId");
        if (
            waves.find((wave) => wave.id === representative.waveId)!
                .securityId !== representative.securityId
        )
            fail("representative", "wave belongs to another security");
    }
    nonOverlapping(representatives, "securityId", "representatives");
    const portfolios = records(bundle.portfolios, "portfolios");
    unique(portfolios, "id", "portfolios");
    for (const portfolio of portfolios) {
        string(portfolio.name, "portfolio.name");
        string(portfolio.description, "portfolio.description");
        choice(
            portfolio.kind,
            ["strategy", "tw-etf", "us-etf"],
            "portfolio.kind",
        );
        strings(portfolio.limitations, "portfolio.limitations");
        for (const sourceId of array(
            portfolio.sourceIds,
            "portfolio.sourceIds",
        ))
            reference(sourceId, sourceIds, "portfolio.sourceIds");
        for (const coverage of records(
            portfolio.coverage,
            "portfolio.coverage",
        )) {
            interval(coverage, "coverage");
            choice(
                coverage.completeness,
                ["full", "partial"],
                "coverage.completeness",
            );
            choice(
                coverage.kind,
                ["daily", "snapshot", "event-replay"],
                "coverage.kind",
            );
            reference(coverage.sourceId, sourceIds, "coverage.sourceId");
            if (
                coverage.kind === "snapshot" &&
                Date.parse(String(coverage.untilExclusive)) -
                    Date.parse(String(coverage.from)) !==
                    DAY_MS
            )
                fail(
                    "coverage",
                    "snapshot coverage must cover exactly one calendar day",
                );
        }
        for (const holding of records(
            portfolio.holdings,
            "portfolio.holdings",
        )) {
            interval(holding, "holding");
            string(holding.securityId, "holding.securityId");
            reference(holding.sourceId, sourceIds, "holding.sourceId");
            if (
                holding.quantity !== undefined &&
                number(holding.quantity, "holding.quantity", 0) === 0
            )
                fail(
                    "holding.quantity",
                    "holding intervals require a positive quantity",
                );
        }
        const allocations = records(
            portfolio.allocations,
            "portfolio.allocations",
        );
        unique(allocations, "date", "allocations");
        for (const allocation of allocations) {
            calendarDate(allocation.date, "allocation.date");
            choice(
                allocation.completeness,
                ["full", "partial"],
                "allocation.completeness",
            );
            reference(allocation.sourceId, sourceIds, "allocation.sourceId");
            if (
                allocation.nav !== null &&
                number(allocation.nav, "allocation.nav", 0) === 0
            )
                fail("allocation.nav", "must be positive or null");
            let total =
                allocation.cashWeight === null
                    ? 0
                    : number(
                          allocation.cashWeight,
                          "allocation.cashWeight",
                          0,
                          1,
                      );
            const hasOtherAssets =
                allocation.otherAssetsWeight !== undefined &&
                allocation.otherAssetsWeight !== null;
            if (hasOtherAssets)
                total += number(
                    allocation.otherAssetsWeight,
                    "allocation.otherAssetsWeight",
                    0,
                    1,
                );
            const positions = records(
                allocation.positions,
                "allocation.positions",
            );
            unique(positions, "securityId", "allocation.positions");
            for (const position of positions)
                total += number(position.weight, "position.weight", 0, 1);
            if (total > 1 + WEIGHT_TOLERANCE)
                fail("allocation", "weights exceed 100 percent");
            if (
                allocation.completeness === "full" &&
                allocation.cashWeight !== null &&
                hasOtherAssets &&
                Math.abs(total - 1) > WEIGHT_TOLERANCE
            )
                fail(
                    "allocation",
                    "full allocation weights must reconcile to 100 percent",
                );
        }
        if (portfolio.method !== undefined) {
            const method = object(portfolio.method, "portfolio.method");
            for (const key of ["taskId", "ruleVersion", "conclusion"])
                string(method[key], `method.${key}`);
            choice(
                method.status,
                ["exploratory", "failed", "incomplete", "accepted"],
                "method.status",
            );
            strings(method.rules, "method.rules");
            strings(method.limitations, "method.limitations");
            for (const [key, parameter] of Object.entries(
                object(method.parameters, "method.parameters"),
            )) {
                if (
                    typeof parameter !== "string" &&
                    typeof parameter !== "boolean" &&
                    !(
                        typeof parameter === "number" &&
                        Number.isFinite(parameter)
                    )
                )
                    fail(
                        `method.parameters.${key}`,
                        "expected string, boolean or finite number",
                    );
            }
            for (const key of ["missionPath", "reportPath"])
                if (method[key] !== undefined)
                    string(method[key], `method.${key}`);
        }
    }
    return value as OpportunityBundle;
}
