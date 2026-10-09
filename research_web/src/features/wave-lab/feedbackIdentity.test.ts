import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { test } from "node:test";
import {
    createFeedbackIdentity,
    readyFeedbackIdentity,
} from "./feedbackIdentity.ts";
import type { FeedbackIdentityState } from "./feedbackIdentity.ts";
import type { LabCase } from "./types.ts";

function fixture(): LabCase {
    return {
        id: "shared-detail-case",
        name: "Same named case",
        code: "1234",
        kind: "historical",
        category: "review",
        question: "Which part is a wave?",
        points: [
            { date: "2020-01-02", raw: 10, adjusted: 20, flags: [] },
            {
                date: "2020-01-03",
                raw: 11,
                adjusted: 22,
                flags: ["source-observation"],
            },
        ],
        source: {
            label: "Saved case",
            from: "2020-01-02",
            to: "2020-01-03",
            priceBasis: "adjusted-close",
            limitations: ["bounded case"],
        },
    };
}

test("map wave evidence separates feedback for different waves of the same case and normalizes property order", async () => {
    const sample = fixture();
    const standalone = await createFeedbackIdentity(sample, "rules.v1");
    sample.selectedOpportunity = {
        securityId: "TW:1234",
        waveId: "saved-wave",
        sourceId: "saved-method",
        start: "2020-01-02",
        peakDate: "2020-01-03",
        endConfirmedAt: null,
        observedThrough: "2020-01-03",
        scale: "large",
        leftCensored: false,
        rightCensored: true,
        launch: {
            date: "2020-01-03",
            rangeFrom: "2020-01-02",
            rangeUntil: "2020-01-03",
            sourceId: "launch-source",
        },
    };
    const key = await createFeedbackIdentity(sample, "rules.v1");
    assert.notEqual(key, standalone);
    const reordered = structuredClone(sample);
    reordered.selectedOpportunity = Object.fromEntries(
        Object.entries(sample.selectedOpportunity).reverse(),
    ) as LabCase["selectedOpportunity"];
    assert.equal(await createFeedbackIdentity(reordered, "rules.v1"), key);
    for (const change of [
        (value: NonNullable<LabCase["selectedOpportunity"]>) => {
            value.start = "2020-01-01";
        },
        (value: NonNullable<LabCase["selectedOpportunity"]>) => {
            value.waveId = "other-wave";
        },
        (value: NonNullable<LabCase["selectedOpportunity"]>) => {
            value.sourceId = "other-method";
        },
        (value: NonNullable<LabCase["selectedOpportunity"]>) => {
            value.launch!.rangeUntil = "2020-01-06";
        },
    ]) {
        const other = structuredClone(sample);
        change(other.selectedOpportunity!);
        assert.notEqual(await createFeedbackIdentity(other, "rules.v1"), key);
    }
});

test("content identity is stable for clones and property order, and uses actual SHA-256", async () => {
    const sample = fixture();
    const key = await createFeedbackIdentity(sample, "rules.v1");
    assert.equal(
        await createFeedbackIdentity(structuredClone(sample), "rules.v1"),
        key,
    );
    const reordered = {
        source: {
            limitations: [...sample.source.limitations],
            priceBasis: sample.source.priceBasis,
            to: sample.source.to,
            from: sample.source.from,
            label: sample.source.label,
        },
        points: sample.points.map((point) => ({
            flags: [...point.flags],
            adjusted: point.adjusted,
            raw: point.raw,
            date: point.date,
        })),
        question: sample.question,
        category: sample.category,
        kind: sample.kind,
        code: sample.code,
        name: sample.name,
        id: sample.id,
    };
    assert.equal(await createFeedbackIdentity(reordered, "rules.v1"), key);
    const canonical = JSON.stringify({
        schema: "wave-lab-feedback-content.v1",
        ruleVersion: "rules.v1",
        sample: {
            id: sample.id,
            name: sample.name,
            code: sample.code,
            kind: sample.kind,
            category: sample.category,
            question: sample.question,
            source: {
                label: sample.source.label,
                from: sample.source.from,
                to: sample.source.to,
                priceBasis: sample.source.priceBasis,
                hash: null,
                catalogHash: null,
                limitations: sample.source.limitations,
            },
            points: sample.points,
        },
    });
    assert.equal(
        key,
        `wave-lab-feedback-content.v1:sha256:${createHash("sha256").update(canonical).digest("hex")}`,
    );
});

test("same case id cannot reuse feedback across changed prices, dates, flags, provenance, basis or rules", async () => {
    const original = fixture();
    const originalKey = await createFeedbackIdentity(original, "rules.v1");
    const changes: ((sample: LabCase) => void)[] = [
        (sample) => {
            sample.points[0].raw = 10.01;
        },
        (sample) => {
            sample.points[0].adjusted = 20.01;
        },
        (sample) => {
            sample.points[1].adjusted = null;
        },
        (sample) => {
            sample.points[1].date = "2020-01-06";
        },
        (sample) => {
            sample.points[1].flags.push("additional-quality-flag");
        },
        (sample) => {
            sample.points.push({
                date: "2020-01-06",
                raw: 12,
                adjusted: 24,
                flags: [],
            });
        },
        (sample) => {
            sample.source.label = "Another source";
        },
        (sample) => {
            sample.source.from = "2020-01-01";
        },
        (sample) => {
            sample.source.to = "2020-01-06";
        },
        (sample) => {
            sample.source.priceBasis = "dividend-reinvestment-total-return";
        },
        (sample) => {
            sample.source.limitations.push("new limitation");
        },
        (sample) => {
            sample.source.hash = "declared-source-hash";
        },
        (sample) => {
            sample.source.catalogHash = "declared-catalog-hash";
        },
        (sample) => {
            sample.id = "another-case";
        },
        (sample) => {
            sample.name = "Other name";
        },
        (sample) => {
            sample.code = "5678";
        },
        (sample) => {
            sample.kind = "synthetic";
        },
        (sample) => {
            sample.category = "another category";
        },
        (sample) => {
            sample.question = "Another review question";
        },
    ];
    for (const change of changes) {
        const sample = structuredClone(original);
        change(sample);
        assert.notEqual(
            await createFeedbackIdentity(sample, "rules.v1"),
            originalKey,
        );
    }
    assert.notEqual(
        await createFeedbackIdentity(original, "rules.v2"),
        originalKey,
    );
    const sameDeclaredHash = fixture();
    sameDeclaredHash.source.hash = "same-external-hash";
    const changed = structuredClone(sameDeclaredHash);
    changed.points[1].adjusted = 220;
    assert.notEqual(
        await createFeedbackIdentity(sameDeclaredHash, "rules.v1"),
        await createFeedbackIdentity(changed, "rules.v1"),
    );
});

test("out-of-order async identities cannot expose another same-id case's feedback", async () => {
    const first = fixture();
    const next = structuredClone(first);
    next.points[0].adjusted = 200;
    const firstKey = await createFeedbackIdentity(first, "rules.v1");
    let state: FeedbackIdentityState | null = { sample: first, key: firstKey };
    assert.equal(readyFeedbackIdentity(state, next), null);
    const nextKey = await createFeedbackIdentity(next, "rules.v1");
    state = { sample: next, key: nextKey };
    assert.equal(readyFeedbackIdentity(state, next), nextKey);
    // Even a late completion from the first request cannot pass the current-case guard.
    state = { sample: first, key: firstKey };
    assert.equal(readyFeedbackIdentity(state, next), null);
    assert.equal(readyFeedbackIdentity(null, next), null);
});

test("failed SHA-256 and invalid prices reject without a weaker identity", async () => {
    const unavailable = {
        digest: async () => {
            throw new Error("SHA disabled");
        },
    } as Pick<SubtleCrypto, "digest">;
    await assert.rejects(
        createFeedbackIdentity(fixture(), "rules.v1", unavailable),
        /SHA disabled/,
    );
    const sample = fixture();
    sample.points[0].adjusted = NaN;
    await assert.rejects(
        createFeedbackIdentity(sample, "rules.v1"),
        /finite prices/,
    );
});
