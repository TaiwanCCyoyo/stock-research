import { createHash } from "node:crypto";
import { readFile, realpath, stat, writeFile } from "node:fs/promises";
import { isAbsolute, relative, resolve, sep, win32 } from "node:path";
import { fileURLToPath } from "node:url";
import { gunzipSync } from "node:zlib";
import { validateBundle } from "../src/domain/opportunities/model.ts";
import type {
    ClassificationReference,
    OpportunityBundle,
    SourceRef,
} from "../src/domain/opportunities/types.ts";

const VERSION = "classification-evidence-adapter.v2";
const LIMIT = 64 * 1024 * 1024;
const REPOSITORY_ROOT = fileURLToPath(new URL("../..", import.meta.url));
const REQUIRED_RECEIPT_CHECKS = [
    "exact-eight-identifiers-and-unique-source-identities",
    "known-broad-labels-retained-independent-of-fine-and-effective-date-gaps",
    "all-layer-source-bindings-and-null-unverified-effective-periods",
    "retained-source-raw-hashes-and-observation-digests-recomputed",
    "yangming-2021-role-and-explicit-sector-mappings-without-2022-extrapolation",
    "other-category-multiple-htc-roles-and-event-context-distinguished",
] as const;
type Row = Record<string, unknown>;
export interface FileIdentity {
    path: string;
    sha256: string;
}
export interface ClassificationIdentities {
    classification: FileIdentity;
    sources: FileIdentity;
    selections: FileIdentity;
    receipt: FileIdentity;
}
function fail(message: string): never {
    throw new Error(`Invalid classification evidence: ${message}`);
}
function row(value: unknown): Row {
    if (!value || typeof value !== "object" || Array.isArray(value))
        fail("expected object");
    return value as Row;
}
function array(value: unknown): unknown[] {
    if (!Array.isArray(value)) fail("expected array");
    return value;
}
function text(value: unknown): string {
    if (typeof value !== "string" || !value.trim())
        fail("expected nonempty string");
    return value;
}
function portableLocator(value: unknown): string {
    const locator = text(value);
    if (
        isAbsolute(locator) ||
        win32.isAbsolute(locator) ||
        /^[a-z]:/i.test(locator) ||
        locator.includes("\\") ||
        locator
            .split("/")
            .some((part) => !part || part === "." || part === "..")
    )
        fail(
            "identity path must be a repository-relative forward-slash locator; store required evidence as an explicit snapshot inside the repository",
        );
    return locator;
}
function digest(value: unknown): string {
    const result = text(value);
    if (!/^[a-f0-9]{64}$/.test(result)) fail("invalid sha256 digest");
    return result;
}
function date(value: unknown): string {
    const result = text(value);
    if (
        !/^\d{4}-\d{2}-\d{2}$/.test(result) ||
        new Date(result).toISOString().slice(0, 10) !== result
    )
        fail("invalid date");
    return result;
}
function timestamp(value: unknown): string | null {
    if (value === null) return null;
    const result = text(value);
    if (
        !/^\d{4}-\d{2}-\d{2}T.*(?:Z|[+-]\d{2}:\d{2})$/.test(result) ||
        !Number.isFinite(Date.parse(result))
    )
        fail("invalid timestamp");
    date(result.slice(0, 10));
    return result;
}
function period(
    value: unknown,
): { from: string; untilExclusive: string; precision: string } | null {
    if (value === null) return null;
    const item = row(value),
        from = date(item.from),
        untilExclusive = date(item.until_exclusive);
    if (from >= untilExclusive) fail("invalid document period");
    return { from, untilExclusive, precision: text(item.precision) };
}
function unique(values: string[], label: string): void {
    if (new Set(values).size !== values.length) fail(`duplicate ${label}`);
}
function schema(value: unknown, expected: string): Row {
    const result = row(value);
    if (result.schema_version !== expected) fail("unsupported schema");
    return result;
}

/** Add evidence only; document coverage never establishes exchange-effective or PIT membership. */
export function applyClassificationEvidence(
    input: OpportunityBundle,
    classificationValue: unknown,
    sourcesValue: unknown,
    selectionsValue: unknown,
    identities: ClassificationIdentities,
): OpportunityBundle {
    const bundle = structuredClone(validateBundle(input));
    const classification = schema(
        classificationValue,
        "opportunity-classification-evidence.v1",
    );
    const registry = schema(
        sourcesValue,
        "opportunity-classification-sources.v1",
    );
    const selections = row(selectionsValue);
    if (selections.schema !== "opportunity-classification-selections.v1")
        fail("unsupported selections schema");
    const catalogMatch = /^sector-wave-catalog:sha256:([a-f0-9]{64})$/.exec(
        text(classification.catalog_identity),
    );
    if (
        !catalogMatch ||
        !bundle.sources.some(
            (source) =>
                source.id === "producer:catalog_hash" &&
                source.hash === catalogMatch[1],
        )
    )
        fail("catalog identity mismatch");
    for (const identity of Object.values(identities)) {
        portableLocator(identity.path);
        digest(identity.sha256);
    }
    const namespace = `classification:${identities.classification.sha256}:${identities.sources.sha256}:`;
    const registryRows = array(registry.sources).map(row);
    unique(
        registryRows.map((source) => text(source.source_id)),
        "source",
    );
    const sourceMap = new Map(
        registryRows.map((source) => [text(source.source_id), source]),
    );
    const added = new Map<string, SourceRef>();
    const add = (source: SourceRef): string => {
        if (bundle.sources.some((existing) => existing.id === source.id))
            fail("existing evidence source collision");
        const previous = added.get(source.id);
        if (previous && JSON.stringify(previous) !== JSON.stringify(source))
            fail("conflicting source identity");
        added.set(source.id, source);
        return source.id;
    };
    // Validate the complete registry, including records not selected for map grouping.
    for (const source of registryRows) {
        if (source.url !== undefined) {
            let url: URL;
            try {
                url = new URL(text(source.url));
            } catch {
                fail("invalid source URL");
            }
            if (!["https:", "http:"].includes(url.protocol))
                fail("invalid source URL");
        }
        if (source.content_digest !== undefined) {
            const content = row(source.content_digest);
            if (
                content.algorithm !== "sha256" ||
                ![
                    "raw-file-bytes",
                    "canonical-retained-observation-json",
                ].includes(text(content.basis))
            )
                fail("unsupported digest basis");
            digest(content.value);
        } else if (!source.source_refs)
            fail("source has no digest or retained evidence link");
        for (const key of ["published_at", "first_available_at", "observed_at"])
            if (source[key] !== undefined) timestamp(source[key]);
        if (source.observed_on !== undefined) date(source.observed_on);
        if (source.document_covered_period !== undefined)
            period(source.document_covered_period);
    }
    const refs = (value: unknown, stack: string[] = []): string[] => {
        const items = array(value).map(row);
        if (!items.length) fail("empty source references");
        const ids = items.map((item) => {
            const sourceId = text(item.source_id),
                locator = text(item.locator),
                source = sourceMap.get(sourceId);
            if (!source) fail("unknown source reference");
            if (stack.includes(sourceId)) fail("cyclic source reference");
            const inherited = source.source_refs
                ? refs(source.source_refs, [...stack, sourceId])
                : [];
            const content =
                source.content_digest === undefined
                    ? null
                    : row(source.content_digest);
            const id = `${namespace}ref:${createHash("sha256").update(`${sourceId}\n${locator}`).digest("hex")}`;
            return add({
                id,
                label: `${source.title ?? source.source_type ?? sourceId} | ${locator} | ${content ? content.basis : `retained observation via ${inherited.map((id) => added.get(id)!.label).join("; ")}`}`,
                ...(source.url ? { url: text(source.url) } : {}),
                ...(source.repository_path
                    ? { path: text(source.repository_path) }
                    : {}),
                ...(content ? { hash: digest(content.value) } : {}),
            });
        });
        unique(ids, "source locator");
        return ids;
    };
    for (const source of registryRows)
        if (source.source_refs)
            refs(source.source_refs, [text(source.source_id)]);
    const packets = array(classification.securities).map(row);
    unique(
        packets.map((packet) => text(packet.security_id)),
        "security",
    );
    const declared = array(classification.security_ids).map(text);
    unique(declared, "declared security");
    if (
        JSON.stringify([...declared].sort()) !==
        JSON.stringify(packets.map((packet) => text(packet.security_id)).sort())
    )
        fail("security declarations mismatch");
    const claims = new Map<string, { securityId: string; value: Row }>();
    for (const packet of packets) {
        const securityId = text(packet.security_id),
            security = bundle.securities.find((item) => item.id === securityId);
        if (!security) fail("unknown security");
        const snapshot = row(packet.official_industry_snapshot);
        if (snapshot.effective_interval !== null)
            fail("unsupported snapshot effective interval");
        const snapshotRefs = refs(snapshot.source_refs);
        if (snapshot.status !== "known")
            fail("unsupported broad snapshot status");
        const snapshotSource =
            snapshotRefs.length === 1
                ? snapshotRefs[0]
                : add({
                      id: `${namespace}snapshot:${securityId}`,
                      label: `Official snapshot reference: ${snapshotRefs.map((id) => added.get(id)!.label).join("; ")}`,
                      path: `${identities.classification.path}#securities[security_id=${securityId}].official_industry_snapshot`,
                  });
        const snapshotLabel = text(snapshot.label),
            observedAt = timestamp(snapshot.metadata_fetched_at);
        if (security.classificationSnapshot) {
            if (
                security.classificationSnapshot.label !== snapshotLabel ||
                security.classificationSnapshot.observedAt !== observedAt
            )
                fail("existing snapshot conflict");
        } else
            security.classificationSnapshot = {
                label: snapshotLabel,
                observedAt,
                sourceId: snapshotSource,
            };
        const references: ClassificationReference[] = [];
        const append = (
            item: Row,
            idKey: string,
            layer: ClassificationReference["layer"],
            scope: ClassificationReference["temporalScope"],
            coverage: ReturnType<typeof period>,
        ) => {
            references.push({
                id: text(item[idKey]),
                label: text(item.label),
                layer,
                temporalScope: scope,
                from: coverage?.from ?? null,
                untilExclusive: coverage?.untilExclusive ?? null,
                sourceIds: refs(item.source_refs),
            });
        };
        const chain = row(packet.official_value_chain_snapshot),
            groups = row(packet.research_group_snapshot);
        if (
            chain.effective_interval !== null ||
            groups.effective_interval !== null
        )
            fail("unsupported reference effective interval");
        timestamp(chain.snapshot_recorded_at);
        for (const value of array(chain.memberships)) {
            const item = row(value);
            timestamp(item.source_fetched_at);
            append(item, "node_id", "official-value-chain", "snapshot", null);
        }
        for (const value of array(groups.groups))
            append(row(value), "group_id", "research-group", "snapshot", null);
        for (const value of array(packet.company_business_assertions)) {
            const claim = row(value),
                id = text(claim.assertion_id);
            if (claims.has(id)) fail("duplicate claim");
            claims.set(id, { securityId, value: claim });
            const layers = {
                business_role: "business-role",
                business_group: "business-group",
                business_sector: "business-sector",
            } as const;
            const layer = layers[text(claim.layer) as keyof typeof layers];
            if (!layer) fail("unsupported claim layer");
            const scope = text(
                claim.temporal_scope,
            ) as ClassificationReference["temporalScope"];
            if (
                ![
                    "retrospective-period-summary",
                    "retrospective-event-context",
                    "undated-reference",
                    "dated-profile-reference",
                ].includes(scope)
            )
                fail("unsupported temporal scope");
            if (claim.effective_interval !== null)
                fail("unsupported claim effective interval");
            timestamp(claim.published_at);
            timestamp(claim.first_available_at);
            const coverage = period(claim.document_covered_period);
            if ((scope === "undated-reference") !== (coverage === null))
                fail("temporal scope and coverage mismatch");
            append(claim, "assertion_id", layer, scope, coverage);
        }
        unique(
            references.map((item) => `${item.layer}:${item.id}`),
            "classification reference",
        );
        if (security.classificationReferences?.length)
            fail("existing references conflict");
        security.classificationReferences = references;
    }
    const selected = array(selections.selections).map(row);
    unique(
        selected.map((item) => text(item.securityId)),
        "selection security",
    );
    for (const selection of selected) {
        const securityId = text(selection.securityId),
            security = bundle.securities.find((item) => item.id === securityId);
        if (!security) fail("unknown selection security");
        const assertionIds = array(selection.assertionIds).map(text);
        if (!assertionIds.length) fail("empty selected claims");
        unique(assertionIds, "selected claim");
        let common: ReturnType<typeof period> = null;
        const evidence: string[] = [],
            claimLabels: string[] = [];
        for (const id of assertionIds) {
            const assertion = claims.get(id);
            if (!assertion || assertion.securityId !== securityId)
                fail("unknown or incompatible selected claim");
            const claim = assertion.value,
                coverage = period(claim.document_covered_period);
            if (
                claim.temporal_scope !== "retrospective-period-summary" ||
                ![
                    "primary-company-disclosure",
                    "company-document-period",
                ].includes(text(claim.basis)) ||
                claim.effective_interval !== null ||
                !coverage ||
                coverage.precision !== "fiscal-year"
            )
                fail("selected claim is not a fiscal-year period summary");
            if (common && JSON.stringify(common) !== JSON.stringify(coverage))
                fail("selected document periods differ");
            common = coverage;
            evidence.push(...refs(claim.source_refs));
            claimLabels.push(text(claim.label));
        }
        if (!common) fail("missing selected document period");
        if (
            security.industry.some(
                (item) =>
                    item.basis === "document-period" &&
                    item.from < common.untilExclusive &&
                    (item.untilExclusive === null ||
                        item.untilExclusive > common.from),
            )
        )
            fail("existing document-period conflict");
        const evidenceSources = [...new Set(evidence)].map((id) =>
            added.get(id)!,
        );
        const urls = [
            ...new Set(
                evidenceSources
                    .map((source) => source.url)
                    .filter((url): url is string => !!url),
            ),
        ];
        const sourceId = add({
            id: `${namespace}selection:${securityId}`,
            label: `回溯文件期間 ${common.from}–${common.untilExclusive}；${claimLabels.join("／")}；${evidenceSources.map((source) => source.label).join("; ")}；claims ${assertionIds.join(", ")}`,
            path: `${identities.classification.path}#securities[security_id=${securityId}].company_business_assertions`,
            ...(urls.length === 1 &&
            evidenceSources.every((source) => source.url === urls[0])
                ? { url: urls[0] }
                : {}),
        });
        security.industry.push({
            id: text(selection.groupId),
            label: text(selection.label),
            basis: "document-period",
            from: common.from,
            untilExclusive: common.untilExclusive,
            sourceId,
        });
    }
    for (const [kind, identity] of Object.entries(identities))
        add({
            id: `${namespace}file:${kind}`,
            label: `${kind} packet (raw-file-bytes SHA-256)`,
            path: identity.path,
            hash: identity.sha256,
        });
    bundle.sources.push(...added.values());
    const supplementIdentity = createHash("sha256")
        .update(JSON.stringify(identities))
        .digest("hex");
    bundle.classificationVersion += `+${VERSION}:${supplementIdentity}`;
    bundle.id += `+${VERSION}:${supplementIdentity}`;
    return validateBundle(bundle);
}

async function load(
    path: string,
    compressed = false,
): Promise<{ identity: FileIdentity; value: unknown }> {
    const absolute = resolve(path);
    portableLocator(relative(REPOSITORY_ROOT, absolute).split(sep).join("/"));
    const root = await realpath(REPOSITORY_ROOT);
    const actual = await realpath(absolute);
    const locator = portableLocator(
        relative(root, actual).split(sep).join("/"),
    );
    if ((await stat(actual)).size > LIMIT) fail("file exceeds 64MB");
    const raw = await readFile(actual);
    if (raw.length > LIMIT) fail("file exceeds 64MB");
    const decoded = compressed
        ? gunzipSync(raw, { maxOutputLength: LIMIT })
        : raw;
    return {
        identity: {
            path: locator,
            sha256: createHash("sha256").update(raw).digest("hex"),
        },
        value: JSON.parse(decoded.toString("utf8").replace(/^\uFEFF/, "")),
    };
}
export async function exportClassificationEvidence(
    options: Record<string, string>,
): Promise<OpportunityBundle> {
    for (const name of [
        "input",
        "classification",
        "sources",
        "receipt",
        "selections",
        "output",
    ])
        text(options[name]);
    const output = resolve(options.output);
    if (
        ["input", "classification", "sources", "receipt", "selections"].some(
            (name) => resolve(options[name]) === output,
        )
    )
        fail("output would overwrite source");
    const input = await load(
        options.input,
        options.input.toLowerCase().endsWith(".gz"),
    );
    const classification = await load(options.classification),
        sources = await load(options.sources);
    const receipt = await load(options.receipt),
        selections = await load(options.selections);
    const verified = schema(
            receipt.value,
            "opportunity-classification-verification.v1",
        ),
        files = row(verified.files);
    const checks = array(verified.checks).map(row);
    const checkNames = checks.map((check) => text(check.check));
    unique(checkNames, "receipt check");
    for (const required of REQUIRED_RECEIPT_CHECKS)
        if (!checkNames.includes(required))
            fail(`missing receipt check: ${required}`);
    for (const check of checks)
        if (check.status !== "passed")
            fail(`receipt check did not pass: ${text(check.check)}`);
    for (const [name, file] of [
        ["classification-v1.json", classification],
        ["sources-v1.json", sources],
    ] as const) {
        if (digest(row(files[name]).raw_sha256) !== file.identity.sha256)
            fail(`receipt hash mismatch: ${name}`);
    }
    const bundle = applyClassificationEvidence(
        validateBundle(input.value),
        classification.value,
        sources.value,
        selections.value,
        {
            classification: classification.identity,
            sources: sources.identity,
            receipt: receipt.identity,
            selections: selections.identity,
        },
    );
    await writeFile(output, `${JSON.stringify(bundle, null, 2)}\n`, {
        flag: "wx",
    });
    return bundle;
}
if (
    process.argv[1] &&
    resolve(process.argv[1]) === fileURLToPath(import.meta.url)
) {
    try {
        const options: Record<string, string> = {};
        for (let i = 2; i < process.argv.length; i += 2) {
            const name = process.argv[i].slice(2);
            if (
                !process.argv[i].startsWith("--") ||
                ![
                    "input",
                    "classification",
                    "sources",
                    "receipt",
                    "selections",
                    "output",
                ].includes(name) ||
                options[name] ||
                !process.argv[i + 1]
            )
                fail("invalid CLI arguments");
            options[name] = process.argv[i + 1];
        }
        const result = await exportClassificationEvidence(options);
        console.log(`Applied classification evidence: ${result.id}`);
    } catch (error) {
        console.error(error instanceof Error ? error.message : error);
        process.exitCode = 1;
    }
}
