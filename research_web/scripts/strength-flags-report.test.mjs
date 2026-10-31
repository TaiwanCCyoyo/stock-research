import * as fs from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import * as path from "node:path";
import * as vm from "node:vm";
import assert from "node:assert/strict";
const root = path.resolve(
    fileURLToPath(
        new URL(
            "../../tasks/20261024-strength-weakening-flags/web-report/",
            import.meta.url,
        ),
    ),
);
class Element {
    constructor(tag) {
        this.tagName = tag;
        this.children = [];
        this.listeners = {};
        this.dataset = {};
        this._text = "";
        this._value = null;
        this.hidden = false;
        this.style = {};
        this.open = false;
        this.focused = false;
    }
    set textContent(v) {
        this._text = String(v);
        this.children = [];
    }
    get textContent() {
        return this._text + this.children.map((x) => x.textContent).join("");
    }
    append(...nodes) {
        this.children.push(...nodes);
    }
    appendChild(node) {
        this.append(node);
        return node;
    }
    replaceChildren(...nodes) {
        this._text = "";
        this.children = nodes;
    }
    setAttribute(k, v) {
        this[k] = v;
    }
    addEventListener(k, v) {
        this.listeners[k] = v;
    }
    querySelector(tag) {
        return descendants(this).find((x) => x.tagName === tag);
    }
    createTHead() {
        const e = new Element("thead");
        this.append(e);
        return e;
    }
    createTBody() {
        const e = new Element("tbody");
        this.append(e);
        return e;
    }
    scrollIntoView() {}
    focus() {
        this.focused = true;
    }
    set value(v) {
        this._value = String(v);
    }
    get value() {
        return (
            this._value ??
            this.children.find((x) => x.selected)?.value ??
            this.children[0]?.value ??
            ""
        );
    }
}
function descendants(e) {
    return e.children.flatMap((c) => [c, ...descendants(c)]);
}
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const ids = new Map();
for (const m of html.matchAll(/<([a-z0-9]+)\b[^>]*\bid="([^"]+)"[^>]*>/g)) {
    const e = new Element(m[1]);
    ids.set(m[2], e);
    if (m[1] === "table") {
        e.createTHead();
        e.createTBody();
    }
}
const callbacks = [];
const document = {
    documentElement: new Element("html"),
    head: new Element("head"),
    createElement: (t) => new Element(t),
    createElementNS: (_, t) => new Element(t),
    querySelector: (q) => {
        const [id, tag] = q.slice(1).split(" ");
        const e = ids.get(id);
        return tag ? e.querySelector(tag) : e;
    },
    addEventListener: (name, callback) => {
        if (name === "DOMContentLoaded") callbacks.push(callback);
    },
    dispatchEvent: () => {},
    currentScript: null,
};
const page = {
    document,
    URL,
    URLSearchParams,
    console,
    location: { hash: "" },
    matchMedia: () => ({ matches: false }),
    CustomEvent: class {},
    addEventListener: () => {},
};
page.window = page;
page.parent = page;
const context = vm.createContext(page);
function run(file) {
    document.currentScript = { src: "https://report.invalid/" + file };
    vm.runInContext(fs.readFileSync(path.join(root, file), "utf8"), context, {
        filename: file,
    });
}
document.head.appendChild = (node) => {
    const local = path.resolve(root, new URL(node.src).pathname.slice(1));
    assert(local.startsWith(root + path.sep));
    vm.runInContext(fs.readFileSync(local, "utf8"), context, {
        filename: local,
    });
    setImmediate(() => node.onload());
    return node;
};
test("saved report supports guided choices and full evidence without changing denominators", async () => {
    run("kit/report-kit.js");
    run("data/manifest.js");
    run("app.js");
    await page.REPORT_READY;
    for (const callback of callbacks) await callback();
    const guided = descendants(ids.get("guided-controls")).filter(
        (e) => e.tagName === "select",
    );
    assert.equal(guided.length, 3);
    assert.match(guided[0].textContent, /已大幅上漲的股票/);
    assert.match(guided[0].textContent, /再加上當天漲至少9.5%/);
    assert(!guided[0].textContent.includes("雙重強勢"));
    assert(ids.get("main-findings"), "the main finding must be present");
    assert.equal(ids.get("main-triggered-rate").textContent, "10.2%");
    assert.equal(ids.get("main-not-triggered-rate").textContent, "22.5%");
    assert.equal(ids.get("main-cost-rate").textContent, "66.0%");
    assert.match(html, /前20日內收盤曾低於60日均線/);
    assert.match(html, /100 元要到 200/);
    assert.match(html, /符合這兩項價格條件的股票/);
    assert.match(html, /收盤價.*是否曾達到起點收盤價的兩倍/s);
    assert.deepEqual(
        guided.map((e) => e.value),
        ["CORE", "X5_MA60", "252"],
    );
    assert.match(ids.get("guided-comparison").textContent, /10\.2%/);
    assert.match(ids.get("guided-comparison").textContent, /22\.5%/);
    assert.match(
        ids.get("guided-comparison").textContent,
        /前20個交易日內曾出現訊號/,
    );
    assert.match(
        ids.get("guided-comparison").textContent,
        /前20個交易日內未出現訊號/,
    );
    assert.match(
        ids.get("guided-comparison").textContent,
        /結果已知的 28,483 筆事件/,
    );
    assert.match(
        ids.get("guided-comparison").textContent,
        /結果已知的 43,908 筆事件/,
    );
    assert.match(
        ids.get("guided-comparison").textContent,
        /尚無法判定結果者另列/,
    );
    assert.match(ids.get("false-abandonment-card").textContent, /66\.0%/);
    assert.equal(ids.get("evidence-disclosure").open, false);
    assert.equal(ids.get("full-results-disclosure").open, false);
    const evidence = html.slice(
        html.indexOf('id="evidence-disclosure"'),
        html.indexOf('id="full-results-disclosure"'),
    );
    assert(evidence.includes('id="detail-title"'));
    assert(!evidence.includes('id="grid-table"'));
    ids.get("guided-evidence-button").listeners.click();
    assert.equal(ids.get("evidence-disclosure").open, true);
    assert.equal(ids.get("full-results-disclosure").open, false);
    assert.equal(ids.get("detail-title").focused, true);
    assert.match(ids.get("detail-content").textContent, /8,733／4,490／0/);
    const messages = [];
    page.parent = { postMessage: (message) => messages.push(message) };
    ids.get("guided-evidence-button").listeners.click();
    ids.get("guided-evidence-button").listeners.click();
    assert.equal(messages.length, 2);
    for (const message of messages) {
        assert.equal(message.type, "rk:reveal");
        assert.equal(message.target, "detail-title");
    }
    assert.equal(ids.get("full-results-disclosure").open, false);
    page.parent = page;
    guided[0].value = "LEAD_B1";
    guided[0].listeners.change();
    assert.match(ids.get("guided-comparison").textContent, /10\.0%/);
    assert.match(ids.get("guided-comparison").textContent, /23\.9%/);
    assert.match(ids.get("false-abandonment-card").textContent, /56\.6%/);
    guided[2].value = "126";
    guided[2].listeners.change();
    assert.match(ids.get("guided-comparison").textContent, /7\.7%/);
    assert.match(ids.get("false-abandonment-card").textContent, /34\.4%/);
    // Every guided choice must use the selected stored row, including a different cost population.
    const summary = page.REPORT_TABLES.summary.flatMap((chunk) =>
        chunk.rows.map((row) =>
            Object.fromEntries(
                chunk.columns.map((column, i) => [column, row[i]]),
            ),
        ),
    );
    for (const group of ["CORE", "LEAD_B1"])
        for (const flag of [
            "Y3",
            "X5_MA20",
            "X5_MA60",
            "X6_10",
            "X6_15",
            "X7",
            "X8",
        ])
            for (const horizon of [126, 252]) {
                [group, flag, String(horizon)].forEach((value, i) => {
                    guided[i].value = value;
                    guided[i].listeners.change();
                });
                const expected = summary.find(
                    (r) =>
                        r.group_id === group &&
                        r.flag_id === flag &&
                        r.horizon === horizon &&
                        r.landmark === 20 &&
                        r.target_multiple === 2 &&
                        r.row_kind === "full" &&
                        r.era === "all" &&
                        r.split === "all",
                );
                assert(
                    expected,
                    "guided choice has exactly a stored main comparison",
                );
                const fills = descendants(ids.get("guided-comparison")).filter(
                    (e) => e.className === "rate-fill",
                );
                assert.deepEqual(
                    fills.map((e) => Number.parseFloat(e.style.width)),
                    [
                        expected.triggered_hit_rate * 100,
                        expected.untriggered_hit_rate * 100,
                    ],
                );
                assert(
                    ids
                        .get("false-abandonment-card")
                        .textContent.includes(
                            page.ReportKit.fmt.pct(
                                expected.false_abandonment_rate,
                            ),
                        ),
                );
            }
    const tbody = (id) => ids.get(id).querySelector("tbody");
    assert.equal(tbody("primary-table").children.length, 28);
    assert.equal(tbody("grid-table").children.length, 1728);
    assert.equal(ids.get("load-error").hidden, false); // fixture does not parse HTML booleans
    assert(!ids.get("primary-table").textContent.includes("載入失敗"));
    const menus = descendants(ids.get("grid-controls")).filter(
        (e) => e.tagName === "select",
    );
    assert.equal(menus.length, 5);
    for (const [i, value] of ["CORE", "2", "252", "20", "X5_MA60"].entries()) {
        menus[i].value = value;
        menus[i].listeners.change();
    }
    assert.equal(tbody("grid-table").children.length, 1);
    tbody("grid-table").children[0].listeners.click();
    assert.match(
        ids.get("detail-title").textContent,
        /已大幅上漲的股票.*252.*20.*60/,
    );
    const detail = ids.get("detail-content").textContent;
    assert(detail.includes("8,733／4,490／0"));
    assert(detail.includes("66.0%"));
    const detailTables = descendants(ids.get("detail-content")).filter(
        (e) => e.tagName === "table",
    );
    assert.equal(detailTables[0].querySelector("tbody").children.length, 6);
    assert.equal(detailTables[1].querySelector("tbody").children.length, 7);
    assert(detailTables[0].textContent.includes("×"));
    assert(detailTables[1].textContent.includes("標準化差"));
    assert(detailTables[2].textContent.includes("未達標但未收低"));
    menus[0].value = "LEAD_B1";
    menus[0].listeners.change();
    tbody("grid-table").children[0].listeners.click();
    assert(ids.get("detail-content").textContent.includes("695／532／0"));
    menus[4].value = "Y1";
    menus[4].listeners.change();
    const nonApplicable = tbody("grid-table").children[0];
    assert(nonApplicable.textContent.includes("不適用"));
    assert.equal(nonApplicable.children[5].textContent, "—");
    const body = html.split("<body>")[1].replace(/<[^>]+>/g, "");
    assert(
        !/\b(?:CORE|LEAD_B1|Y1|Y2|X5_MA60|L20)\b|世代|雜湊|快照|20261024-strength/.test(
            body,
        ),
    );
    console.log(
        JSON.stringify({
            primaryRows: 28,
            fullGridRows: 1728,
            filterAndSelection: true,
            intervalRows: 6,
            sliceRows: 7,
            costDenominators: true,
            ratioUnits: true,
            notApplicableNull: true,
            visualLayoutChecked: false,
        }),
    );
});
