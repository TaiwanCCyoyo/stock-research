/* Pure rules behind the HHHL v4 variants report, kept apart from the drawing code so
   research_web/scripts/hhhl-variants-report.test.mjs can check them against the
   published data. A classic script: it works in the page, from disk and in Node. */
(function (root) {
    "use strict";

    /** hit / known, or null when nothing is known. */
    function rate(row) {
        return row && row.known_n > 0 ? row.hit_n / row.known_n : null;
    }

    /**
     * The comparator PR #9 published for one pattern row.
     *  - matched: the control cohort's row with the same condition.
     *  - unfiltered: a pattern-only condition (Z2, restart, drawn lines…) is only
     *    defined when the pattern exists, so PR #9 compared it with an unfiltered
     *    control: C-52w counts stored on the pattern row, or the C-base baseline.
     *  - self: the same pattern without the condition.
     *  - na / none: no comparator.
     */
    function publishedControl({
        comparator,
        patternRow,
        selfBaseline,
        cBaseBaseline,
        sameConditionRow,
    }) {
        if (comparator === "none") return { r: null, n: null, kind: "none" };
        if (comparator === "self")
            return {
                r: rate(selfBaseline),
                n: selfBaseline ? selfBaseline.known_n : null,
                kind: "self",
            };
        if (
            patternRow &&
            patternRow.reference_kind === "pattern_only_unfiltered"
        ) {
            if (comparator === "C-52w") {
                const n = patternRow.reference_c52w_known_n;
                const r = n > 0 ? patternRow.reference_c52w_hit_n / n : null;
                return { r, n, kind: r === null ? "na" : "unfiltered" };
            }
            if (comparator === "C-base") {
                const r = rate(cBaseBaseline);
                return {
                    r,
                    n: cBaseBaseline ? cBaseBaseline.known_n : null,
                    kind: r === null ? "na" : "unfiltered",
                };
            }
            return { r: null, n: null, kind: "na" };
        }
        const r = rate(sameConditionRow);
        return {
            r,
            n: sameConditionRow ? sameConditionRow.known_n : null,
            kind: r === null ? "na" : "matched",
        };
    }

    /** One place changes the chosen signal, so the chart, table and menu agree. */
    function selectFlag(state, id, menu, rerender) {
        state.flag = id;
        if (menu) menu.value = id;
        rerender();
    }

    /**
     * Start years with any known outcome for one cohort and horizon. A year is
     * partial when some of its events still have open windows (censored): its known
     * part holds only earlier starts whose windows have ended, so it is not a
     * full-year rate.
     */
    function yearSeries(yearRows, cohort, horizon) {
        return yearRows
            .filter(
                (r) =>
                    r.cohort_id === cohort &&
                    r.horizon === horizon &&
                    r.known_n > 0,
            )
            .sort((a, b) => a.year - b.year)
            .map((r) => ({
                year: r.year,
                rate: rate(r),
                known: r.known_n,
                hit: r.hit_n,
                censored: r.censored_n || 0,
                partial: (r.censored_n || 0) > 0,
            }));
    }

    root.HhhlReportModel = { rate, publishedControl, selectFlag, yearSeries };
})(typeof window !== "undefined" ? window : globalThis);
