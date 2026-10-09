import type { LabBundle, LabPoint } from "./types.ts";

function validAdjustedPrice(
    point: LabPoint | undefined,
): point is LabPoint & { adjusted: number } {
    return (
        point !== undefined &&
        point.adjusted !== null &&
        Number.isFinite(point.adjusted) &&
        point.adjusted > 0 &&
        point.flags.length === 0
    );
}

/** Validate saved JSON before any case reaches the chart, analysis or feedback. */
export function validateLabBundle(value: unknown): LabBundle {
    const fail = (path: string): never => {
        throw new Error(`案例格式不符：${path}`);
    };
    const record = (entry: unknown, path: string): Record<string, unknown> => {
        if (!entry || typeof entry !== "object" || Array.isArray(entry))
            return fail(path);
        return entry as Record<string, unknown>;
    };
    const text = (entry: unknown, path: string): string => {
        if (typeof entry !== "string" || !entry.trim()) return fail(path);
        return entry;
    };
    const date = (entry: unknown, path: string): string => {
        const result = text(entry, path);
        const time = Date.parse(`${result}T00:00:00Z`);
        if (
            !/^\d{4}-\d{2}-\d{2}$/.test(result) ||
            !Number.isFinite(time) ||
            new Date(time).toISOString().slice(0, 10) !== result
        )
            return fail(path);
        return result;
    };
    const strings = (entry: unknown, path: string) => {
        if (
            !Array.isArray(entry) ||
            entry.some((item) => typeof item !== "string")
        )
            fail(path);
    };
    const optionalText = (entry: unknown, path: string) => {
        if (entry !== undefined && typeof entry !== "string") fail(path);
    };
    const bundle = record(value, "bundle");
    if (bundle.schema !== "wave-lab-cases.v1") fail("schema");
    text(bundle.projectionHash, "projectionHash");
    text(bundle.catalogHash, "catalogHash");
    if (!Array.isArray(bundle.cases) || !bundle.cases.length) fail("cases");
    const ids = new Set<string>();
    for (const entry of bundle.cases as unknown[]) {
        const sample = record(entry, "case");
        const id = text(sample.id, "case.id");
        if (ids.has(id)) fail("duplicate case.id");
        ids.add(id);
        for (const key of ["name", "category", "question"])
            text(sample[key], `case.${key}`);
        optionalText(sample.code, "case.code");
        if (sample.kind !== "historical" && sample.kind !== "synthetic")
            fail("case.kind");
        if (!Array.isArray(sample.points) || !sample.points.length)
            fail("case.points");
        const calendar = new Set<string>();
        let previous = "";
        for (const row of sample.points as unknown[]) {
            const point = record(row, "point");
            const day = date(point.date, "point.date");
            if (day <= previous) fail("point.date order");
            calendar.add(day);
            previous = day;
            for (const key of ["raw", "adjusted"]) {
                const price = point[key];
                if (
                    price !== null &&
                    (typeof price !== "number" ||
                        !Number.isFinite(price) ||
                        price <= 0)
                )
                    fail(`point.${key}`);
            }
            strings(point.flags, "point.flags");
        }
        const days = [...calendar];
        const source = record(sample.source, "source");
        text(source.label, "source.label");
        text(source.priceBasis, "source.priceBasis");
        if (
            date(source.from, "source.from") !== days[0] ||
            date(source.to, "source.to") !== days.at(-1)
        )
            fail("source.from/to must match point calendar endpoints");
        strings(source.limitations, "source.limitations");
        for (const key of ["hash", "catalogHash"])
            optionalText(source[key], `source.${key}`);
        if (sample.selectedOpportunity !== undefined) {
            const selected = record(
                sample.selectedOpportunity,
                "selectedOpportunity",
            );
            for (const key of ["securityId", "waveId", "sourceId", "scale"])
                text(selected[key], `selectedOpportunity.${key}`);
            for (const key of ["leftCensored", "rightCensored"])
                if (typeof selected[key] !== "boolean")
                    fail(`selectedOpportunity.${key}`);
            const reference = (entry: unknown, path: string) => {
                const day = date(entry, path);
                if (!calendar.has(day)) fail(`${path} outside point calendar`);
                return day;
            };
            const start = reference(
                selected.start,
                "selectedOpportunity.start",
            );
            const peak = reference(
                selected.peakDate,
                "selectedOpportunity.peakDate",
            );
            const observed = reference(
                selected.observedThrough,
                "selectedOpportunity.observedThrough",
            );
            if (start > peak || peak > observed)
                fail("selectedOpportunity boundaries");
            const points = sample.points as LabPoint[];
            const peakPoint = points.find((point) => point.date === peak);
            // Partial prices remain readable; only valid known prices contradict a known peak.
            if (
                validAdjustedPrice(peakPoint) &&
                points.some(
                    (point) =>
                        point.date >= start &&
                        point.date <= observed &&
                        validAdjustedPrice(point) &&
                        point.adjusted > peakPoint.adjusted,
                )
            )
                fail("selectedOpportunity.peakDate is not an interval maximum");
            const end =
                selected.endConfirmedAt === null
                    ? null
                    : reference(
                          selected.endConfirmedAt,
                          "selectedOpportunity.endConfirmedAt",
                      );
            if (end !== null && (end <= start || end < peak || end > observed))
                fail("selectedOpportunity.endConfirmedAt boundaries");
            if (selected.launch !== null) {
                const launch = record(
                    selected.launch,
                    "selectedOpportunity.launch",
                );
                text(launch.sourceId, "selectedOpportunity.launch.sourceId");
                const launched = reference(
                    launch.date,
                    "selectedOpportunity.launch.date",
                );
                const from = reference(
                    launch.rangeFrom,
                    "selectedOpportunity.launch.rangeFrom",
                );
                const until = reference(
                    launch.rangeUntil,
                    "selectedOpportunity.launch.rangeUntil",
                );
                if (
                    launched < start ||
                    launched > observed ||
                    from > launched ||
                    until < launched ||
                    (end !== null && end <= launched)
                )
                    fail("selectedOpportunity.launch boundaries");
            }
        }
    }
    return value as LabBundle;
}
