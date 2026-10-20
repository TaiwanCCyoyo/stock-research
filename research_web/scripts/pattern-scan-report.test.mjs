import assert from "node:assert/strict";
import { readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const folder = fileURLToPath(
    new URL("../../tasks/20261013-pattern-scan/web-report/", import.meta.url),
);
const source = readFileSync(join(folder, "report.js"), "utf8");
const pageIds = [
    "report-title",
    "study-meta",
    "completion-banner",
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
    return { elements, document };
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
                        { key: "label", label: "標籤", kind: "text" },
                    ],
                    rows: Array.from({ length: 120 }, (_, index) => ({
                        id: `row-${index}`,
                        count: index,
                        missing: null,
                        fraction: 0.125,
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

test("the actual renderer preserves zero, null, fraction units and literal markup", () => {
    const payload = synthetic();
    const original = JSON.stringify(payload);
    const page = render(payload);
    const q1 = questionById(page, "Q1");
    const first = byTag(q1, "tbody")[0].children[0].children;
    assert.deepEqual(
        first.map((cell) => cell.textContent),
        ["row-0", "0", "—", "12.5%", "<img src=x onerror=alert(1)>"],
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
    assert.match(page.elements.get("audit-status").textContent, /尚未完成/);
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

test("the committed summary exists and matches its displayed rows and actual downloads", () => {
    // Required, not a conditional skip: a registered report must ship its data.
    const context = {};
    context.window = context;
    runInNewContext(
        readFileSync(join(folder, "data/summary.js"), "utf8"),
        context,
        {
            timeout: 5000,
        },
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
        assert.ok(["complete", "partial", "pending"].includes(question.status));
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
        assert.ok(Number.isInteger(item.rows) && item.rows >= 0);
        if (item.href.endsWith(".csv")) {
            const records = csvRecords(readFileSync(file, "utf8"));
            assert.ok(records.length > 0, "CSV needs a header");
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
