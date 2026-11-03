import test from "node:test";
import assert from "node:assert/strict";
import {
    comparisonBack,
    comparisonSourceHref,
    restoreComparisonEntrance,
    comparisonEntryHref,
    comparisonHref,
    parseComparisonLocation,
    validateComparisonLocation,
} from "./journey.ts";
import { syntheticComparison as view } from "./fixture.ts";
import { initialSelection } from "./model.ts";
import { readRegisteredComparison } from "./registry.ts";
import { studioRoute } from "../../app/routes.ts";

test("registered saved result is exact and does not substitute unknown or pending producer data", () => {
    assert.equal(readRegisteredComparison(view.id).status, "ready");
    assert.equal(
        readRegisteredComparison("l1-volume-comparison.v1").status,
        "error",
    );
    assert.equal(
        readRegisteredComparison("https://example.com/result").status,
        "error",
    );
});
test("URL carries selected horizon, group, filter, page, sort, event and bounded return", () => {
    const selection = {
        ...initialSelection(view),
        page: 1,
        eventId: "demo-01",
    };
    const back = "#studies?q=量縮&filter=report&study=20261013-pattern-scan";
    const href = comparisonHref(selection, back, "demo-01");
    const route = parseComparisonLocation(href);
    assert.equal(studioRoute(href).page, "condition-comparison");
    assert.deepEqual(route.selection, selection);
    assert.equal(validateComparisonLocation(view, route)?.eventId, "demo-01");
    assert.equal(
        new URLSearchParams(route.back.split("?")[1]).get("q"),
        "量縮",
    );
    const returned = parseComparisonLocation(
        comparisonHref(route.selection, route.back),
    );
    assert.equal(returned.openCase, undefined);
    assert.deepEqual(returned.selection, selection);
});
test("refresh and repeated case returns reconstruct exactly the same saved selection", () => {
    const selection = {
        ...initialSelection(view),
        group: "both" as const,
        filter: "hit" as const,
        eventId: "demo-01",
    };
    const back = "#report/20261013-pattern-scan";
    for (let repeat = 0; repeat < 3; repeat++) {
        const route = parseComparisonLocation(
            comparisonHref(selection, back, "demo-01"),
        );
        assert.equal(
            validateComparisonLocation(view, route)?.effectiveLabel,
            "hit",
        );
        assert.deepEqual(
            parseComparisonLocation(comparisonHref(route.selection, route.back))
                .selection,
            selection,
        );
    }
});
test("malformed routes, stale identity and mismatching case context fail explicitly", () => {
    const base = comparisonEntryHref(view, "#studies");
    for (const suffix of [
        "&h=252",
        "&unknown=1",
        "&page=-1",
        "&source=private",
    ])
        assert.throws(() => parseComparisonLocation(base + suffix));
    assert.throws(() =>
        parseComparisonLocation("#condition-comparison?result=%zz"),
    );
    for (const selection of [
        { ...initialSelection(view), page: 50 },
        {
            ...initialSelection(view),
            group: "both" as const,
            eventId: "demo-02",
        },
        {
            ...initialSelection(view),
            filter: "unknown" as const,
            eventId: "demo-01",
        },
        { ...initialSelection(view), resultId: "other" },
    ])
        assert.throws(() =>
            validateComparisonLocation(
                view,
                parseComparisonLocation(comparisonHref(selection)),
            ),
        );
    const missingReader = { ...initialSelection(view), eventId: "demo-03" };
    assert.throws(() =>
        validateComparisonLocation(
            view,
            parseComparisonLocation(
                comparisonHref(missingReader, "#studies", "demo-03"),
            ),
        ),
    );
});
test("safe return never accepts external or arbitrary internal navigation", () => {
    for (const back of [
        "https://example.com",
        "javascript:alert(1)",
        "#overview",
        "#stock/2330",
        "#report/../private",
        "#report/%2fprivate",
    ])
        assert.equal(comparisonBack(back), "#studies");
    assert.equal(comparisonBack("#studies?q=test&evil=1"), "#studies?q=test");
    assert.equal(
        comparisonBack("#report/20261013-pattern-scan"),
        "#report/20261013-pattern-scan",
    );
});

test("source focus survives direct entry, refresh and repeated returns without storage", () => {
    const original = Object.getOwnPropertyDescriptor(
        globalThis,
        "sessionStorage",
    );
    Object.defineProperty(globalThis, "sessionStorage", {
        configurable: true,
        get() {
            throw new Error("Storage unavailable");
        },
    });
    try {
        for (const back of [
            "#studies?q=volume&filter=all",
            "#report/20261013-pattern-scan",
        ]) {
            let focused = 0;
            let scrolled = 0;
            const entrance = {
                focus(options: FocusOptions) {
                    assert.equal(options.preventScroll, true);
                    focused++;
                },
                scrollIntoView(options: ScrollIntoViewOptions) {
                    assert.equal(options.block, "center");
                    scrolled++;
                },
            };
            // Direct comparison entry has no entrance-click or stored marker.
            const direct = comparisonEntryHref(view, back);
            for (let visit = 1; visit <= 3; visit++) {
                const route = parseComparisonLocation(direct);
                const returned = comparisonSourceHref(route.back);
                restoreComparisonEntrance(
                    returned,
                    comparisonBack(returned),
                    entrance,
                );
                assert.equal(focused, visit);
                assert.equal(scrolled, visit);
                assert.equal(comparisonBack(returned), comparisonBack(back));
            }
            restoreComparisonEntrance(back, back, entrance);
            restoreComparisonEntrance("#studies?focus=other", back, entrance);
            assert.equal(
                focused,
                3,
                "ordinary source visits do not steal focus",
            );
        }
    } finally {
        if (original)
            Object.defineProperty(globalThis, "sessionStorage", original);
        else Reflect.deleteProperty(globalThis, "sessionStorage");
    }
});
test("source focus markers preserve bounded destinations", () => {
    assert.equal(
        comparisonSourceHref("https://example.com"),
        "#studies?focus=comparison",
    );
    assert.equal(
        comparisonBack("#report/../private?focus=comparison"),
        "#studies",
    );
    assert.equal(
        comparisonBack("#report/20261013-pattern-scan?focus=comparison&evil=1"),
        "#studies",
    );
    assert.equal(
        comparisonSourceHref("#studies?q=test&evil=1"),
        "#studies?q=test&focus=comparison",
    );
});
