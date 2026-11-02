/* Display saved candidate-direction counts; no research calculation. */
(() => {
    // Related-report links: inside the viewer iframe, ask the host to navigate.
    function relatedReportLinks(root = document) {
        const hosted = ["http:", "https:"].includes(window.location.protocol);
        for (const link of root.querySelectorAll("a[data-related-report]")) {
            const reportId = link.getAttribute("data-related-report");
            if (!reportId) continue;
            if (hosted && window.parent !== window)
                link.href = `../${reportId}/index.html`;
            link.addEventListener("click", (event) => {
                if (window.parent === window) return;
                event.preventDefault();
                window.parent.postMessage(
                    { type: "rk:navigate", href: `#report/${reportId}` },
                    "*",
                );
            });
        }
    }
    relatedReportLinks();

    // Headline: per-pattern unconditional comparison from the saved
    // comparisonSummary (horizon 252), plus the saved per-pattern counts of the
    // 92 condition sets (interpretation-evidence.json candidate_by_family, 252).
    // No research calculation: only differences and ratios of stored values.
    const conditionCounts = {
        B1: [46, 43, 2],
        B2: [23, 60, 9],
        B3: [32, 13, 45],
        B4: [64, 27, 0],
        H1: [55, 36, 0],
        L1: [74, 18, 0],
        L2: [32, 60, 0],
        L3: [7, 82, 3],
        P1: [52, 32, 5],
        R1: [11, 67, 10],
        R2: [13, 53, 22],
        R3: [23, 34, 35],
    };
    const names = {
        H1: "HHHL v4 突破型態",
        B1: "杯形突破",
        B2: "布林通道收縮後突破",
        B3: "平台突破",
        B4: "跳空突破",
        R1: "跌破區間支撐後收復",
        R2: "跌深近低的看漲 K 棒",
        R3: "RSI 背離",
        P1: "突破後回測",
        L1: "突破 60 日高點",
        L2: "近五日回落、收盤仍高於 60 日均線",
        L3: "跌破 20 日低點後收復",
    };
    const GROUPS = 92;
    // Which pattern a saved table row belongs to (target, group or bin id).
    function rowCode(row) {
        const direct = row.target || row.target_pattern_id;
        if (direct) return String(direct);
        const group = row.group || row.group_id;
        if (group) return String(group).split(":")[0];
        const bin = row.bin_id || row.candidate_id;
        return bin ? String(bin).split(":")[1] || null : null;
    }
    // Detail links into the question tables (first table of each question).
    const questionLinks = [
        ["Q2", "加條件後的各組結果（問題 2：此型態固定的十組條件）"],
        ["Q3", "同條件、沒有型態的對照（問題 3）"],
        ["Q4", "已翻倍的段落有多少出現過它（問題 4）"],
        ["Q5", "沒翻倍者的途中走勢（問題 5）"],
        ["Q6", "轉弱訊號的代價（問題 6）"],
    ];
    // Same series as the lineage section: the other studies in this line.
    const relatedReports = [
        [
            "20261021-momentum-only-doubling",
            "只看強勢條件的翻倍機率（不要求型態）",
        ],
        [
            "20261024-strength-weakening-flags",
            "已大漲的股票，接著轉弱，之後還會翻倍嗎？",
        ],
    ];
    const tableId = (question) => `${question}-table-1`;
    function tableRows(question) {
        const q = (window.REPORT_DATA?.questions || []).find(
            (item) => item?.id === question,
        );
        return q?.tables?.[0]?.rows || [];
    }
    function rowMatcher(code) {
        return (row) =>
            rowCode(row) === code &&
            (row.horizon === undefined || row.horizon === 252);
    }
    function patternModel() {
        const summary = window.REPORT_DATA?.comparisonSummary;
        if (!summary || !Array.isArray(summary.rows)) return null;
        const base = (summary.baselines || []).find((r) => r.horizon === 252);
        if (!base || !(base.hit_rate > 0)) return null;
        const rows = summary.rows
            .filter((r) => r.horizon === 252 && names[r.target])
            .map((r) => ({ ...r, rate: r.baseline_multiple * base.hit_rate }))
            .sort((x, y) => y.delta_pp - x.delta_pp);
        return rows.map((r, index) => {
            const [higher, lower, incomparable] = conditionCounts[r.target];
            const enough = r.known_n >= 100 && r.control_known_n >= 100;
            return {
                code: r.target,
                name: names[r.target],
                rank: index + 1,
                enough,
                rate: r.rate,
                control: r.rate - r.delta_pp / 100,
                delta: r.delta_pp,
                known: r.known_n,
                higher,
                lower,
                incomparable,
                same: GROUPS - higher - lower - incomparable,
                small: higher + lower < 10,
                links: questionLinks
                    .filter(([q]) => tableRows(q).some(rowMatcher(r.target)))
                    .map(([q]) => q),
            };
        });
    }
    window.patternRank = { rowCode, patternModel, questionLinks, tableId };

    function renderHeadlineTable() {
        const body = document.getElementById("headline-rows");
        const model = patternModel();
        if (!body || !model) return;
        const pct = (v) => `${(v * 100).toFixed(1)}%`;
        const int = (v) => v.toLocaleString("en-US");
        const fragment = document.createDocumentFragment();
        for (const r of model) {
            const tr = document.createElement("tr");
            const name = document.createElement("td");
            name.textContent = `${r.name}（${r.code}）`;
            const plain = document.createElement("td");
            const conditional = document.createElement("td");
            if (!r.enough) {
                plain.textContent = "樣本不足，不下結論";
            } else {
                const sign = r.delta > 0 ? "高" : "低";
                const strong = document.createElement("span");
                strong.className = r.delta > 0 ? "delta-up" : "delta-down";
                strong.textContent = `${pct(r.rate)} 對 ${pct(r.control)}`;
                const small = document.createElement("small");
                const size = Math.abs(r.delta);
                small.textContent = `${sign} ${size < 0.05 ? "不到 0.1" : size.toFixed(1)} 個百分點 · 樣本 ${int(r.known)}`;
                plain.append(strong, small);
            }
            if (r.small) {
                conditional.textContent = "樣本不足，不下結論";
            } else {
                conditional.textContent = `${r.higher} 組較高 · ${r.lower} 組較低`;
                if (r.incomparable > 0) {
                    const small = document.createElement("small");
                    small.textContent = `另有 ${r.incomparable} 組無法比較`;
                    conditional.append(small);
                }
            }
            tr.append(name, plain, conditional);
            fragment.append(tr);
        }
        body.replaceChildren(fragment);
    }
    renderHeadlineTable();

    // Ranking ladder + detail pane (replaces the 12-row table as the first
    // view; the table stays available). Display only, from patternModel().
    function renderRankView() {
        const view = document.getElementById("rank-view");
        const model = patternModel();
        if (!view || !model || !model.length) return;
        const layout = document.getElementById("rank-layout");
        const ladder = document.getElementById("rank-ladder");
        const pane = document.getElementById("rank-pane");
        const tableWrap = document.getElementById("headline-table-wrap");
        const switcher = document.getElementById("rank-switch");
        const byCode = Object.fromEntries(model.map((p) => [p.code, p]));
        const controlTxts = [
            ...new Set(model.map((p) => `${(p.control * 100).toFixed(1)}%`)),
        ];
        const baseTxt =
            controlTxts.length === 1 ? controlTxts[0] : "各型態自己的對照";
        const pct = (v) => `${(v * 100).toFixed(1)}%`;
        const int = (v) => v.toLocaleString("en-US");
        const sizeText = (p) => {
            const size = Math.abs(p.delta);
            return size < 0.05 ? "不到 0.1" : size.toFixed(1);
        };
        const signed = (p) =>
            Math.abs(p.delta) < 0.05
                ? "低 不到 0.1"
                : `${p.delta > 0 ? "+" : "−"}${sizeText(p)}`;
        const h = (tag, className, ...kids) => {
            const el = document.createElement(tag);
            if (className) el.className = className;
            for (const kid of kids) {
                if (kid === null || kid === undefined || kid === false)
                    continue;
                el.append(
                    typeof kid === "object"
                        ? kid
                        : document.createTextNode(String(kid)),
                );
            }
            return el;
        };
        const attr = (el, values) => {
            for (const [key, value] of Object.entries(values))
                el.setAttribute(key, value);
            return el;
        };
        const clean = (el) => el.textContent.replace(/\s+/g, " ").trim();

        document.getElementById("rank-title").textContent =
            `追蹤約一年（252 個交易日）：比一般合格日（隔 20 個交易日取一天，翻倍比例 ${baseTxt}）高或低幾個百分點`;

        // ---- ladder ----
        const MIN = -4;
        const MAX = 6;
        const pos = (v) => ((v - MIN) / (MAX - MIN)) * 100;
        const ticks = [-3, 0, 3, 6];
        const axis = document.getElementById("rank-axis");
        for (const t of ticks) {
            const span = h(
                "span",
                null,
                t > 0 ? `+${t}` : t < 0 ? `−${-t}` : "0",
            );
            span.style.left = `${pos(t)}%`;
            axis.append(span);
        }
        for (const p of model) {
            const li = h("li", "rank-row");
            attr(li, {
                role: "option",
                id: `rank-row-${p.code}`,
                "data-code": p.code,
                "aria-selected": "false",
                tabindex: "-1",
                "aria-label": `第 ${p.rank} 名 ${p.name}，${pct(p.rate)} 對 ${pct(p.control)}，${p.delta > 0 ? "高" : "低"} ${sizeText(p)} 個百分點`,
            });
            const track = h("span", "rank-track");
            track.setAttribute("aria-hidden", "true");
            for (const t of ticks.filter(Boolean)) {
                const tick = h("span", "rank-tick");
                tick.style.left = `${pos(t)}%`;
                track.append(tick);
            }
            const zero = h("span", "rank-zero");
            zero.style.left = `${pos(0)}%`;
            const stem = h("span", "rank-stem");
            stem.style.left = `${pos(Math.min(0, p.delta))}%`;
            stem.style.width = `${pos(Math.max(0, p.delta)) - pos(Math.min(0, p.delta))}%`;
            const dot = h(
                "span",
                p.delta < 0 ? "rank-dot is-below" : "rank-dot",
            );
            dot.style.left = `${pos(p.delta)}%`;
            track.append(zero, stem, dot);
            li.append(
                h("span", "rank-no", p.rank),
                h("span", "rank-name", p.name),
                track,
                h("span", "rank-val", p.enough ? signed(p) : "—"),
            );
            ladder.append(li);
        }

        // ---- detail pane: text and shapes come from the guide on this page ----
        const guide = (code) => {
            const article = document.getElementById(`pg-${code}`);
            const result = { first: "", svgs: [], captions: [], examples: [] };
            if (!article) return result;
            for (const child of Array.from(article.children)) {
                if (child.tagName.toLowerCase() === "svg")
                    result.svgs.push(child.cloneNode(true));
                else if (child.tagName === "P") {
                    const text = clean(child);
                    if (!child.className.includes("pattern-eg")) {
                        if (!result.first)
                            result.first = text.includes("。")
                                ? text.slice(0, text.indexOf("。") + 1)
                                : text;
                    } else if (/^(有柄)?例/.test(text))
                        result.examples.push(text);
                    else result.captions.push(text);
                }
            }
            return result;
        };

        const segment = (p) => {
            const parts = [
                ["h", "較高", p.higher],
                ["s", "相同", p.same],
                ["l", "較低", p.lower],
                ["x", "無法比較", p.incomparable],
            ];
            const bar = h("div", "seg");
            attr(bar, {
                role: "img",
                "aria-label": parts
                    .map(([, label, n]) => `${n} 組${label}`)
                    .join("、"),
            });
            const legend = h("ul", "seg-legend");
            for (const [kind, label, n] of parts) {
                if (n) {
                    const part = h("i", `seg-${kind}`);
                    part.style.width = `${(n / GROUPS) * 100}%`;
                    bar.append(part);
                }
                legend.append(
                    h(
                        "li",
                        null,
                        h("i", `seg-key seg-${kind}`),
                        `${label} ${n}`,
                    ),
                );
            }
            return [bar, legend];
        };

        const detailLink = (text, href, kind, extra) => {
            const a = h("a", null, text);
            a.href = href;
            a.setAttribute("data-detail", kind);
            for (const [key, value] of Object.entries(extra || {}))
                a.setAttribute(key, value);
            return a;
        };

        function buildPane(p) {
            const g = guide(p.code);
            const i = model.indexOf(p);
            const prev = model[i - 1];
            const next = model[i + 1];
            const back = h("button", "rank-btn rank-back", "‹ 返回排行");
            attr(back, { type: "button", "data-act": "back" });
            const title = h(
                "h3",
                "rank-ptitle",
                p.name,
                h("small", null, p.code),
            );
            title.id = "rank-ptitle";
            title.tabIndex = -1;
            const stage = h("div", "stage");
            const shapes = h("div", "stage-shapes");
            shapes.setAttribute("aria-hidden", "true");
            if (g.svgs.length) for (const svg of g.svgs) shapes.append(svg);
            else shapes.append(h("div", "stage-none", "示意圖未帶入"));
            stage.append(shapes);
            if (g.captions.length)
                stage.append(h("p", "stage-cap", g.captions.join(" ")));
            stage.append(h("hr", "stage-sep"));
            stage.append(h("p", "stage-label", "不加條件 · 追蹤約一年"));
            if (p.enough)
                stage.append(
                    h(
                        "div",
                        "cmp",
                        h("b", null, pct(p.rate)),
                        h("span", null, `對 一般合格日 ${pct(p.control)}`),
                    ),
                    h(
                        "p",
                        "stage-foot",
                        `${p.delta > 0 ? "高" : "低"} ${sizeText(p)} 個百分點 · 樣本 ${int(p.known)} 件`,
                    ),
                );
            else stage.append(h("p", null, "樣本不足，不下結論"));
            stage.append(h("hr", "stage-sep"));
            stage.append(
                h(
                    "p",
                    "stage-label",
                    `加上篩選條件後 · ${GROUPS} 組，各自和同條件、沒型態的事件比`,
                ),
            );
            if (p.small) stage.append(h("p", null, "樣本不足，不下結論"));
            else stage.append(...segment(p));

            const links = h("ul", "rank-links");
            links.append(
                h(
                    "li",
                    null,
                    detailLink("精確定義與判定細節", `#pg-${p.code}`, "guide", {
                        "data-code": p.code,
                    }),
                ),
                h(
                    "li",
                    null,
                    detailLink(
                        "這個型態在完整對照表的那一列",
                        `#fs-row-${p.code}`,
                        "family",
                        { "data-code": p.code },
                    ),
                ),
            );
            for (const [q, label] of questionLinks)
                if (p.links.includes(q))
                    links.append(
                        h(
                            "li",
                            null,
                            detailLink(label, `#${tableId(q)}`, "table", {
                                "data-code": p.code,
                                "data-table": tableId(q),
                            }),
                        ),
                    );
            const related = h("ul", "rank-links");
            for (const [id, label] of relatedReports) {
                const a = h("a", null, label);
                a.href = `../../${id}/web-report/index.html`;
                a.setAttribute("data-related-report", id);
                related.append(h("li", null, a));
            }

            const eg = h(
                "div",
                "rank-eg",
                h("h4", null, "例子（以 100 元示意）"),
            );
            for (const text of g.examples) eg.append(h("p", null, text));
            const nav = h("div", "rank-nav");
            const step = (target, label) => {
                const b = h("button", "rank-btn", label);
                attr(b, { type: "button", "data-go": target.code });
                return b;
            };
            nav.append(
                prev ? step(prev, `‹ 上一名：${prev.name}`) : h("span"),
                next ? step(next, `下一名：${next.name} ›`) : h("span"),
            );
            pane.replaceChildren(
                back,
                h(
                    "div",
                    "rank-phead",
                    title,
                    h("span", "rank-prank", `第 ${p.rank} 名／${model.length}`),
                ),
                h("p", "rank-def", g.first),
                stage,
                eg,
                h(
                    "div",
                    "rank-detail",
                    h("h4", null, "想看更細的資料"),
                    links,
                    h("p", "rank-related-label", "同一系列的其他研究"),
                    related,
                ),
                nav,
            );
            relatedReportLinks(pane);
        }

        // ---- state, hash, history ----
        let sel = model[0].code;
        let stacked = false;
        let inDetail = false;
        let listScroll = 0;
        let pushed = false;
        const readHash = () => {
            const raw = location.hash.replace(/^#/, "");
            return new URLSearchParams(raw.includes("=") ? raw : "");
        };
        const readCode = () => {
            const code = readHash().get("pattern");
            return code && byCode[code] ? code : null;
        };
        const hashFor = (code) => {
            const params = readHash();
            if (code) params.set("pattern", code);
            else params.delete("pattern");
            const text = params.toString();
            return text ? `#${text}` : `${location.pathname}${location.search}`;
        };
        const writeHash = (code, push) => {
            try {
                if (push)
                    history.pushState({ pattern: code }, "", hashFor(code));
                else history.replaceState(history.state, "", hashFor(code));
            } catch {
                /* some sandboxes refuse history updates; the view still works */
            }
        };
        function select(code, focusRow) {
            sel = code;
            for (const row of ladder.children) {
                const on = row.getAttribute("data-code") === code;
                row.setAttribute("aria-selected", String(on));
                row.tabIndex = on ? 0 : -1;
            }
            ladder.setAttribute("aria-activedescendant", `rank-row-${code}`);
            buildPane(byCode[code]);
            if (focusRow)
                document
                    .getElementById(`rank-row-${code}`)
                    .focus({ preventScroll: true });
        }
        function enterDetail(code, push) {
            select(code);
            if (!inDetail) listScroll = window.scrollY;
            inDetail = true;
            document.body.classList.add("rank-open");
            writeHash(code, push);
            pushed = pushed || push;
            window.scrollTo(0, 0);
            document
                .getElementById("rank-ptitle")
                .focus({ preventScroll: true });
        }
        function leaveDetail(restore) {
            if (!inDetail) return;
            inDetail = false;
            pushed = false;
            document.body.classList.remove("rank-open");
            if (restore) {
                window.scrollTo(0, listScroll);
                document
                    .getElementById(`rank-row-${sel}`)
                    ?.focus({ preventScroll: true });
            }
        }
        ladder.addEventListener("click", (event) => {
            const row = event.target.closest(".rank-row");
            if (!row) return;
            const code = row.getAttribute("data-code");
            if (stacked) enterDetail(code, true);
            else {
                select(code, true);
                writeHash(code, false);
            }
        });
        ladder.addEventListener("keydown", (event) => {
            const i = model.findIndex((p) => p.code === sel);
            const to = {
                ArrowDown: i + 1,
                ArrowUp: i - 1,
                Home: 0,
                End: model.length - 1,
            }[event.key];
            if (to !== undefined) {
                event.preventDefault();
                const code =
                    model[Math.max(0, Math.min(model.length - 1, to))].code;
                select(code, true);
                if (!stacked) writeHash(code, false);
            } else if (
                (event.key === "Enter" || event.key === " ") &&
                stacked
            ) {
                event.preventDefault();
                enterDetail(sel, true);
            }
        });
        const clearTarget = () => {
            for (const el of document.querySelectorAll(".is-target"))
                el.classList.remove("is-target");
        };
        const reveal = (el) => {
            if (!el) return;
            el.classList.add("is-target");
            el.scrollIntoView({ block: "center", behavior: "instant" });
        };
        function followDetail(link) {
            const code = link.getAttribute("data-code");
            const kind = link.getAttribute("data-detail");
            if (inDetail) {
                // The target sits outside the detail page: return to the page first.
                leaveDetail(false);
                writeHash(null, false);
            }
            clearTarget();
            if (kind === "guide") {
                const details = document.querySelector(
                    ".pattern-guide-details",
                );
                if (details) details.open = true;
                const article = document.getElementById(`pg-${code}`);
                const precise = article?.querySelector(".pattern-precise");
                if (precise) precise.open = true;
                reveal(article);
            } else if (kind === "family") {
                const details = document.getElementById("family-details");
                if (details) details.open = true;
                const horizon = document.getElementById(
                    "family-summary-horizon",
                );
                if (horizon && horizon.value !== "252") {
                    horizon.value = "252";
                    horizon.dispatchEvent(new Event("change"));
                }
                reveal(document.getElementById(`fs-row-${code}`));
            } else if (kind === "table") {
                const jump =
                    window.reportTableJump?.[link.getAttribute("data-table")];
                const article = jump ? jump(rowMatcher(code)) : null;
                reveal(article?.querySelector("tr.is-target") || article);
            }
        }
        pane.addEventListener("click", (event) => {
            if (event.target.closest("[data-act=back]")) {
                if (pushed) history.back();
                else {
                    writeHash(null, false);
                    leaveDetail(true);
                }
                return;
            }
            const go = event.target.closest("[data-go]");
            if (go) {
                const code = go.getAttribute("data-go");
                if (inDetail) enterDetail(code, false);
                else {
                    select(code);
                    writeHash(code, false);
                }
                return;
            }
            const link = event.target.closest("a[data-detail]");
            if (link) {
                event.preventDefault();
                followDetail(link);
            }
        });
        document.addEventListener("keydown", (event) => {
            if (event.key === "Escape" && inDetail)
                pane.querySelector("[data-act=back]")?.click();
        });
        function syncFromHash() {
            const code = readCode();
            if (code) {
                if (stacked) enterDetail(code, false);
                else if (code !== sel) select(code);
            } else if (inDetail) {
                leaveDetail(true);
            }
        }
        window.addEventListener("popstate", syncFromHash);
        window.addEventListener("hashchange", syncFromHash);

        // ---- view switch: ranking or the original table ----
        function setView(name) {
            const rank = name === "rank";
            layout.hidden = !rank;
            tableWrap.hidden = rank;
            for (const button of switcher.querySelectorAll("button"))
                button.setAttribute(
                    "aria-pressed",
                    String(button.getAttribute("data-view") === name),
                );
            if (!rank && inDetail) {
                leaveDetail(false);
                writeHash(null, false);
            }
            measure();
        }
        switcher.addEventListener("click", (event) => {
            const button = event.target.closest("button[data-view]");
            if (button) setView(button.getAttribute("data-view"));
        });

        function measure() {
            if (layout.hidden) return;
            const next = layout.clientWidth < 680;
            if (next === stacked) return;
            stacked = next;
            view.classList.toggle("is-stacked", stacked);
            if (!stacked && inDetail) leaveDetail(false);
        }
        layout.hidden = false;
        tableWrap.hidden = true;
        switcher.hidden = false;
        select(readCode() || model[0].code);
        measure();
        if ("ResizeObserver" in window)
            new ResizeObserver(measure).observe(view);
        else window.addEventListener("resize", measure);
        if (readCode() && stacked) enterDetail(readCode(), false);
    }
    renderRankView();

    const selector = document.getElementById("reader-horizon");
    if (!selector) return;
    const counts = { 126: [465, 497, 19, 123], 252: [432, 525, 16, 131] };
    const labels = [
        "有型態的翻倍比例較高",
        "有型態的翻倍比例較低",
        "兩邊比例相同",
        "無法比較",
    ];
    function render() {
        const horizon = Number(selector.value);
        const values = counts[horizon];
        document.getElementById("reader-comparison-answer").textContent =
            `追蹤 ${horizon} 個交易日：${values[0]} 組較高，${values[1]} 組較低。`;
        const bars = document.getElementById("reader-comparison-bars");
        bars.replaceChildren();
        values.forEach((value, index) => {
            const row = document.createElement("div");
            row.className = "reader-bar-row";
            const label = document.createElement("span");
            label.textContent = labels[index];
            const track = document.createElement("div");
            track.className = "reader-bar-track";
            const fill = document.createElement("div");
            fill.className = `reader-bar-fill tone-${index}`;
            fill.style.width = `${(value / 1104) * 100}%`;
            track.setAttribute("aria-hidden", "true");
            track.append(fill);
            const number = document.createElement("strong");
            number.textContent = `${value}／1,104`;
            row.append(label, track, number);
            bars.append(row);
        });
        document.getElementById("reader-sample-note").textContent =
            horizon === 252
                ? "約一年的 1,104 組中，571 組的型態樣本不足 100 件（含 80 組為零件）；比例很高的組合要連同樣本數一起看。"
                : "各組的樣本數、未知數與原始比例在下方各問題的表格中。";
    }
    selector.addEventListener("change", render);
    render();
})();
