import assert from "node:assert/strict";
import test from "node:test";
import {
    datasetDetailHref,
    resolveDataset,
    safeDatasetBack,
    safeStudyBack,
    studyContext,
} from "./datasetJourney.ts";
import { studioRoute } from "../../app/routes.ts";
import type { Families } from "../shared-data/model.ts";

const data: Families = {
    families: [],
    catalogError: null,
    catalog: {
        version_id: "index-1",
        retired: [],
        entries: [
            {
                data_id: "events",
                version_id: "old",
                kind: "bundle",
                status: "ok",
            },
            {
                data_id: "events",
                version_id: "new",
                kind: "bundle",
                status: "ok",
            },
        ],
    },
};
test("direct dataset URLs round-trip the exact reference and study context", () => {
    const back = studyContext("#studies?q=volume&filter=report", "study-A");
    const href = datasetDetailHref("catalog:events:old", back);
    assert.equal(studioRoute(href).page, "dataset");
    const query = new URLSearchParams(href.split("?")[1]);
    assert.equal(query.get("ref"), "catalog:events:old");
    assert.equal(query.get("back"), back);
    assert.equal(safeDatasetBack(href), href);
    assert.equal(
        new URLSearchParams(back.split("?")[1]).get("study"),
        "study-A",
    );
});
test("return contexts cannot redirect outside the bounded local routes", () => {
    for (const bad of [
        "https://example.com",
        "//evil",
        "javascript:alert(1)",
        "#studies/evil",
        "#stock/foo",
    ])
        assert.equal(safeStudyBack(bad), "#studies");
    assert.equal(safeDatasetBack("#dataset/evil"), null);
    assert.equal(
        safeDatasetBack("#dataset?ref=events&back=https://evil"),
        datasetDetailHref("events"),
    );
    assert.equal(
        safeStudyBack("#studies?study=A&redirect=https://evil"),
        "#studies?study=A",
    );
});
test("frozen references never choose the newest version", () => {
    const match = resolveDataset(data, "catalog:events:old", null);
    assert.equal(match.kind, "catalog");
    if (match.kind === "catalog") assert.equal(match.entry.version_id, "old");
    assert.equal(
        resolveDataset(data, "catalog:events:gone", null).kind,
        "missing",
    );
    assert.equal(
        resolveDataset(data, "catalog:events:old", "new").kind,
        "ambiguous",
    );
    assert.equal(resolveDataset(data, "events", null).kind, "choose");
});
test("missing, unavailable and duplicate identities remain distinct", () => {
    assert.equal(resolveDataset(data, "absent", null).kind, "missing");
    assert.equal(
        resolveDataset(
            { ...data, catalog: null, catalogError: "busy" },
            "events",
            "old",
        ).kind,
        "unavailable",
    );
    const duplicate = {
        ...data,
        catalog: {
            ...data.catalog!,
            entries: [data.catalog!.entries[0], data.catalog!.entries[0]],
        },
    };
    assert.equal(resolveDataset(duplicate, "events", "old").kind, "ambiguous");
});
test("a family requires explicit generation selection and rejects expired generations", () => {
    const familyData: Families = {
        ...data,
        families: [
            {
                family: "adjusted-daily-v1",
                generation: "g2",
                asof: "",
                status_sha256: "",
                codes: 0,
                calendar: { first: "", last: "", sessions: 0 },
                definition: null,
                bases: null,
                technical: null,
            },
        ],
    };
    assert.equal(
        resolveDataset(familyData, "adjusted-daily-v1", null).kind,
        "choose",
    );
    assert.equal(
        resolveDataset(familyData, "adjusted-daily-v1", "g1").kind,
        "missing",
    );
    assert.equal(
        resolveDataset(familyData, "adjusted-daily-v1", "g2").kind,
        "family",
    );
});
