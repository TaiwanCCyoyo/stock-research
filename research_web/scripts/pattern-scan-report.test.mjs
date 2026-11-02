import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import { gunzipSync } from "node:zlib";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createServer } from "vite";

const folder = fileURLToPath(
    new URL("../../tasks/20261013-pattern-scan/web-report/", import.meta.url),
);
const source = readFileSync(join(folder, "report.js"), "utf8");

test("the actual viewer permits result downloads while retaining other sandbox restrictions", async () => {
    const server = await createServer({
        logLevel: "silent",
        server: { middlewareMode: true, hmr: false },
    });
    try {
        const { ReportViewer } = await server.ssrLoadModule(
            "/src/features/report-library/ReportViewer.tsx",
        );
        const html = renderToStaticMarkup(
            createElement(ReportViewer, {
                reportId: "20261013-pattern-scan",
                palette: "forest",
                appearance: "dark",
            }),
        );
        const frame = html.match(/<iframe\b[^>]*>/)?.[0];
        assert.ok(frame, "the report must be rendered inside its viewer");
        const sandbox = frame.match(/\bsandbox="([^"]*)"/)?.[1].split(/\s+/);
        assert.deepEqual(
            new Set(sandbox),
            new Set(["allow-scripts", "allow-same-origin", "allow-downloads"]),
        );
        assert.match(
            frame,
            /src="\/reports\/20261013-pattern-scan\/index\.html#/,
        );
    } finally {
        await server.close();
    }
});
const pageIds = [
    "report-title",
    "study-meta",
    "completion-banner",
    "family-summary-horizon",
    "family-summary-scope",
    "family-summary-baseline",
    "family-summary-rows",
    "family-summary-status",
    "as-of",
    "overview-values",
    "question-progress",
    "questions",
    "audit-status",
    "audit-notes",
    "limitations",
    "provenance",
    "downloads",
];

// Only the DOM surface used by this classic script. Assigning HTML is forbidden.
class Element {
    constructor(tag) {
        this.tagName = tag.toUpperCase();
        this.children = [];
        this.attributes = new Map();
        this.listeners = new Map();
        this.className = "";
        this.value = "";
        this.text = "";
        this.classList = {
            add: (name) => {
                this.className = `${this.className} ${name}`.trim();
            },
        };
    }
    set innerHTML(_) {
        throw new Error("Report data must never be assigned as HTML");
    }
    set textContent(value) {
        this.text = String(value);
        this.children = [];
    }
    get textContent() {
        return (
            this.text + this.children.map((child) => child.textContent).join("")
        );
    }
    get childElementCount() {
        return this.children.filter((child) => !child.tagName.startsWith("#"))
            .length;
    }
    append(...children) {
        for (const child of children) {
            if (child.tagName === "#FRAGMENT") this.append(...child.children);
            else this.children.push(child);
        }
    }
    replaceChildren(...children) {
        this.text = "";
        this.children = [];
        this.append(...children);
    }
    setAttribute(name, value) {
        this.attributes.set(name, String(value));
    }
    addEventListener(type, callback) {
        const callbacks = this.listeners.get(type) || [];
        callbacks.push(callback);
        this.listeners.set(type, callbacks);
    }
    fire(type) {
        for (const callback of this.listeners.get(type) || []) callback();
    }
}

function render(payload) {
    const elements = new Map(
        pageIds.map((id) => {
            const element = new Element("div");
            element.id = id;
            return [id, element];
        }),
    );
    const document = {
        title: "",
        getElementById: (id) => elements.get(id),
        createElement: (tag) => new Element(tag),
        createTextNode: (text) => {
            const element = new Element("#text");
            element.textContent = text;
            return element;
        },
        createDocumentFragment: () => new Element("#fragment"),
    };
    const page = { document };
    page.window = page;
    if (payload !== undefined) page.REPORT_DATA = payload;
    runInNewContext(source, page, { timeout: 5000 });
    return { elements, document, page };
}

function descendants(root, predicate) {
    const found = [];
    for (const child of root.children) {
        if (predicate(child)) found.push(child);
        found.push(...descendants(child, predicate));
    }
    return found;
}

const byTag = (root, tag) =>
    descendants(root, (element) => element.tagName === tag.toUpperCase());
const questionById = (page, id) =>
    page.elements
        .get("questions")
        .children.find((element) => element.id === id);
const synthetic = () => ({
    schema: "pattern-scan-report.v1",
    title: "合成測試；不是研究結果",
    asOf: "2026-10-21",
    status: "partial",
    study: {
        period: ["2010-01-04", "2026-10-12"],
        stockN: 1942,
        horizons: [126, 252],
        generation: "synthetic-only",
        cutoff: "2026-10-12",
    },
    overview: [{ label: "已提供", value: 0, note: "零不是缺值" }],
    questions: [
        {
            id: "Q1",
            title: "合成表格",
            status: "complete",
            conclusion: "<img src=x onerror=alert(1)>",
            notes: ["<script>bad()</script>"],
            tables: [
                {
                    id: "synthetic",
                    title: "120 列合成資料",
                    columns: [
                        { key: "id", label: "列號", kind: "text" },
                        { key: "count", label: "計數", kind: "integer" },
                        { key: "missing", label: "缺值", kind: "number" },
                        { key: "fraction", label: "比例", kind: "percent" },
                        {
                            key: "delta",
                            label: "百分點",
                            kind: "percentage_points",
                        },
                        { key: "multiple", label: "倍數", kind: "multiple" },
                        { key: "label", label: "標籤", kind: "text" },
                    ],
                    rows: Array.from({ length: 120 }, (_, index) => ({
                        id: `row-${index}`,
                        count: index,
                        missing: null,
                        fraction: 0.125,
                        delta: 1.25,
                        multiple: 1.5,
                        label: "<img src=x onerror=alert(1)>",
                    })),
                    downloads: [
                        { label: "明細", href: "data/rows.csv", rows: 120 },
                    ],
                },
            ],
        },
    ],
    audit: { status: "pending", notes: ["整份稽核尚未完成"] },
    provenance: [{ label: "測試來源", value: "synthetic" }],
    limitations: ["不是研究結果"],
    downloads: [],
});

function familyComparison() {
    const targets = [
        "H1",
        "B1",
        "B2",
        "B3",
        "B4",
        "R1",
        "R2",
        "R3",
        "P1",
        "L1",
        "L2",
        "L3",
    ];
    return {
        scope: {
            question: "Q1",
            split: "all",
            era: "all",
            mkt: "all",
            cohort: "union",
        },
        baselines: [
            { horizon: 126, hit_rate: 0.4, known_n: 1000 },
            { horizon: 252, hit_rate: 0.5, known_n: 900 },
        ],
        rows: targets.flatMap((target, index) => [
            {
                target,
                horizon: 126,
                baseline_multiple: 1.25 + index / 100,
                delta_pp: 1.25,
                known_n: 100 + index,
                control_known_n: 200 + index,
                loss_rate: 0.2,
            },
            {
                target,
                horizon: 252,
                baseline_multiple: 0.75,
                delta_pp: -1.25,
                known_n: 80 + index,
                control_known_n: 180 + index,
                loss_rate: 0.25,
            },
        ]),
    };
}

test("the actual renderer preserves zero, null, fraction, pp and multiple units and literal markup", () => {
    const payload = synthetic();
    const original = JSON.stringify(payload);
    const page = render(payload);
    const q1 = questionById(page, "Q1");
    const first = byTag(q1, "tbody")[0].children[0].children;
    assert.deepEqual(
        first.map((cell) => cell.textContent),
        [
            "row-0",
            "0",
            "—",
            "12.5%",
            "+1.25 百分點",
            "1.5×",
            "<img src=x onerror=alert(1)>",
        ],
    );
    assert.match(first[2].title, /不代表零/);
    assert.match(first[3].title, /原始比例：0\.125/);
    assert.equal(
        page.elements.get("overview-values").children[0].children[1]
            .textContent,
        "0",
    );
    assert.match(q1.textContent, /<script>bad\(\)<\/script>/);
    assert.equal(byTag(q1, "img").length + byTag(q1, "script").length, 0);
    assert.equal(
        JSON.stringify(payload),
        original,
        "rendering must not mutate its payload",
    );
});

test("all 120 supplied rows remain reachable through the real pagination controls", () => {
    const page = render(synthetic());
    const q1 = questionById(page, "Q1");
    const tbody = byTag(q1, "tbody")[0];
    const [previous, next] = byTag(q1, "button");
    const input = byTag(q1, "input")[0];
    const size = byTag(q1, "select")[0];
    const visibleIds = () =>
        tbody.children.map((row) => row.children[0].textContent);
    assert.equal(previous.disabled, true);
    assert.deepEqual(
        visibleIds(),
        Array.from({ length: 50 }, (_, i) => `row-${i}`),
    );
    const seen = new Set(visibleIds());
    next.fire("click");
    assert.equal(visibleIds()[0], "row-50");
    visibleIds().forEach((id) => seen.add(id));
    next.fire("click");
    assert.equal(visibleIds()[0], "row-100");
    assert.equal(tbody.children.length, 20);
    assert.equal(next.disabled, true);
    visibleIds().forEach((id) => seen.add(id));
    assert.equal(seen.size, 120);
    assert.deepEqual(
        [...seen],
        Array.from({ length: 120 }, (_, i) => `row-${i}`),
    );
    previous.fire("click");
    assert.equal(visibleIds()[0], "row-50");
    size.value = "25";
    size.fire("change");
    assert.equal(
        visibleIds()[0],
        "row-50",
        "changing size retains the first visible row",
    );
    assert.equal(input.value, "3");
    input.value = "5";
    input.fire("change");
    assert.deepEqual(
        visibleIds(),
        Array.from({ length: 20 }, (_, i) => `row-${100 + i}`),
    );
    input.value = "1";
    input.fire("change");
    assert.equal(visibleIds()[0], "row-0");
    assert.equal(tbody.children.length, 25);
    size.value = "100";
    size.fire("change");
    assert.equal(tbody.children.length, 100);
    input.value = "999";
    input.fire("change");
    assert.equal(input.value, "2");
    assert.equal(visibleIds()[0], "row-100");
});

test("the first-screen comparison keeps twelve Q1 families on one scope and switches horizons", () => {
    const payload = synthetic();
    payload.comparisonSummary = familyComparison();
    const page = render(payload);
    const rows = page.elements.get("family-summary-rows");
    const selector = page.elements.get("family-summary-horizon");
    const rowCells = (row) => row.children.map((cell) => cell.textContent);

    assert.equal(selector.value, "126");
    assert.equal(rows.children.length, 12);
    assert.deepEqual(rowCells(rows.children[0]), [
        "HHHL v4 突破型態（H1）",
        "1.25×",
        "+1.25 百分點",
        "100",
        "200",
        "20%",
    ]);
    assert.match(
        page.elements.get("family-summary-baseline").textContent,
        /所有合格日的翻倍比例 40%（樣本 1,000）/,
    );
    assert.match(
        page.elements.get("family-summary-scope").textContent,
        /不加額外條件.*全部股票.*全部年份.*全部市場/,
    );
    assert.match(
        readFileSync(join(folder, "index.html"), "utf8"),
        /加上篩選條件的結果在問題\s+2、3/,
    );
    assert.match(
        page.elements.get("family-summary-status").textContent,
        /十二種型態/,
    );

    selector.value = "252";
    selector.fire("change");

    assert.equal(rows.children.length, 12);
    assert.deepEqual(rowCells(rows.children[0]), [
        "HHHL v4 突破型態（H1）",
        "0.75×",
        "−1.25 百分點",
        "80",
        "180",
        "25%",
    ]);
    assert.match(
        page.elements.get("family-summary-baseline").textContent,
        /所有合格日的翻倍比例 50%（樣本 900）/,
    );
});

test("summary denominators show N/A while real zero counts and rates remain zero", () => {
    const payload = synthetic();
    payload.comparisonSummary = {
        scope: "synthetic-only",
        baselines: [{ horizon: 126, hit_rate: 0, known_n: 0 }],
        rows: [
            {
                target: "H1",
                horizon: 126,
                baseline_multiple: 0,
                delta_pp: 0,
                known_n: 0,
                control_known_n: 0,
                loss_rate: 0,
            },
            {
                target: "B1",
                horizon: 126,
                baseline_multiple: null,
                delta_pp: null,
                known_n: 9,
                control_known_n: 0,
                loss_rate: null,
            },
            {
                target: "B2",
                horizon: 126,
                baseline_multiple: 0,
                delta_pp: 0,
                known_n: 10,
                control_known_n: 12,
                loss_rate: 0,
            },
        ],
    };
    const page = render(payload);
    const rows = page.elements.get("family-summary-rows").children;
    const rowCells = (row) => row.children.map((cell) => cell.textContent);

    assert.deepEqual(rowCells(rows[0]), [
        "HHHL v4 突破型態（H1）",
        "N/A",
        "N/A",
        "0",
        "0",
        "N/A",
    ]);
    assert.deepEqual(rowCells(rows[1]), [
        "杯形突破（B1）",
        "N/A",
        "N/A",
        "9",
        "0",
        "N/A",
    ]);
    assert.deepEqual(rowCells(rows[2]), [
        "布林通道收縮後突破（B2）",
        "N/A",
        "0 百分點",
        "10",
        "12",
        "0%",
    ]);
    assert.match(
        page.elements.get("family-summary-baseline").textContent,
        /N\/A（樣本 0）/,
    );
});

test("older payloads without a comparison summary remain readable without invented values", () => {
    const page = render(synthetic());

    assert.equal(page.elements.get("family-summary-horizon").value, "126");
    assert.equal(page.elements.get("family-summary-rows").children.length, 0);
    assert.match(
        page.elements.get("family-summary-status").textContent,
        /尚未提供/,
    );
    assert.equal(byTag(questionById(page, "Q1"), "table").length, 1);
});

test("collapsible table definitions use native details without dropping paginated rows", () => {
    const payload = synthetic();
    payload.questions[0].tables[0].collapsible = true;
    const page = render(payload);
    const q1 = questionById(page, "Q1");
    const details = byTag(q1, "details").find((item) =>
        item.className.includes("question-table"),
    );
    const tbody = byTag(details, "tbody")[0];

    assert.ok(details);
    assert.equal(byTag(details, "summary")[0].textContent, "120 列合成資料");
    assert.equal(tbody.children.length, 50);
    byTag(details, "button")[1].fire("click");
    assert.equal(tbody.children[0].children[0].textContent, "row-50");
    assert.match(
        byTag(details, "table")[0].children[0].textContent,
        /共 120 列/,
    );
});

test("the overview and evidence disclosure preserve the current completion boundaries", () => {
    const html = readFileSync(join(folder, "index.html"), "utf8");

    assert.match(html, /看見型態之後，股票更容易翻倍嗎/);
    assert.match(html, /另外兩個發現/);
    assert.ok(
        html.indexOf("另外兩個發現") < html.indexOf('id="family-summary"'),
    );
    assert.match(html, /完整成果與資料取得/);
    // Answer first: the page opens with the question's answer and its denominator.
    // The per-pattern answer leads; the 432/525 direction count is a later supplement.
    const answer = html.indexOf('id="main-answer"');
    const supplement = html.indexOf("432", answer);
    assert.ok(html.indexOf('id="headline-table"') < supplement);
    assert.ok(supplement < html.indexOf("另外兩個發現"));
    assert.doesNotMatch(html, /先在一半股票上挑出表現最好的幾個再組合/);
    assert.match(html, /這份研究想找出：哪些型態與一年內翻倍有關/);
    assert.match(html, /不是 1,104\s*次獨立檢定/);
    assert.ok(
        html.indexOf('id="main-answer"') <
            html.indexOf('id="research-lineage"'),
    );
    // Lineage: every other station is a clickable related-report link plus JSON-LD.
    for (const id of [
        "20261021-momentum-only-doubling",
        "20261024-strength-weakening-flags",
    ])
        assert.match(html, new RegExp(`data-related-report="${id}"`));
    const ld = JSON.parse(
        html.match(
            /<script type="application\/ld\+json">([\s\S]*?)<\/script>/,
        )[1],
    );
    assert.equal(ld["@type"], "Report");
    assert.equal(ld.identifier, "20261013-pattern-scan");
    assert.equal(ld.citation, "../research-lineage.md");
    // Reader tone: no warning slogans or disclaimers.
    assert.doesNotMatch(html, /僅供參考|不要照做|不可外推|不構成策略通過/);
    assert.doesNotMatch(html, /獨立重建稽核尚未完成/);
    assert.match(html, /<details class="evidence-details">/);
    // Pattern guide: names plus codes, defined before the first question, no bare code legend.
    assert.ok(
        html.indexOf('id="pattern-guide"') < html.indexOf('id="questions"'),
    );
    assert.doesNotMatch(html, /代號對照/);
    const guide = html.slice(
        html.indexOf('id="pattern-guide"'),
        html.indexOf('id="questions"'),
    );
    for (const code of [
        "H1",
        "B1",
        "B2",
        "B3",
        "B4",
        "R1",
        "R2",
        "R3",
        "P1",
        "L1",
        "L2",
        "L3",
    ])
        assert.match(guide, new RegExp(`pattern-code">${code}<`));
    const svgs = guide.match(/<svg[^>]*>/g) ?? [];
    assert.equal(svgs.length, 3);
    assert.ok(svgs.every((tag) => /aria-hidden="true"/.test(tag)));
    for (const id of [
        "audit-status",
        "audit-notes",
        "limitations",
        "provenance",
        "downloads",
    ])
        assert.match(html, new RegExp(`id="${id}"`));
});

test("the headline summary matches the saved per-pattern numbers", () => {
    const html = readFileSync(join(folder, "index.html"), "utf8");
    const context = {};
    context.window = context;
    runInNewContext(
        readFileSync(join(folder, "data/final-v1/summary.js"), "utf8"),
        context,
        { timeout: 5000 },
    );
    const rows = context.REPORT_DATA.comparisonSummary.rows.filter(
        (row) => row.horizon === 252,
    );
    assert.equal(rows.length, 12);
    const evidence = JSON.parse(
        readFileSync(
            join(folder, "data/final-v1/interpretation-evidence.json"),
            "utf8",
        ),
    );
    const counts = Object.fromEntries(
        evidence.candidate_by_family
            .filter((row) => row.horizon === 252)
            .map((row) => [
                row.family,
                [row.higher_n, row.lower_n, row.incomparable_n],
            ]),
    );
    const reader = readFileSync(join(folder, "reader.js"), "utf8");
    for (const [family, values] of Object.entries(counts))
        assert.ok(
            reader.includes(`${family}: [${values.join(", ")}]`),
            `reader.js condition counts for ${family}`,
        );
    // Left column: unconditional differences only, signs as saved (no mixed rule).
    const positive = rows.filter((row) => row.delta_pp > 0).length;
    const negative = rows.filter((row) => row.delta_pp < 0).length;
    const top = Math.max(...rows.map((row) => row.delta_pp));
    assert.deepEqual([positive, negative], [7, 5]);
    assert.equal(Math.round(top), 5);
    assert.match(
        html,
        /七種的翻倍比例比一般合格日高（最多高約\s*5 個百分點），五種較低/,
    );
    assert.doesNotMatch(html, /兩種看不出差別|同一天也符合/);
    // Right column: a separate comparison; per-pattern group counts as saved.
    assert.match(html, /加上篩選條件後（另一個比較）/);
    assert.match(html, /不是顯著性檢定/);
    assert.ok(
        reader.includes("size < 0.05"),
        "near-zero differences must not print as a signed 0.0",
    );
    const evidenceTotal = evidence.candidate_totals.find(
        (row) => row.horizon === 252,
    );
    assert.match(html, new RegExp(`${evidenceTotal.higher_n}\\s*組較高`));
    assert.match(html, new RegExp(`${evidenceTotal.lower_n}\\s*組較低`));
    // Reader tone and no mixed-up comparison wording in the headline block.
    const block = html.slice(
        html.indexOf('id="main-answer"'),
        html.indexOf('class="reader-explorer"'),
    );
    assert.doesNotMatch(block, /先在一半股票|不要照做|僅供參考/);
});

test("the ranking view shows 12 rows, 7 high and 5 low, and every detail link has a target", () => {
    const html = readFileSync(join(folder, "index.html"), "utf8");
    const context = {};
    context.window = context;
    for (const name of [
        "data/final-v1/summary.js",
        ...Array.from(
            { length: 12 },
            (_, i) => `data/final-v1/rows-${String(i + 1).padStart(3, "0")}.js`,
        ),
    ])
        runInNewContext(readFileSync(join(folder, name), "utf8"), context, {
            timeout: 5000,
        });
    // reader.js only needs a DOM-less surface to publish its pure model.
    context.location = { protocol: "file:" };
    context.parent = context;
    context.document = {
        querySelectorAll: () => [],
        getElementById: () => null,
    };
    runInNewContext(readFileSync(join(folder, "reader.js"), "utf8"), context, {
        timeout: 5000,
    });
    const model = context.patternRank.patternModel();
    assert.equal(model.length, 12);
    assert.equal(model.filter((row) => row.delta > 0).length, 7);
    assert.equal(model.filter((row) => row.delta < 0).length, 5);
    assert.deepEqual(
        Array.from(model, (row) => row.delta),
        [...model.map((row) => row.delta)].sort((a, b) => b - a),
    );
    // One shared baseline (9.9%) and the same numbers as the saved summary.
    const baseline = context.REPORT_DATA.comparisonSummary.baselines.find(
        (row) => row.horizon === 252,
    );
    const saved = Object.fromEntries(
        context.REPORT_DATA.comparisonSummary.rows
            .filter((row) => row.horizon === 252)
            .map((row) => [row.target, row]),
    );
    for (const row of model) {
        assert.equal((row.control * 100).toFixed(1), "9.9", row.code);
        assert.equal(row.delta, saved[row.code].delta_pp);
        assert.equal(
            row.rate,
            saved[row.code].baseline_multiple * baseline.hit_rate,
        );
        assert.equal(row.higher + row.lower + row.incomparable + row.same, 92);
        assert.ok(row.same >= 0);
    }
    assert.equal(
        model.reduce((total, row) => total + row.same, 0),
        16,
        "the 16 equal groups of the 252-day total",
    );
    // Detail links: static anchors exist, and every question table has rows.
    for (const row of model) {
        assert.match(html, new RegExp(`id="pg-${row.code}"`));
        assert.match(html, new RegExp(`data-pattern="${row.code}"`));
        assert.deepEqual(Array.from(row.links), ["Q2", "Q3", "Q4", "Q5", "Q6"]);
    }
    for (const id of [
        "rank-view",
        "rank-layout",
        "rank-ladder",
        "rank-pane",
        "rank-switch",
        "rank-axis",
        "headline-table",
        "headline-table-wrap",
        "family-details",
    ])
        assert.match(html, new RegExp(`id="${id}"`), id);
    // Runtime anchors are created by report.js: family rows and table jumps.
    const family = render(context.REPORT_DATA).elements.get(
        "family-summary-rows",
    );
    const familyIds = family.children.map((row) => row.id).sort();
    assert.deepEqual(
        familyIds,
        Array.from(model, (row) => `fs-row-${row.code}`).sort(),
    );
    const rendered = render(context.REPORT_DATA);
    for (const question of ["Q2", "Q3", "Q4", "Q5", "Q6"]) {
        const jump = rendered.page.reportTableJump[`${question}-table-1`];
        assert.equal(typeof jump, "function", question);
        for (const row of model)
            assert.ok(
                jump((r) => context.patternRank.rowCode(r) === row.code),
                `${question} ${row.code}`,
            );
    }
    const reader = readFileSync(join(folder, "reader.js"), "utf8");
    // The hash keeps the kit's palette/appearance parameters next to pattern=.
    assert.match(reader, /new URLSearchParams\(raw\.includes\("="\)/);
    assert.match(reader, /params\.set\("pattern", code\)/);
    assert.match(reader, /params\.delete\("pattern"\)/);
});

test("downloads accept report-local data files and refuse traversal or URLs", () => {
    const payload = synthetic();
    payload.downloads = [
        {
            label: "合法",
            href: "data/final/results.csv",
            rows: 120,
            bytes: 1234,
        },
        { label: "穿越", href: "data/../outside.csv" },
        { label: "編碼穿越", href: "data/%2e%2e/outside.csv" },
        { label: "反斜線", href: "data/..\\outside.csv" },
        { label: "外部", href: "https://example.invalid/result.csv" },
        { label: "絕對", href: "/data/result.csv" },
        { label: "程式", href: "javascript:alert(1)" },
    ];
    const page = render(payload);
    const links = byTag(page.elements.get("downloads"), "a");
    assert.deepEqual(
        links.map((link) => link.href),
        ["data/final/results.csv"],
    );
    assert.match(page.elements.get("downloads").textContent, /1,234 bytes/);
    assert.equal(byTag(questionById(page, "Q1"), "a")[0].href, "data/rows.csv");
});

test("missing Q2–Q6 and missing payload stay explicitly pending", () => {
    const page = render(synthetic());
    for (let number = 2; number <= 6; number += 1) {
        const question = questionById(page, `Q${number}`);
        assert.match(question.textContent, /尚未完成/);
        assert.match(question.textContent, /尚未提供成果表/);
        assert.equal(byTag(question, "table").length, 0);
    }
    assert.match(page.elements.get("audit-status").textContent, /狀態尚未提供/);
    const missing = render();
    assert.match(
        missing.elements.get("completion-banner").textContent,
        /尚未載入研究資料/,
    );
    assert.match(
        missing.elements.get("completion-banner").textContent,
        /不代表零/,
    );
    for (let number = 1; number <= 6; number += 1)
        assert.match(
            questionById(missing, `Q${number}`).textContent,
            /尚未完成/,
        );
});

function readCsv(file) {
    const bytes = readFileSync(file);
    return (file.endsWith(".gz") ? gunzipSync(bytes) : bytes)
        .toString("utf8")
        .replace(/^\uFEFF/, "");
}

function csvRecords(text) {
    const records = [];
    let row = [];
    let field = "";
    let quoted = false;
    const finishRow = () => {
        row.push(field);
        records.push(row);
        row = [];
        field = "";
    };
    for (let index = 0; index < text.length; index += 1) {
        const character = text[index];
        if (character === '"') {
            if (quoted && text[index + 1] === '"') {
                field += '"';
                index += 1;
            } else quoted = !quoted;
        } else if (!quoted && character === ",") {
            row.push(field);
            field = "";
        } else if (!quoted && character === "\n") finishRow();
        else if (!quoted && character === "\r") {
            finishRow();
            if (text[index + 1] === "\n") index += 1;
        } else field += character;
    }
    assert.equal(quoted, false, "CSV must not end inside a quoted field");
    if (field || row.length) finishRow();
    return records;
}

test("the actual page loads every final chunk in order and matches all displayed rows and downloads", () => {
    // Required, not a conditional skip: a registered report must ship its data.
    const html = readFileSync(join(folder, "index.html"), "utf8");
    const tags = [...html.matchAll(/<script\b([^>]*)><\/script>/g)];
    const scripts = tags.map((tag) => tag[1].match(/\bsrc="([^"]+)"/)?.[1]);
    const manifest = JSON.parse(
        readFileSync(
            join(folder, "data/final-v1/scripts-manifest.json"),
            "utf8",
        ),
    );
    assert.equal(manifest.max_bytes_exclusive, 500 * 1024);
    assert.deepEqual(scripts, [
        "kit/report-kit.js",
        ...manifest.scripts.map((name) => `data/final-v1/${name}`),
        "conclusions.js",
        "report.js",
        "reader.js",
    ]);
    for (const [index, tag] of tags.entries()) {
        assert.match(tag[1], /\bdefer\b/);
        assert.doesNotMatch(tag[1], /\basync\b|\btype=/);
        const stats = statSync(join(folder, scripts[index]));
        assert.ok(stats.isFile());
        assert.ok(stats.size < 500 * 1024, `${scripts[index]}: script budget`);
    }
    const context = {};
    context.window = context;
    for (const script of scripts.slice(1, -2)) {
        runInNewContext(readFileSync(join(folder, script), "utf8"), context, {
            timeout: 5000,
            filename: script,
        });
    }
    assert.deepEqual(
        Array.from(context.REPORT_DATA.dataScripts),
        manifest.scripts,
    );
    assert.equal(
        context.REPORT_DATA.questions
            .flatMap((question) => question.tables)
            .reduce((total, table) => total + table.rows.length, 0),
        8268,
    );
    const data = context.REPORT_DATA;
    assert.ok(data && typeof data === "object");
    assert.equal(typeof data.schema, "string");
    assert.ok(data.schema.length > 0);
    assert.ok(["partial", "complete"].includes(data.status));
    assert.ok(Array.isArray(data.provenance) && data.provenance.length > 0);
    assert.deepEqual(Array.from(data.study.period), [
        "2010-01-04",
        "2026-10-12",
    ]);
    assert.deepEqual(Array.from(data.study.horizons), [126, 252]);
    assert.ok(Number.isInteger(data.study.stockN) && data.study.stockN > 0);
    assert.equal(data.questions.length, 6);
    assert.deepEqual(
        Array.from(data.questions, (question) => question.id).sort(),
        ["Q1", "Q2", "Q3", "Q4", "Q5", "Q6"],
    );
    const page = render(data);
    const downloads = [...(data.downloads || [])];
    for (const question of data.questions) {
        assert.equal(question.status, "complete");
        const questionElement = questionById(page, question.id);
        assert.ok(questionElement.textContent.includes(question.title));
        assert.ok(questionElement.textContent.includes(question.conclusion));
        assert.equal(
            byTag(questionElement, "table").length,
            question.tables.filter(
                (table) => table.columns.length && table.rows.length,
            ).length,
        );
        for (const table of question.tables) {
            const keys = table.columns.map((column) => column.key);
            assert.equal(
                new Set(keys).size,
                keys.length,
                "table keys must be unique",
            );
            for (const row of table.rows) {
                for (const column of table.columns) {
                    assert.ok(
                        Object.hasOwn(row, column.key),
                        `${table.id}: missing ${column.key}`,
                    );
                    const value = row[column.key];
                    if (column.kind !== "text" && value !== null) {
                        assert.equal(
                            typeof value,
                            "number",
                            `${table.id}/${column.key}: numeric value`,
                        );
                        assert.ok(Number.isFinite(value));
                        if (column.kind === "integer")
                            assert.ok(Number.isInteger(value));
                    }
                }
            }
            downloads.push(...(table.downloads || []));
            const csv = table.downloads.find((item) =>
                /\.csv(?:\.gz)?$/.test(item.href),
            );
            assert.ok(
                csv,
                `${question.id}/${table.id}: complete displayed CSV`,
            );
            const records = csvRecords(readCsv(join(folder, csv.href)));
            assert.deepEqual(records[0], Array.from(keys));
            assert.equal(records.length - 1, table.rows.length);
            for (const [index, row] of table.rows.entries()) {
                for (const [columnIndex, column] of table.columns.entries()) {
                    const value = row[column.key];
                    const cell = records[index + 1][columnIndex];
                    assert.equal(
                        value === null || column.kind === "text"
                            ? cell
                            : Number(cell),
                        value === null ? "" : value,
                        `${csv.href}: row ${index}, ${column.key}`,
                    );
                }
            }
        }
    }
    assert.ok(
        downloads.length > 0,
        "the stored report must link its actual result exports",
    );
    for (const item of downloads) {
        assert.match(item.href, /^data\/[A-Za-z0-9_./-]+$/);
        assert.ok(
            !item.href
                .split("/")
                .some((part) => !part || part === "." || part === ".."),
        );
        const file = join(folder, item.href);
        const stats = statSync(file);
        assert.ok(stats.isFile());
        assert.equal(stats.size, item.bytes, `${item.href}: advertised bytes`);
        if (item.rows !== undefined)
            assert.ok(Number.isInteger(item.rows) && item.rows >= 0);
        if (/\.csv(?:\.gz)?$/.test(item.href)) {
            assert.ok(stats.size < 500 * 1024, `${item.href}: download budget`);
            const records = csvRecords(readCsv(file));
            assert.ok(records.length > 0, "CSV needs a header");
            if (item.rows !== undefined)
                assert.equal(
                    records.length - 1,
                    item.rows,
                    `${item.href}: advertised row count`,
                );
            assert.ok(
                records
                    .slice(1)
                    .every((row) => row.length === records[0].length),
                `${item.href}: consistent CSV field counts`,
            );
        }
    }
});

test("path categories are described by the implemented rule", () => {
    const names = source.slice(source.indexOf("const pathNames"));
    assert.match(
        names,
        /direct_failure: "先跌 10% 才漲 10%（或一直沒漲 10%）"/,
    );
    assert.doesNotMatch(names, /就沒再漲|後回落|緩慢下跌|大致盤整/);
    assert.match(names, /rise_then_fall: "沒有先跌 10%，且曾漲 20% 以上"/);
});
