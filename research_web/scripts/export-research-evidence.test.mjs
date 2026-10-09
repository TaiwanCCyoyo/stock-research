import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
    access,
    mkdir,
    mkdtemp,
    readFile,
    rm,
    writeFile,
} from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { gunzipSync, gzipSync } from "node:zlib";
import { test } from "node:test";
import {
    joinResearchEvidence,
    exportResearchEvidence,
} from "./export-research-evidence.mts";
import {
    buildMarketView,
    comparePortfolio,
    getHoldingState,
    validateBundle,
} from "../src/domain/opportunities/model.ts";
import { validateResearchBundle } from "../src/domain/opportunities/research.ts";

const dates = ["2019-01-04", "2019-01-07", "2019-01-08"];
const files = [
    "20261002-add-retry--normal-v1.json",
    "20261002-entry-extension-cap--cap-v1.json",
];
const tasks = ["20261002-add-retry", "20261002-entry-extension-cap"];
const runIds = ["normal-v1", "cap-v1"];
const hash = (value) => createHash("sha256").update(value).digest("hex");
const timestamp = (day, time = "20:00:00") => `${day}T${time}+08:00`;
const provenance = {
    catalogPath: "D:\\fixture\\catalog.json",
    catalogHash: "a".repeat(64),
    receiptPath: "D:\\fixture\\export-receipt.json",
    receiptHash: "b".repeat(64),
};

function catalog() {
    return {
        schema: "opportunity-explorer.v1",
        id: "fixture-catalog",
        label: "Historical fixture",
        kind: "historical-preview",
        asOf: dates[2],
        dates: [...dates],
        priceBasis: "adjusted close",
        catalogCoverage: "case-slice",
        ruleVersion: "rules.v1",
        selectionPolicy: "explicit.v1",
        classificationVersion: "unknown.v1",
        sources: [
            {
                id: "catalog-source",
                label: "Recorded adjusted price fixture",
                hash: "c".repeat(64),
            },
        ],
        limitations: [],
        securities: [
            {
                id: "TW:1234",
                code: "1234",
                name: "Recorded stock",
                market: "TW",
                currency: "TWD",
                industry: [],
                prices: [100, 120, 130].map((close, i) => ({
                    date: dates[i],
                    close,
                    raw: close / 2,
                    flags: [],
                })),
            },
        ],
        waves: [
            {
                id: "wave",
                securityId: "TW:1234",
                start: dates[0],
                launch: {
                    date: dates[0],
                    rangeFrom: dates[0],
                    rangeUntil: dates[0],
                    sourceId: "catalog-source",
                },
                launchMissingReason: null,
                peakDate: dates[2],
                endConfirmedAt: null,
                observedThrough: dates[2],
                leftCensored: false,
                rightCensored: true,
                scale: "large",
                parentId: null,
                sourceId: "catalog-source",
                phases: [],
            },
        ],
        representatives: [
            {
                securityId: "TW:1234",
                waveId: "wave",
                from: dates[0],
                untilExclusive: "2019-01-09",
            },
        ],
        portfolios: [],
    };
}

function ledger(index) {
    const id = `stock:${tasks[index]}:${runIds[index]}`;
    const verdict =
        index === 0
            ? "normal_development_screen_passed_final_validation_not_approved"
            : "candidate_failed";
    const sourceHash = (index ? "d" : "e").repeat(64);
    const position = (code, quantity, nav) => ({
        security_id: code,
        quantity,
        raw_mark_twd: 10,
        market_value_twd: quantity * 10,
        weight_fraction: (quantity * 10) / nav,
        weight_missing_reason: null,
        mark_quality: {
            status: "observed_source_mark",
            modeled_mark: false,
            is_execution_price: false,
            source_id: "observed:synthetic-fixture",
        },
    });
    const state = (
        day,
        quantity,
        outsideQuantity,
        nav,
        cash,
        dividend,
        claims,
        eventCount,
    ) => ({
        portfolio_id: id,
        date: timestamp(day),
        event_count: eventCount,
        cash_twd: cash,
        nav_twd: nav,
        tradable_positions: [
            position("1234", quantity, nav),
            position("9999", outsideQuantity, nav),
        ],
        dividend_receivable_twd: dividend,
        capital_return_receivable_twd: 0,
        share_claims_value_twd: claims,
        receivables: [],
        share_claims: [],
        valuation_reconciliation: {
            recorded_nav_twd: nav,
            replayed_nav_twd: nav,
            difference_twd: 0,
        },
        raw_mark_basis: {
            checkpoint_kind: "daily_evening",
            close_at: timestamp(day, "13:30:00"),
            available_at: timestamp(day, "18:00:00"),
            decision_at: timestamp(day),
        },
    });
    const metrics = {
        endpoint_equity_twd: 2000100,
        endpoint_net_pnl_twd: 100,
        endpoint_net_return_fraction: 0.00005,
        costs_total_twd: 5,
    };
    return {
        schema: "native-ledger-presentation.v1",
        status: "reconciled_accounting_export_not_strategy_approval",
        portfolio_id: id,
        units: {
            money: "TWD",
            weights: "fraction",
            quantities: "shares",
            event_fields: "original source units",
        },
        source_hashes: {
            [`D:\\source-only\\${tasks[index]}\\summary.json`]: sourceHash,
        },
        method_metadata: {
            catalog_record: {
                portfolio_id: id,
                task_id: tasks[index],
                candidate_id: index
                    ? "initial-entry-ret60-cap-50pct-v1"
                    : "one-lot-add-retry-v1",
                run_id: runIds[index],
                scenario: "normal_next_session",
                display_name: index ? "Initial entry cap" : "One add retry",
                kind: "strategy_run",
                is_sample: false,
                method_source: `tasks/${tasks[index]}/mission.md`,
                method_code_commit: "fixed-code",
                packet_sha256: sourceHash,
                report: `tasks/${tasks[index]}/execution.md`,
                execution_status: "complete",
                research_verdict: verdict,
                evidence_status:
                    "saved_outputs_match_receipts_schema_inspected",
                failure_reason: index
                    ? "failed original development screen"
                    : null,
                limitations: ["exposed development period"],
                recorded_metrics: metrics,
            },
            mission_markdown: "# Original recorded mission",
            execution_report_markdown:
                "# Recorded outcome, not strategy approval",
            packet_parameters: {
                schema: index
                    ? "initial-entry-extension-cap-exploration.v1"
                    : "one-lot-add-retry-exploration.v1",
                final_strategy_approved: false,
                initial_cash_cents: 200000000,
                max_positions: 5,
                nested_reference: { original: "retained in source" },
            },
            final_strategy_approved: false,
        },
        daily_states: [
            state(dates[0], 10, 10, 2000000, 1999600, 100, 100, 2),
            state(dates[1], 5, 20, 2000100, 1999700, 50, 100, 3),
        ],
        recorded_nav: [
            { date: timestamp(dates[0]), equity: 2000000 },
            { date: timestamp(dates[1]), equity: 2000100 },
        ],
        events: [
            {
                presentation_event_id: `${id}:event-index:0`,
                source_event_index: 0,
                source_event_id: null,
                order_id: "original-buy",
                source_event: {
                    date: timestamp(dates[0], "09:00:00"),
                    action: "BUY",
                    code: "1234",
                    qty: 10,
                    price: 10,
                    total: -100,
                    order_id: "original-buy",
                    commission_cents: 10,
                    note: "<script>inert evidence text</script>",
                },
            },
            {
                presentation_event_id: `${id}:event-index:1`,
                source_event_index: 1,
                source_event_id: null,
                order_id: null,
                source_event: {
                    date: timestamp(dates[0], "10:00:00"),
                    action: "DIVIDEND_ENTITLEMENT",
                    code: "1234",
                    qualified_qty: 10,
                    total: 0,
                    amount: 100,
                    entitlement_id: "retained-original",
                },
            },
            {
                presentation_event_id: `${id}:event-index:2`,
                source_event_index: 2,
                source_event_id: null,
                order_id: "partial-sell",
                source_event: {
                    date: timestamp(dates[1], "09:00:00"),
                    action: "SELL",
                    code: "1234",
                    qty: 5,
                    price: 10,
                    total: 50,
                    order_id: "partial-sell",
                },
            },
        ],
        recorded_measurement: {
            status: "conditional_endpoint_diagnostic_only",
            initial_capital_twd: 2000000,
            ...metrics,
        },
        validation: {
            daily_states: 2,
            daily_nav_reconciled: 2,
            event_count: 3,
            original_event_fields_retained: true,
            max_abs_nav_difference_twd: 0,
            absolute_tolerance_twd: 1e-6,
            full_original_runtime_and_market_inputs_reverified: false,
        },
        limitations: ["Stored ledger accounting only"],
    };
}

function inputsFor(values = [ledger(0), ledger(1)]) {
    const inputs = values.map((value, i) => ({
        filename: files[i],
        path: `D:\\ledger fixture\\${files[i]}`,
        sha256: hash(JSON.stringify(value)),
        value,
    }));
    const receipt = {
        schema: "native-ledger-presentation-export-receipt.v1",
        status: "complete",
        strategy_runner_executed: false,
        strategy_verdict_changed: false,
        sources_unchanged: true,
        source_hashes: Object.assign(
            {},
            ...values.map((value) => value.source_hashes),
        ),
        outputs: Object.fromEntries(
            inputs.map((input) => [input.filename, input.sha256]),
        ),
        validation: Object.fromEntries(
            inputs.map((input) => [
                input.filename,
                structuredClone(input.value.validation),
            ]),
        ),
    };
    return { inputs, receipt };
}
function adapted(values) {
    const { inputs, receipt } = inputsFor(values);
    return joinResearchEvidence(catalog(), inputs, receipt, provenance);
}

test("joins both original verdicts, complete NAV/events and inert original event details", () => {
    const values = [ledger(0), ledger(1)];
    const before = structuredClone(values);
    const { opportunities, research } = adapted(values);
    assert.deepEqual(values, before);
    validateBundle(opportunities);
    validateResearchBundle(research);
    assert.deepEqual(
        research.runs.map((run) => run.method.status),
        ["exploratory", "failed"],
    );
    assert.ok(
        research.runs.every(
            (run) => run.method.parameters.final_strategy_approved === false,
        ),
    );
    assert.ok(
        opportunities.portfolios
            .filter((portfolio) => portfolio.kind === "strategy")
            .every((portfolio) => portfolio.method.status !== "accepted"),
    );
    assert.equal(
        opportunities.portfolios.filter(
            (portfolio) => portfolio.kind === "strategy",
        ).length,
        2,
    );
    const etfs = opportunities.portfolios.filter(
        (portfolio) => portfolio.kind !== "strategy",
    );
    assert.equal(etfs.length, 6);
    assert.ok(
        etfs.every(
            (portfolio) =>
                portfolio.holdings.length === 0 &&
                portfolio.allocations.length === 0 &&
                portfolio.coverage.length === 0,
        ),
    );
    assert.ok(
        etfs.every(
            (portfolio) =>
                comparePortfolio(
                    opportunities,
                    buildMarketView(opportunities, dates[1]),
                    portfolio,
                ).capital.status === "unknown",
        ),
    );
    assert.equal(research.runs[0].nav.length, 2);
    assert.equal(research.runs[0].events.length, 3);
    assert.deepEqual(
        research.runs[0].events[0].original,
        values[0].events[0].source_event,
    );
    assert.equal(research.runs[0].events[1].action, "DIVIDEND_ENTITLEMENT");
    assert.equal(research.runs[0].events[1].quantity, null);
    assert.equal(research.runs[0].events[1].cashFlow, 0);
    assert.equal(research.runs[0].netReturn, 0.00005);
    assert.equal(research.runs[0].costs, 5);
    assert.deepEqual(opportunities.securities, catalog().securities);
    assert.equal(opportunities.securities.length, 1);
});

test("partial sale leaves positive holdings; snapshots do not fill weekends or missing dates", () => {
    const { opportunities } = adapted();
    const portfolio = opportunities.portfolios[0];
    assert.equal(
        portfolio.holdings.find(
            (entry) =>
                entry.securityId === "TW:1234" && entry.from === dates[0],
        ).quantity,
        10,
    );
    assert.equal(
        portfolio.holdings.find(
            (entry) =>
                entry.securityId === "TW:1234" && entry.from === dates[1],
        ).quantity,
        5,
    );
    assert.equal(getHoldingState(portfolio, "TW:1234", dates[1]), "held");
    assert.equal(getHoldingState(portfolio, "TW:absent", dates[1]), "not-held");
    assert.equal(
        getHoldingState(portfolio, "TW:1234", "2019-01-05"),
        "unknown",
    );
    assert.equal(
        getHoldingState(portfolio, "TW:1234", "2019-01-06"),
        "unknown",
    );
    assert.equal(getHoldingState(portfolio, "TW:1234", dates[2]), "unknown");
    assert.ok(
        portfolio.coverage.every((interval) => interval.kind === "snapshot"),
    );
    assert.equal(
        comparePortfolio(
            opportunities,
            buildMarketView(opportunities, dates[2]),
            portfolio,
        ).capital.status,
        "unknown",
    );
});

test("cash, tradable stock and receivable/claim weights retain exact NAV denominator without fake assets", () => {
    const { opportunities } = adapted();
    const portfolio = opportunities.portfolios[0];
    const snapshot = portfolio.allocations[1];
    assert.equal(snapshot.nav, 2000100);
    assert.equal(snapshot.cashWeight, 1999700 / 2000100);
    assert.equal(snapshot.otherAssetsWeight, 150 / 2000100);
    assert.deepEqual(snapshot.positions, [
        { securityId: "TW:1234", weight: 50 / 2000100 },
        { securityId: "TW:9999", weight: 200 / 2000100 },
    ]);
    const capital = comparePortfolio(
        opportunities,
        buildMarketView(opportunities, dates[1]),
        portfolio,
    ).capital;
    assert.equal(capital.status, "partial");
    assert.equal(capital.opportunityWeight, 50 / 2000100);
    assert.equal(capital.otherAssetsWeight, 150 / 2000100);
    assert.equal(capital.otherWeight, 0);
    assert.ok(Math.abs(capital.unknownWeight - 200 / 2000100) < 1e-12);
    assert.ok(
        !opportunities.securities.some((security) => security.id === "TW:9999"),
    );
});

test("hash mismatch, changed approval/verdict and broken accounting reject before output", () => {
    const { inputs, receipt } = inputsFor();
    inputs[0].sha256 = "0".repeat(64);
    assert.throws(
        () => joinResearchEvidence(catalog(), inputs, receipt, provenance),
        /SHA-256 mismatch/,
    );
    const changes = [
        (value) => {
            value.method_metadata.final_strategy_approved = true;
        },
        (value) => {
            value.method_metadata.catalog_record.research_verdict = "accepted";
        },
        (value) => {
            value.daily_states[0].cash_twd += 10;
        },
        (value) => {
            value.daily_states[0].tradable_positions[0].quantity = 0;
        },
        (value) => {
            value.daily_states[0].tradable_positions[0].weight_fraction = 0.5;
        },
        (value) => {
            value.daily_states[0].tradable_positions.push(
                structuredClone(value.daily_states[0].tradable_positions[0]),
            );
        },
        (value) => {
            value.daily_states[1].date = timestamp(dates[0]);
        },
        (value) => {
            value.daily_states[0].raw_mark_basis.available_at = timestamp(
                dates[0],
                "21:00:00",
            );
        },
        (value) => {
            value.events[1].source_event_index = 2;
        },
        (value) => {
            value.recorded_nav[1].equity += 10;
        },
    ];
    for (const change of changes) {
        const values = [ledger(0), ledger(1)];
        change(values[0]);
        assert.throws(() => adapted(values), /Invalid research evidence/);
    }
});

test("matching receipt and ledger declarations must still assert success and reconcile actual counts", () => {
    for (const index of [0, 1]) {
        for (const changes of [
            { original_event_fields_retained: false },
            { original_event_fields_retained: null },
            { original_event_fields_retained: "true" },
            { original_event_fields_retained: undefined },
            { daily_states: 999 },
            { daily_nav_reconciled: 999 },
            { event_count: 999 },
        ]) {
            const values = [ledger(0), ledger(1)];
            Object.assign(values[index].validation, changes);
            const { inputs, receipt } = inputsFor(values);
            assert.deepEqual(
                receipt.validation[files[index]],
                values[index].validation,
            );
            assert.throws(
                () =>
                    joinResearchEvidence(
                        catalog(),
                        inputs,
                        receipt,
                        provenance,
                    ),
                /reconciled row\/event counts mismatch/,
            );
        }
    }
    const values = [ledger(0), ledger(1)];
    values[0].validation.additional_diagnostic = false;
    const original = structuredClone(values);
    assert.equal(
        values[0].validation.full_original_runtime_and_market_inputs_reverified,
        false,
    );
    assert.doesNotThrow(() => adapted(values));
    assert.deepEqual(values, original);
});

test("observed marks require a source identity that does not declare modeling", () => {
    for (const source of [
        undefined,
        null,
        "",
        " ",
        "modeled:estimate",
        " modeled:estimate",
    ]) {
        const values = [ledger(0), ledger(1)];
        values[0].daily_states[0].tradable_positions[0].mark_quality.source_id =
            source;
        assert.throws(
            () => adapted(values),
            /mark_quality.source_id|observed mark cannot/,
        );
    }
});

test("positive holdings reject a zero source mark even when all NAV and weight arithmetic balances", () => {
    for (const index of [0, 1]) {
        const values = [ledger(0), ledger(1)];
        const state = values[index].daily_states[0];
        const position = state.tradable_positions[0];
        state.cash_twd += position.market_value_twd;
        position.raw_mark_twd = 0;
        position.market_value_twd = 0;
        position.weight_fraction = 0;
        assert.equal(position.quantity > 0, true);
        const original = structuredClone(values);
        assert.throws(
            () => adapted(values),
            /positive quantity.*positive raw mark/,
        );
        assert.deepEqual(values, original);
    }
});

test("zero-quantity rows retain their legal zero mark and value without creating holdings", () => {
    const values = [ledger(0), ledger(1)];
    const state = values[0].daily_states[0];
    const position = state.tradable_positions[0];
    state.cash_twd += position.market_value_twd;
    position.quantity = 0;
    position.raw_mark_twd = 0;
    position.market_value_twd = 0;
    position.weight_fraction = 0;
    const original = structuredClone(values);
    const { opportunities } = adapted(values);
    const portfolio = opportunities.portfolios[0];
    assert.equal(portfolio.allocations[0].positions[0].weight, 0);
    assert.equal(
        portfolio.holdings.some(
            (entry) =>
                entry.securityId === "TW:1234" && entry.from === dates[0],
        ),
        false,
    );
    assert.deepEqual(values, original);
});

test("full allocations require consistent observed or named modeled mark declarations", () => {
    for (const index of [0, 1]) {
        for (const modeled of [false, true]) {
            for (const [key, invalidValues] of [
                ["status", [undefined, null, "", "modeled_mark", true]],
                ["modeled_mark", [undefined, null, !modeled, "false", 0]],
                ["is_execution_price", [undefined, null, true, "false", 0]],
            ]) {
                for (const invalid of invalidValues) {
                    const values = [ledger(0), ledger(1)];
                    const quality =
                        values[index].daily_states[0].tradable_positions[0]
                            .mark_quality;
                    if (modeled)
                        Object.assign(quality, {
                            status: "named_modeled_mark",
                            modeled_mark: true,
                            source_id: "modeled:retained-source-identity",
                        });
                    if (invalid === undefined) delete quality[key];
                    else quality[key] = invalid;
                    const original = structuredClone(values);
                    assert.throws(
                        () => adapted(values),
                        /mark_quality declarations/,
                    );
                    assert.deepEqual(values, original);
                }
            }
        }
    }
});

test("named modeled marks require their recorded modeled source identity", () => {
    for (const index of [0, 1]) {
        for (const sourceId of [
            undefined,
            null,
            "",
            " ",
            "modeled:",
            "observed:source",
            12,
            {},
        ]) {
            const values = [ledger(0), ledger(1)];
            const quality =
                values[index].daily_states[0].tradable_positions[0]
                    .mark_quality;
            Object.assign(quality, {
                status: "named_modeled_mark",
                modeled_mark: true,
            });
            if (sourceId !== undefined) quality.source_id = sourceId;
            assert.throws(() => adapted(values), /mark_quality.source_id/);
        }
    }
});

test("named modeled marks retain values and full allocations with explicit valuation limitations", () => {
    const values = [ledger(0), ledger(1)];
    const baseline = adapted(values);
    for (const value of values)
        Object.assign(
            value.daily_states[0].tradable_positions[0].mark_quality,
            {
                status: "named_modeled_mark",
                modeled_mark: true,
                source_id:
                    "modeled:last-observed-close-on-confirmed-single-session-halt-v1|retained",
                additional_diagnostic: false,
            },
        );
    const original = structuredClone(values);
    const { opportunities, research } = adapted(values);
    assert.deepEqual(values, original);
    for (const index of [0, 1]) {
        const run = research.runs[index];
        assert.deepEqual(run.nav, baseline.research.runs[index].nav);
        assert.deepEqual(run.events, baseline.research.runs[index].events);
        assert.deepEqual(
            opportunities.portfolios[index].allocations,
            baseline.opportunities.portfolios[index].allocations,
        );
        assert.deepEqual(
            opportunities.portfolios[index].holdings,
            baseline.opportunities.portfolios[index].holdings,
        );
        assert.match(run.valuationBasis, /具名模型估值/);
        assert.equal(
            run.limitations.filter(
                (text) =>
                    /1 筆具名模型估值/.test(text) &&
                    text.includes(dates[0]) &&
                    text.includes("TW:1234"),
            ).length,
            1,
        );
        assert.equal(
            baseline.research.runs[index].limitations.some((text) =>
                /具名模型估值/.test(text),
            ),
            false,
        );
    }
    assert.equal(
        opportunities.limitations.filter((text) =>
            /1 筆具名模型估值/.test(text),
        ).length,
        2,
    );
});

test("additional mark diagnostics remain open and native events stay unchanged", () => {
    const values = [ledger(0), ledger(1)];
    for (const value of values) {
        Object.assign(
            value.daily_states[0].tradable_positions[0].mark_quality,
            {
                additional_diagnostic: false,
                other_diagnostic: true,
                source_detail: { retained: "source metadata" },
            },
        );
    }
    const original = structuredClone(values);
    const { opportunities, research } = adapted(values);
    assert.deepEqual(values, original);
    for (let index = 0; index < values.length; index++) {
        assert.equal(
            opportunities.portfolios[index].allocations[0].completeness,
            "full",
        );
        assert.deepEqual(
            research.runs[index].events.map((event) => event.original),
            original[index].events.map((event) => event.source_event),
        );
    }
});

test("packet hash must match the same ledger's verified native sources", () => {
    for (const index of [0, 1]) {
        for (const replacement of ["unknown", "receipt-only", "other-run"]) {
            const values = [ledger(0), ledger(1)];
            const packetHash =
                replacement === "other-run"
                    ? values[1 - index].method_metadata.catalog_record
                          .packet_sha256
                    : "f".repeat(64);
            values[index].method_metadata.catalog_record.packet_sha256 =
                packetHash;
            // Rebuild both the ledger byte identities and their matching receipt;
            // only the packet-to-native-source relationship is invalid.
            const { inputs, receipt } = inputsFor(values);
            if (replacement === "receipt-only")
                receipt.source_hashes["D:\\receipt-only\\packet.json"] =
                    packetHash;
            assert.throws(
                () =>
                    joinResearchEvidence(
                        catalog(),
                        inputs,
                        receipt,
                        provenance,
                    ),
                /packet hash must match a verified native source of this ledger/,
                `ledger ${index}: ${replacement}`,
            );
        }
    }
});

test("daily event prefixes reject both future events and delayed past events", () => {
    for (const index of [0, 1]) {
        for (const count of [1, 3]) {
            const values = [ledger(0), ledger(1)];
            // Two events have occurred at the first checkpoint. The third is
            // on the next snapshot day; the final count still covers all three.
            values[index].daily_states[0].event_count = count;
            assert.throws(
                () => adapted(values),
                /daily event prefix must include exactly the events at or before the checkpoint/,
            );
        }
    }
});

test("daily event prefixes use full timestamps and include every equal-time event", () => {
    const boundaries = [
        { time: "19:59:59", count: 2, sameTime: false },
        { time: "20:00:00", count: 2, sameTime: false },
        { time: "20:00:01", count: 1, sameTime: false },
        { time: "20:00:00", count: 3, sameTime: true },
    ];
    for (const index of [0, 1]) {
        for (const boundary of boundaries) {
            const values = [ledger(0), ledger(1)];
            const value = values[index];
            value.events[1].source_event.date = timestamp(
                dates[0],
                boundary.time,
            );
            if (boundary.sameTime)
                value.events[2].source_event.date =
                    value.events[1].source_event.date;
            value.daily_states[0].event_count = boundary.count;
            const { research } = adapted(values);
            assert.deepEqual(
                research.runs[index].events.map((event) => event.original),
                value.events.map((event) => event.source_event),
            );
            value.daily_states[0].event_count =
                boundary.count === 1 ? 2 : boundary.count - 1;
            assert.throws(
                () => adapted(values),
                /daily event prefix must include exactly the events at or before the checkpoint/,
            );
        }
    }
});

test("event timestamps must be finite explicit Taipei times in source chronology", () => {
    for (const index of [0, 1]) {
        for (const invalid of [
            "not-a-timestamp",
            "2019-01-04T10:00:00",
            "2019-01-04T25:00:00+08:00",
            "2019-01-04T24:00:00+08:00",
            "2019-02-30T10:00:00+08:00",
        ]) {
            const values = [ledger(0), ledger(1)];
            values[index].events[1].source_event.date = invalid;
            assert.throws(() => adapted(values), /event date/);
        }
        for (const outOfOrder of [
            timestamp(dates[0], "08:59:59"),
            timestamp("2019-01-03", "10:00:00"),
        ]) {
            const values = [ledger(0), ledger(1)];
            values[index].events[1].source_event.date = outOfOrder;
            assert.throws(
                () => adapted(values),
                /event timestamps must be chronological in source index order/,
            );
        }
    }
});

test("daily checkpoints must match the declared 20:00 Taipei valuation basis", () => {
    for (const index of [0, 1]) {
        for (const time of ["19:59:59", "20:00:01"]) {
            const values = [ledger(0), ledger(1)];
            const checkpoint = timestamp(dates[0], time);
            values[index].daily_states[0].date = checkpoint;
            values[index].daily_states[0].raw_mark_basis.decision_at =
                checkpoint;
            values[index].recorded_nav[0].date = checkpoint;
            assert.throws(
                () => adapted(values),
                /daily state must be at 20:00:00\+08:00/,
            );
        }
    }
});

test("final daily snapshot must account for a trailing trade even when receipt counts match", () => {
    for (const index of [0, 1]) {
        const values = [ledger(0), ledger(1)];
        const value = values[index];
        const trailing = structuredClone(value.events.at(-1));
        trailing.presentation_event_id = `${value.portfolio_id}:event-index:3`;
        trailing.source_event_index = 3;
        trailing.order_id = "unaccounted-tail-sell";
        trailing.source_event = {
            ...trailing.source_event,
            date: timestamp(dates[1], "10:00:00"),
            qty: 1,
            total: 10,
            order_id: trailing.order_id,
        };
        value.events.push(trailing);
        value.validation.event_count = value.events.length;
        // inputsFor regenerates matching hashes and receipt counts. The saved
        // daily states still consume only the original three-event prefix.
        assert.equal(value.daily_states.at(-1).event_count, 3);
        assert.equal(value.events.length, 4);
        assert.throws(
            () => adapted(values),
            /daily event prefix must include exactly the events at or before the checkpoint/,
        );
        // A tail after the final checkpoint is correctly excluded by its
        // timestamp, but the ledger still lacks a snapshot covering that tail.
        trailing.source_event.date = timestamp(dates[1], "21:00:00");
        assert.throws(
            () => adapted(values),
            /final daily state must account for all events/,
        );
    }
});

test("catalog intersection only limits allocations, never original NAV or events", () => {
    const { inputs, receipt } = inputsFor();
    const source = catalog();
    source.dates = [dates[0], dates[2]];
    source.securities[0].prices.splice(1, 1);
    const { opportunities, research } = joinResearchEvidence(
        source,
        inputs,
        receipt,
        provenance,
    );
    assert.equal(opportunities.portfolios[0].allocations.length, 1);
    assert.equal(opportunities.portfolios[0].coverage.length, 2);
    assert.equal(research.runs[0].nav.length, 2);
    assert.equal(research.runs[0].events.length, 3);
    assert.ok(
        opportunities.portfolios[0].limitations.some((limitation) =>
            limitation.includes("1 個帳本日期"),
        ),
    );
});

async function fileFixture() {
    const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
    await mkdir(join(root, ".tmp"), { recursive: true });
    const directory = await mkdtemp(join(root, ".tmp", "research evidence "));
    const ledgerDir = join(directory, "ledger inputs");
    await mkdir(ledgerDir);
    const inputCatalog = join(directory, "catalog input.json.gz");
    await writeFile(
        inputCatalog,
        gzipSync(Buffer.from(JSON.stringify(catalog()))),
    );
    const { inputs, receipt } = inputsFor();
    for (const input of inputs)
        await writeFile(
            join(ledgerDir, input.filename),
            JSON.stringify(input.value),
        );
    await writeFile(
        join(ledgerDir, "export-receipt.json"),
        JSON.stringify(receipt),
    );
    return { directory, ledgerDir, inputCatalog };
}

test("CLI verifies source hashes, writes genuine gzip/optional JSON, and never overwrites a directory", async () => {
    const { directory, ledgerDir, inputCatalog } = await fileFixture();
    const output = join(directory, "new outputs");
    try {
        const script = fileURLToPath(
            new URL("./export-research-evidence.mts", import.meta.url),
        );
        const result = spawnSync(
            process.execPath,
            [
                "--experimental-strip-types",
                script,
                "--catalog",
                inputCatalog,
                "--ledger-dir",
                ledgerDir,
                "--out-dir",
                output,
                "--json",
            ],
            { encoding: "utf8" },
        );
        assert.equal(result.status, 0, result.stderr);
        const receipt = JSON.parse(result.stdout);
        for (const [filename, expected] of Object.entries(receipt.outputs))
            assert.equal(
                hash(await readFile(join(output, filename))),
                expected,
            );
        const opportunities = validateBundle(
            JSON.parse(
                gunzipSync(
                    await readFile(
                        join(output, "opportunity-explorer.json.gz"),
                    ),
                ).toString("utf8"),
            ),
        );
        const research = validateResearchBundle(
            JSON.parse(
                gunzipSync(
                    await readFile(join(output, "saved-research-runs.json.gz")),
                ).toString("utf8"),
            ),
        );
        assert.equal(opportunities.portfolios.length, 8);
        assert.equal(research.runs[1].method.status, "failed");
        assert.deepEqual(
            JSON.parse(
                await readFile(
                    join(output, "opportunity-explorer.json"),
                    "utf8",
                ),
            ),
            opportunities,
        );
        const before = await readFile(
            join(output, "saved-research-runs.json.gz"),
        );
        await assert.rejects(
            exportResearchEvidence(inputCatalog, ledgerDir, output),
            /EEXIST|already exists/,
        );
        assert.deepEqual(
            await readFile(join(output, "saved-research-runs.json.gz")),
            before,
        );
        await assert.rejects(
            exportResearchEvidence(inputCatalog, ledgerDir, ledgerDir),
            /EEXIST|already exists/,
        );
    } finally {
        await rm(directory, { recursive: true, force: true });
    }
});

test("file bytes altered after receipt creation fail without creating output", async () => {
    const { directory, ledgerDir, inputCatalog } = await fileFixture();
    const output = join(directory, "must not exist");
    try {
        const first = join(ledgerDir, files[0]);
        const bytes = await readFile(first, "utf8");
        await writeFile(first, `${bytes}\n`);
        await assert.rejects(
            exportResearchEvidence(inputCatalog, ledgerDir, output),
            /SHA-256 mismatch/,
        );
        await assert.rejects(access(output), /ENOENT/);
    } finally {
        await rm(directory, { recursive: true, force: true });
    }
});
