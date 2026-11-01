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
const relatedLinks = [];
for (const m of html.matchAll(
    /<a\b[^>]*\bdata-related-report="([^"]+)"[^>]*>/g,
)) {
    const id = /\bid="([^"]+)"/.exec(m[0])?.[1];
    const e = (id && ids.get(id)) || new Element("a");
    e.dataset.relatedReport = m[1];
    relatedLinks.push(e);
}
const callbacks = [];
const document = {
    documentElement: new Element("html"),
    head: new Element("head"),
    querySelectorAll: (q) => {
        assert.equal(q, "a[data-related-report]");
        return relatedLinks;
    },
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
    location: { hash: "", protocol: "https:" },
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
const body = html.split("<body>")[1].replace(/<[^>]+>/g, "");
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
    assert.match(guided[0].textContent, /強勢股/);
    assert.match(guided[0].textContent, /強勢股＋大漲日/);
    assert(!guided[0].textContent.includes("雙重強勢"));
    assert(ids.get("main-findings"), "the main finding must be present");
    assert.equal(ids.get("main-triggered-rate").textContent, "10.2%");
    assert.equal(ids.get("main-not-triggered-rate").textContent, "22.5%");
    assert.equal(ids.get("main-cost-rate").textContent, "66.0%");
    assert.match(html, /前20日內收盤曾低於60日均線/);
    assert.match(
        html,
        /data-related-report="20261013-pattern-scan"\s+href="\.\.\/\.\.\/20261013-pattern-scan\/web-report\/index\.html"/,
    );
    assert.match(
        html,
        /data-related-report="20261021-momentum-only-doubling"\s+href="\.\.\/\.\.\/20261021-momentum-only-doubling\/web-report\/index\.html"/,
    );
    assert.equal(
        ids.get("pattern-report-link").href,
        "../20261013-pattern-scan/index.html",
    );
    assert.equal(
        ids.get("momentum-report-link").href,
        "../20261021-momentum-only-doubling/index.html",
    );
    const crumb = html.slice(
        html.indexOf('class="lineage-crumb"'),
        html.indexOf("</nav>", html.indexOf('class="lineage-crumb"')),
    );
    assert.match(crumb, /data-related-report="20261013-pattern-scan"/);
    assert.match(
        crumb,
        /data-related-report="20261021-momentum-only-doubling"/,
    );
    assert.match(crumb, /href="#lineage-title"/);
    assert.match(html, /application\/ld\+json/);
    assert.match(html, /"isBasedOn"/);
    assert.match(html, /不超過 62\.5 元/);
    assert.match(html, /不超過 40 元/);
    for (const gone of [
        "不是訊號造成",
        "反面提醒",
        "不能解讀為第20日賣出",
        "不是停損規則",
        "T/(T+F)",
    ])
        assert(!html.includes(gone), `${gone} was removed from the page`);
    assert.match(
        ids.get("explorer-screen-note").textContent,
        /只有「收盤低於60日均線、看一年」這一種在漲幅相近時仍較低/,
    );
    assert.match(
        ids.get("explorer-screen-note").textContent,
        /共 28 格比較中的 2 格/,
    );
    assert.match(
        ids.get("main-adjusted-difference").textContent,
        /起點到第20日漲跌幅相近.*有訊號組仍低 4\.8 個百分點/,
    );
    assert.match(
        ids.get("gap-title").textContent,
        /原始差 12\.3 個百分點；調整後仍差 4\.8 個百分點/,
    );
    assert.match(
        ids.get("main-scope").textContent,
        /七種轉弱訊號、兩個期限共 28 種比較，扣掉第20日漲跌幅差異後，只有「收盤低於60日均線、看一年」在兩種強勢股都仍較低/,
    );
    assert.match(html, /起點到第20日漲跌幅相近|起點到第20日/);
    assert.match(html, /100 ÷\s*1\.6/);
    // The full-horizon share must not be turned into a day-20 exclusion claim.
    assert.match(html, /觀察整段期間，不限第20日/);
    assert.doesNotMatch(html, /第20日若以|一併排除|會錯失|錯失/);
    assert.doesNotMatch(
        ids.get("false-abandonment-card").textContent,
        /第20日若以|一併排除|會錯失|錯失/,
    );
    assert.match(
        ids.get("false-abandonment-card").textContent,
        /觀察整段期間，不限第20日/,
    );
    assert.match(html, /結果在觀察點時已經定了/);
    // First paint carries the final headline figures; the data-driven nodes
    // show a plain loading state, never an empty gap.
    assert.match(html, /id="main-cost-rate">66\.0%</);
    for (const id of ["main-scope", "gap-title", "main-adjusted-difference"])
        assert.match(
            html,
            new RegExp(`id="${id}"[^>]*>[\r\n ]*載入中…`),
            `${id} has a loading state in the first HTML`,
        );
    for (const gone of ["保存判讀", "冷卻", "標準化差", "達標", "階段報告）"])
        assert(!body.includes(gone) || gone === "階段報告）", gone);
    assert.match(html, /型態搭配哪些條件，後來更常翻倍/);
    assert.match(html, /未翻倍且期末收低的比例也較高/);
    assert.match(html, /觀察2、3、5、10倍結果；下方28格主要比較只涵蓋翻倍/);
    assert.match(html, /100 元要到 200/);
    assert.match(html, /符合兩項大幅上漲條件的股票中/);
    assert.match(html, /收盤價.*是否曾達到起點收盤價的兩倍/s);
    assert.deepEqual(
        guided.map((e) => e.value),
        ["CORE", "X5_MA60", "252"],
    );
    assert.match(ids.get("guided-comparison").textContent, /10\.2%/);
    assert.match(ids.get("guided-comparison").textContent, /22\.5%/);
    const guidedHeading = () =>
        descendants(ids.get("guided-comparison")).find(
            (e) => e.className === "comparison-heading",
        );
    assert.match(
        guidedHeading().textContent,
        /在符合上述兩項漲幅條件的股票中，依條件成立後第1至20個交易日內是否曾出現「收盤低於\s*60\s*日均線」分組。比較兩組起點後一年內，收盤價曾達到起點收盤價兩倍的比例。/,
    );
    const standardized = () =>
        descendants(ids.get("guided-comparison")).find(
            (e) => e.className === "standardized-readout",
        )?.textContent;
    assert.match(standardized(), /出現訊號組的翻倍比例比未出現組低/);
    assert(!standardized().includes("負值表示"));
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
    for (const [id, reportId] of [
        ["pattern-report-link", "20261013-pattern-scan"],
        ["momentum-report-link", "20261021-momentum-only-doubling"],
    ]) {
        let prevented = false;
        ids.get(id).listeners.click({
            preventDefault: () => {
                prevented = true;
            },
        });
        assert(
            prevented,
            `${reportId} uses host navigation in the embedded view`,
        );
    }
    assert.deepEqual(
        messages.map(({ type, href }) => ({ type, href })),
        [
            { type: "rk:navigate", href: "#report/20261013-pattern-scan" },
            {
                type: "rk:navigate",
                href: "#report/20261021-momentum-only-doubling",
            },
        ],
    );
    messages.length = 0;
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
    assert.match(
        guidedHeading().textContent,
        /符合上述兩項漲幅條件，且起點當日原始漲幅至少 9\.5% 的股票/,
    );
    guided[2].value = "126";
    guided[2].listeners.change();
    assert.match(ids.get("guided-comparison").textContent, /7\.7%/);
    assert.match(ids.get("false-abandonment-card").textContent, /34\.4%/);
    assert.match(guidedHeading().textContent, /起點後半年內/);
    // Every guided choice must use the selected stored row, including a different cost population.
    const summary = page.REPORT_TABLES.summary.flatMap((chunk) =>
        chunk.rows.map((row) =>
            Object.fromEntries(
                chunk.columns.map((column, i) => [column, row[i]]),
            ),
        ),
    );
    // Bars share one 0-based scale: the next 10% above the highest stored rate.
    const topRate = Math.max(
        ...summary
            .filter(
                (r) =>
                    r.row_kind === "full" &&
                    r.era === "all" &&
                    r.split === "all" &&
                    r.landmark === 20 &&
                    r.target_multiple === 2 &&
                    [126, 252].includes(r.horizon) &&
                    ["CORE", "LEAD_B1"].includes(r.group_id),
            )
            .flatMap((r) => [
                r.triggered_hit_rate ?? 0,
                r.untriggered_hit_rate ?? 0,
            ]),
    );
    const scaleMax = Math.max(10, Math.ceil((topRate * 100) / 10) * 10);
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
                const widths = fills.map((e) =>
                    Number.parseFloat(e.style.width),
                );
                const wanted = [
                    (expected.triggered_hit_rate * 10000) / scaleMax,
                    (expected.untriggered_hit_rate * 10000) / scaleMax,
                ];
                assert.equal(widths.length, 2);
                widths.forEach((w, i) =>
                    assert(Math.abs(w - wanted[i]) < 1e-9),
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
        /強勢股.*截至起點後第 252 個交易日.*內，收盤價曾達到起點收盤價的 2 倍.*20.*60/,
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
    assert(detailTables[1].textContent.includes("調整後差"));
    assert(detailTables[2].textContent.includes("未翻倍但未收低"));
    menus[0].value = "LEAD_B1";
    menus[0].listeners.change();
    tbody("grid-table").children[0].listeners.click();
    assert(ids.get("detail-content").textContent.includes("695／532／0"));
    menus[4].value = "Y1";
    menus[4].listeners.change();
    const nonApplicable = tbody("grid-table").children[0];
    assert(nonApplicable.textContent.includes("不適用"));
    assert.equal(nonApplicable.children[5].textContent, "—");
    // 3x/5x/10x results are never labelled as doubling.
    const gridState = { 0: "CORE", 2: "252", 3: "20", 4: "X5_MA60" };
    for (const [i, v] of Object.entries(gridState)) {
        menus[i].value = v;
        menus[i].listeners.change();
    }
    for (const t of ["3", "5", "10"]) {
        menus[1].value = t;
        menus[1].listeners.change();
        const rowsNow = tbody("grid-table").children;
        assert.equal(rowsNow.length, 1, `${t}x narrows to one row`);
        const head = ids.get("grid-table").textContent;
        assert(head.includes(`有訊號：達到${t}倍的比例`), `${t}x header`);
        assert(!head.includes("翻倍"), `${t}x grid has no doubling wording`);
        rowsNow[0].listeners.click();
        const d = ids.get("detail-content").textContent;
        for (const phrase of [
            `達到${t}倍的比例比`,
            `最後達到${t}倍者中，首次達到${t}倍前曾有訊號的比例`,
            `首次達到${t}倍前：有訊號／無訊號／訊號不明`,
            `未達到${t}倍且收低`,
            `移除達到${t}倍事件最多`,
        ])
            assert(d.includes(phrase), `${t}x detail has ${phrase}`);
        assert(!d.includes("翻倍"), `${t}x detail has no doubling wording`);
    }
    menus[1].value = "2";
    menus[1].listeners.change();
    tbody("grid-table").children[0].listeners.click();
    assert(ids.get("detail-content").textContent.includes("首次翻倍前"));
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

test("a failed data load never leaves a blank or endless loading state", async () => {
    const failDocument = {
        ...document,
        addEventListener: (name, callback) => {
            if (name === "DOMContentLoaded") failCallbacks.push(callback);
        },
    };
    const failCallbacks = [];
    const failPage = {
        document: failDocument,
        URL,
        URLSearchParams,
        console,
        location: { hash: "", protocol: "file:", reload: () => {} },
        matchMedia: () => ({ matches: false }),
        CustomEvent: class {},
        addEventListener: () => {},
    };
    failPage.window = failPage;
    failPage.parent = failPage;
    const failContext = vm.createContext(failPage);
    for (const id of [
        "main-scope",
        "gap-title",
        "main-adjusted-difference",
        "gap-direct-value",
        "gap-adjusted-value",
        "main-triggered-count",
        "explorer-screen-note",
        "guided-comparison",
        "false-abandonment-card",
    ])
        ids.get(id).textContent = "載入中…";
    ids.get("load-error").hidden = true;
    document.currentScript = { src: "https://report.invalid/app.js" };
    vm.runInContext(
        fs.readFileSync(path.join(root, "app.js"), "utf8"),
        failContext,
    );
    for (const callback of failCallbacks) await callback();
    assert.equal(ids.get("load-error").hidden, false);
    assert(ids.get("load-retry").listeners.click, "retry button is wired");
    for (const id of [
        "main-scope",
        "gap-title",
        "main-adjusted-difference",
        "gap-direct-value",
        "main-triggered-count",
        "guided-comparison",
        "false-abandonment-card",
    ])
        assert.match(ids.get(id).textContent, /無法載入/, id);
    assert.match(html, /id="load-retry"/);
});
