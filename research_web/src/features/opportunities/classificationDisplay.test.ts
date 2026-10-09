import assert from "node:assert/strict";
import { test } from "node:test";
import type {
    IndustryMembership,
    OpportunityRow,
    SourceRef,
} from "../../domain/opportunities/types.ts";
import {
    classificationContext,
    classificationEvidence,
    classificationLabel,
    classificationSourceHref,
    classificationSourceLabel,
} from "./classificationDisplay.ts";

const SOURCES: SourceRef[] = [
    {
        id: "unrelated",
        label: "Unrelated source",
        url: "https://example.com/other",
    },
    { id: "official", label: "Official classification retrieval" },
    {
        id: "annual-report",
        label: "2020 annual report, PDF pages 12–14",
        url: "https://example.com/report.pdf#page=12",
        publishedAt: "2021-05-10",
    },
];
function row(
    basis: IndustryMembership["basis"],
): Pick<OpportunityRow, "security" | "industry"> {
    return {
        industry: {
            id: basis === "unknown" ? "unknown" : "business-group",
            label: "晶圓代工",
            from: "2020-01-01",
            untilExclusive: "2021-01-01",
            basis,
            sourceId: "annual-report",
        },
        security: {
            id: "TW:example",
            code: "example",
            name: "Example",
            market: "TW",
            currency: "TWD",
            industry: [],
            prices: [],
            classificationSnapshot: {
                label: "半導體業",
                observedAt: "2026-10-05T03:12:34.000Z",
                sourceId: "official",
            },
        },
    };
}

test("historical and document-period grouping evidence precede a separately preserved official snapshot", () => {
    for (const basis of ["historical", "document-period"] as const) {
        const input = row(basis);
        const before = structuredClone(input);
        const evidence = classificationEvidence(input, SOURCES);
        assert.equal(evidence.group?.id, "business-group");
        assert.equal(evidence.group?.basis, basis);
        assert.equal(
            classificationContext(input).length > 0,
            basis === "document-period",
        );
        assert.equal(evidence.group?.from, "2020-01-01");
        assert.equal(evidence.group?.through, "2020-12-31");
        assert.equal(evidence.group?.source, SOURCES[2]);
        assert.equal(evidence.group?.source?.publishedAt, "2021-05-10");
        assert.equal(evidence.snapshots.length, 1);
        assert.equal(evidence.snapshots[0].source, SOURCES[1]);
        assert.equal(evidence.snapshots[0].label, "半導體業");
        assert.equal(
            evidence.snapshots[0].observedAt,
            "2026-10-05T03:12:34.000Z",
        );
        assert.equal(classificationLabel(input), "晶圓代工");
        assert.deepEqual(
            classificationEvidence(input, [...SOURCES].reverse()),
            evidence,
        );
        assert.deepEqual(input, before);
    }
});

test("a snapshot supplies a display label without becoming historical grouping or an effective date", () => {
    const input = row("unknown");
    const before = structuredClone(input);
    const evidence = classificationEvidence(input, SOURCES);
    assert.equal(classificationLabel(input), "半導體業");
    assert.equal(evidence.group, null);
    assert.ok(classificationContext(input));
    assert.equal(input.industry.id, "unknown");
    assert.equal(evidence.snapshots[0].observedAt, "2026-10-05T03:12:34.000Z");
    assert.deepEqual(input, before);
    input.security.classificationSnapshot!.observedAt = null;
    assert.equal(
        classificationEvidence(input, SOURCES).snapshots[0].observedAt,
        null,
    );
});

test("legacy bundles without snapshot remain displayable and unbound sources do not borrow provenance", () => {
    const input = row("historical");
    delete input.security.classificationSnapshot;
    assert.equal(classificationLabel(input), "晶圓代工");
    assert.deepEqual(classificationEvidence(input, SOURCES).snapshots, []);
    input.industry.sourceId = "missing";
    const group = classificationEvidence(input, SOURCES).group;
    assert.equal(group?.sourceId, "missing");
    assert.equal(group?.source, null);
    input.industry.basis = "unknown";
    assert.equal(classificationLabel(input), "分類待補");
    assert.equal(classificationContext(input), "");
    assert.equal(classificationEvidence(input, SOURCES).group, null);
    input.industry.basis = "current-snapshot";
    assert.equal(classificationEvidence(input, SOURCES).group, null);
});

test("legacy snapshot memberships preserve every label and source without inferring retrieval dates or selecting a historical group", () => {
    const input = row("unknown");
    delete input.security.classificationSnapshot;
    input.security.industry = [
        {
            ...input.industry,
            id: "snapshot-a",
            label: "半導體業",
            basis: "current-snapshot",
            from: "2026-01-01",
            untilExclusive: null,
            sourceId: "official",
        },
        {
            ...input.industry,
            id: "snapshot-b",
            label: "電子工業",
            basis: "current-snapshot",
            from: "2022-01-01",
            untilExclusive: null,
            sourceId: "annual-report",
        },
        {
            ...input.industry,
            id: "unverified",
            label: "待核對",
            basis: "unknown",
        },
    ];
    const before = structuredClone(input);
    const evidence = classificationEvidence(input, SOURCES);
    assert.equal(classificationLabel(input), "半導體業、電子工業");
    assert.equal(evidence.group, null);
    assert.deepEqual(evidence.snapshots, [
        {
            label: "半導體業",
            observedAt: null,
            sourceId: "official",
            source: SOURCES[1],
        },
        {
            label: "電子工業",
            observedAt: null,
            sourceId: "annual-report",
            source: SOURCES[2],
        },
    ]);
    assert.deepEqual(input, before);
    input.security.industry.reverse();
    assert.deepEqual(
        classificationEvidence(input, SOURCES).snapshots,
        [...evidence.snapshots].reverse(),
    );
    input.security.industry = [input.security.industry[1]];
    const single = classificationEvidence(input, SOURCES);
    assert.equal(single.snapshots.length, 1);
    assert.equal(single.snapshots[0].observedAt, null);
    assert.equal(single.snapshots[0].source, SOURCES[2]);
    input.industry = row("historical").industry;
    assert.equal(classificationLabel(input), "晶圓代工");
    assert.equal(classificationEvidence(input, SOURCES).snapshots.length, 1);
});

test("the explicit classification snapshot takes precedence over legacy memberships without duplication", () => {
    const input = row("unknown");
    input.security.industry = [
        {
            ...input.industry,
            label: "半導體業",
            basis: "current-snapshot",
            sourceId: "official",
        },
        {
            ...input.industry,
            label: "舊版快照",
            basis: "current-snapshot",
            sourceId: "annual-report",
        },
    ];
    const evidence = classificationEvidence(input, SOURCES);
    assert.equal(evidence.snapshots.length, 1);
    assert.equal(evidence.snapshots[0].observedAt, "2026-10-05T03:12:34.000Z");
    assert.equal(evidence.snapshots[0].source, SOURCES[1]);
    assert.equal(classificationLabel(input), "半導體業");
    assert.equal(evidence.group, null);
});

test("half-open document coverage renders calendar-inclusive ends without local-time conversion", () => {
    const input = row("document-period");
    input.industry.untilExclusive = "2020-03-01";
    assert.equal(
        classificationEvidence(input, SOURCES).group?.through,
        "2020-02-29",
    );
    input.industry.untilExclusive = "2021-03-01";
    assert.equal(
        classificationEvidence(input, SOURCES).group?.through,
        "2021-02-28",
    );
    input.industry.untilExclusive = null;
    assert.equal(classificationEvidence(input, SOURCES).group?.through, null);
});

test("all reference layers retain labels, temporal scope and exact source bindings without selecting a main business", () => {
    const input = row("unknown");
    input.security.classificationReferences = [
        ...Array.from({ length: 48 }, (_, index) => ({
            id: `official-${index}`,
            label: `Official node ${index}`,
            layer: "official-value-chain" as const,
            temporalScope: "snapshot" as const,
            from: null,
            untilExclusive: null,
            sourceIds: ["official"],
        })),
        {
            id: "research",
            label: "Research grouping",
            layer: "research-group",
            temporalScope: "retrospective-period-summary",
            from: "2020-01-01",
            untilExclusive: "2021-01-01",
            sourceIds: ["annual-report"],
        },
        {
            id: "role-a",
            label: "Connected devices",
            layer: "business-role",
            temporalScope: "retrospective-event-context",
            from: "2020-01-01",
            untilExclusive: "2021-01-01",
            sourceIds: ["annual-report", "missing"],
        },
        {
            id: "role-b",
            label: "VR",
            layer: "business-role",
            temporalScope: "undated-reference",
            from: null,
            untilExclusive: null,
            sourceIds: [],
        },
        {
            id: "business-group",
            label: "Consumer business",
            layer: "business-group",
            temporalScope: "dated-profile-reference",
            from: "2021-05-10",
            untilExclusive: null,
            sourceIds: ["official"],
        },
        {
            id: "business-sector",
            label: "Electronics",
            layer: "business-sector",
            temporalScope: "undated-reference",
            from: null,
            untilExclusive: null,
            sourceIds: [],
        },
    ];
    const before = structuredClone(input);
    const evidence = classificationEvidence(input, SOURCES);
    assert.equal(evidence.group, null);
    assert.equal(evidence.references.length, 53);
    assert.deepEqual(
        evidence.references.map(({ id, label, layer, temporalScope }) => ({
            id,
            label,
            layer,
            temporalScope,
        })),
        input.security.classificationReferences.map(
            ({ id, label, layer, temporalScope }) => ({
                id,
                label,
                layer,
                temporalScope,
            }),
        ),
    );
    const research = evidence.references.find(
        (entry) => entry.id === "research",
    )!;
    assert.equal(research.through, "2020-12-31");
    assert.equal(research.sources[0].source, SOURCES[2]);
    const event = evidence.references.find((entry) => entry.id === "role-a")!;
    assert.equal(event.temporalScope, "retrospective-event-context");
    assert.equal(event.sources[1].source, null);
    const undated = evidence.references.find((entry) => entry.id === "role-b")!;
    assert.equal(undated.from, null);
    assert.equal(undated.through, null);
    assert.deepEqual(undated.sources, []);
    const profile = evidence.references.find(
        (entry) => entry.id === "business-group",
    )!;
    assert.equal(profile.from, "2021-05-10");
    assert.equal(profile.through, null);
    assert.equal(input.industry.id, "unknown");
    assert.deepEqual(input, before);
});

test("only absolute HTTP and HTTPS classification source URLs become clickable", () => {
    for (const url of [
        "https://example.com/report.pdf#page=12",
        "http://example.com/source",
    ]) {
        assert.equal(
            classificationSourceHref({ id: "source", label: "Source", url }),
            url,
        );
    }
    for (const url of [
        "javascript:alert(1)",
        "data:text/html,test",
        "file:///C:/local.pdf",
        "/relative",
        "not a URL",
        undefined,
    ]) {
        const source = { id: "source", label: "Source", url };
        const before = structuredClone(source);
        assert.equal(classificationSourceHref(source), null);
        assert.deepEqual(source, before);
    }
});

test("source display retains recorded document names and page references without pipeline identity or input mutation", () => {
    const source: SourceRef = {
        id: "classification:internal-claim-set:selection:TW:2609",
        label: "回溯文件期間 2021-01-01–2022-01-01；貨櫃航運／航運；陽明海運2021年度年報（110年度） | Physical PDF page 91 / printed page 85: 本公司現有船隊及經營業務; corroboration physical page 101 / printed page 95. | raw-file-bytes；claims 2609:shipping.container:2021-annual, 2609:shipping:2021-annual",
        url: "https://example.com/110Annual.pdf",
        path: "private/catalog/source.pdf",
        hash: "a".repeat(64),
    };
    const before = structuredClone(source);
    assert.equal(
        classificationSourceLabel(source),
        "陽明海運2021年度年報（110年度） · Physical PDF page 91 · printed page 85 · physical page 101 · printed page 95",
    );
    assert.equal(classificationSourceHref(source), source.url);
    assert.deepEqual(source, before);
});

test("source page display keeps recorded ranges and ignores extraction coordinates", () => {
    assert.equal(
        classificationSourceLabel({
            id: "source",
            label: "TWSE 臺灣證券交易所｜個股資訊 | PDF page 1 (zero-based page 0), lines 34-45; profile lists industry | canonical-retained-observation-json",
        }),
        "TWSE 臺灣證券交易所｜個股資訊 · PDF page 1",
    );
    assert.equal(
        classificationSourceLabel({
            id: "source",
            label:
                "2020 annual report, PDF pages 12–14 | 第 20～22 頁 | hash=" +
                "b".repeat(64),
        }),
        "2020 annual report · PDF pages 12–14 · 第 20～22 頁",
    );
});

test("technical-only sources use a neutral label without inventing a title or pages from hashes and paths", () => {
    const hash = "c".repeat(64);
    for (const label of [
        "preserved-catalog-chunk | rows[node_id=official:Q000:Q200] | raw-file-bytes",
        "raw-file-bytes; claims 1234:internal:observation",
        `Snapshot-only classification: sector-wave-catalog:sha256:${hash}`,
        "raw: official price_daily.parquet Close",
        "D:\\private\\classification\\catalog.json",
        "/private/classification/catalog.json",
        "classification:internal:source",
        hash,
    ]) {
        const source = {
            id: "classification:internal:source",
            label,
            url: "https://example.com/InventedAnnual2021.pdf#page=99",
            hash,
        };
        const before = structuredClone(source);
        assert.equal(classificationSourceLabel(source), "已保存的來源資料");
        assert.deepEqual(source, before);
    }
    assert.equal(classificationSourceLabel(null), "尚未提供可核對的來源");
    assert.equal(
        classificationSourceLabel({
            id: "source",
            label: "公司年報",
            url: "https://example.com/report.pdf#page=99",
        }),
        "公司年報",
    );
});
