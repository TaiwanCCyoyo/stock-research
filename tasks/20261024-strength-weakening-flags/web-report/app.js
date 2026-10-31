(function () {
    "use strict";

    const $ = (selector) => document.querySelector(selector);
    const kit = () => window.ReportKit;
    const labelMap = (name) =>
        (window.REPORT_META && window.REPORT_META[name]) || {};
    const FIELD_ALIASES = {
        group: ["group_id"],
        flag: ["flag_id"],
        primary: ["is_primary", "primary_cell"],
        triggered_rate: [
            "rate_triggered",
            "flagged_rate",
            "triggered_hit_rate",
        ],
        not_triggered_rate: [
            "rate_not_triggered",
            "unflagged_rate",
            "not_triggered_hit_rate",
            "untriggered_hit_rate",
        ],
        triggered_known_n: [
            "known_triggered_n",
            "triggered_n",
            "triggered_known",
        ],
        not_triggered_known_n: [
            "known_not_triggered_n",
            "not_triggered_n",
            "not_triggered_known",
            "untriggered_known_n",
            "all_false_known_n",
        ],
        pooled_difference: ["difference_pooled", "pooled_diff"],
        standardized_difference: [
            "difference_standardized",
            "standardized_diff",
        ],
        false_alarm_cost: ["fa_cost", "false_alarm_rate"],
    };
    const val = (row, ...names) => {
        for (const name of names) {
            const expanded = [name, ...(FIELD_ALIASES[name] || [])];
            for (const alias of expanded)
                if (row && row[alias] !== undefined) return row[alias];
        }
        return null;
    };
    const text = (value) =>
        value === null || value === undefined || value === ""
            ? "—"
            : String(value);
    const human = (kind, value) => {
        if (value === null || value === undefined) return "—";
        const maps = {
            group: labelMap("groupLabels"),
            flag: labelMap("flagLabels"),
            verdict: labelMap("verdictLabels"),
            era: labelMap("eraLabels"),
            split: labelMap("splitLabels"),
            row: labelMap("rowKindLabels"),
            basis: labelMap("basisLabels"),
            rise: labelMap("riseLabels"),
        };
        const map = maps[kind] || {};
        const key = String(value);
        if (kind === "group" && key === "CORE") return "已大幅上漲的股票";
        if (kind === "group" && key === "LEAD_B1")
            return "再加上當天漲至少9.5%";
        if (Object.prototype.hasOwnProperty.call(map, key)) return map[key];
        if (kind === "horizon") return `${key.replace(/^H/, "")} 日`;
        if (kind === "landmark") return `第 ${key.replace(/^L/, "")} 日`;
        if (kind === "split" && key === "all") return "合併切片";
        const simple = {
            CORE: "已大幅上漲的股票",
            LEAD_B1: "再加上當天漲至少9.5%",
            "C-base": "全市場基準",
            "C-base-daily": "一般股票日",
            "C-52w": "相對 52 週高點基準",
            "C-52w-daily": "一年新高且放量",
            Y1: "不適用",
            Y2: "不適用",
            Y3: "跌破起點固定支撐低點",
            X5_MA20: "收盤低於 20 日均線",
            X5_MA60: "收盤低於 60 日均線",
            X6_10: "較起點下跌至少 10%",
            X6_15: "較起點下跌至少 15%",
            X7: "收盤低於布林下軌",
            X8: "新確認較低高點",
            daily: "每日",
            cooled: "冷卻後",
            all: "整體期間／合併",
            development: "固定股票半部一",
            "cross-check": "固定股票半部二",
            full: "整體資料",
            drop_best_year: "移除本格達標事件最多的年份",
            drop_best_stock: "移除本格達標事件最多的股票",
            lt1: "低於 1 倍",
            b1_1p10: "1.00–1.10 倍",
            b1p10_1p25: "1.10–1.25 倍",
            ge1p25: "至少 1.25 倍",
            unknown: "未知",
            H126: "126 日",
            H252: "252 日",
            H504: "504 日",
            L5: "第 5 日",
            L10: "第 10 日",
            L20: "第 20 日",
            L40: "第 40 日",
            2: "2 倍",
            3: "3 倍",
            5: "5 倍",
            10: "10 倍",
            triggered: "已觸發",
            not_triggered: "未觸發",
            untriggered: "未觸發",
            all_false: "未觸發",
            not_applicable: "不適用",
            pooled: "合併估計",
            pooled_difference: "合併差",
            standardized: "標準化估計",
            standardized_difference: "標準化差",
            stock: "以股票為單位重抽",
            two_way: "股票與年份重抽",
            two_way_cluster: "股票與年份重抽",
            hit_rate_ratio: "達標率比",
            difference_pooled: "合併差",
            difference_standardized: "標準化差",
            "2010-2012": "2010–2012 年",
            "2013-2018": "2013–2018 年",
            "2019+": "2019 年起",
        };
        if (kind === "state" && key === "unknown") return "訊號狀態未知";
        if (kind === "era" && key === "all") return "整體期間";
        if (kind === "era" && /^\d{4}$/.test(key)) return `${key} 年`;
        return (
            simple[key] ||
            (kind === "verdict"
                ? "未提供判讀"
                : kind === "state"
                  ? "未知狀態"
                  : "未分類")
        );
    };
    const horizonLabel = (value) =>
        value == null ? "—" : `${String(value).replace(/^H/, "")} 日`;
    const landmarkLabel = (value) =>
        value == null ? "—" : `第 ${String(value).replace(/^L/, "")} 日`;
    const fmtPct = (v) => kit().fmt.pct(typeof v === "number" ? v : null);
    const fmtPp = (v) => kit().fmt.pp(typeof v === "number" ? v : null);
    const fmtRatio = (v) => {
        const ratio = typeof v === "number" ? kit().fmt.ratio(v, 1) : null;
        return ratio === null ? "—" : `${ratio.toFixed(2)}×`;
    };
    const fmtInt = (v) => kit().fmt.int(typeof v === "number" ? v : null);
    const sumStored = (row, names) => {
        const values = names
            .map((name) => val(row, name))
            .filter((value) => typeof value === "number");
        return values.length
            ? values.reduce((sum, value) => sum + value, 0)
            : null;
    };
    const make = (tag, cls, content) => {
        const node = document.createElement(tag);
        if (cls) node.className = cls;
        if (content !== undefined) node.textContent = content;
        return node;
    };
    const appendCell = (row, value, className) => {
        const cell = document.createElement("td");
        if (className) cell.className = className;
        cell.textContent = text(value);
        row.append(cell);
        return cell;
    };
    const table = (element, columns, rows, onPick) => {
        const thead = element.querySelector("thead");
        const tbody = element.querySelector("tbody");
        thead.replaceChildren();
        tbody.replaceChildren();
        const hr = document.createElement("tr");
        columns.forEach((c) => {
            const th = make("th", "", c.label);
            th.scope = "col";
            hr.append(th);
        });
        thead.append(hr);
        if (!rows.length) {
            const tr = document.createElement("tr");
            const td = make("td", "muted", "沒有符合條件的保存資料。");
            td.colSpan = columns.length;
            tr.append(td);
            tbody.append(tr);
            return;
        }
        rows.forEach((row) => {
            const tr = document.createElement("tr");
            if (onPick) {
                tr.tabIndex = 0;
                tr.className = "selectable";
                tr.setAttribute("role", "button");
                tr.addEventListener("click", () => onPick(row));
                tr.addEventListener("keydown", (event) => {
                    if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onPick(row);
                    }
                });
            }
            columns.forEach((c) =>
                appendCell(
                    tr,
                    c.render ? c.render(row) : text(val(row, ...c.keys)),
                    c.className,
                ),
            );
            tbody.append(tr);
        });
    };
    const key = (row, field) => String(val(row, field) ?? "");
    const splitAll = (row) => key(row, "split") === "all";
    const eraAll = (row) => key(row, "era") === "all";
    const full = (row) => key(row, "row_kind") === "full";
    const yes = (v) => v === true || v === 1 || v === "1" || v === "true";
    const chunkRecords = (chunks) =>
        (chunks || []).flatMap((chunk) => kit().records(chunk));
    const summaryRows = () => chunkRecords(window.REPORT_TABLES.summary);
    let selected = null;
    let rows = [];

    const guidedState = {
        group: "CORE",
        flag: "X5_MA60",
        horizon: "252",
        row: null,
    };

    const flagExplanations = {
        Y3: "觀察收盤是否跌破起點時已確認的固定支撐價。",
        X5_MA20:
            "20 日均線是近期 20 個交易日的平均收盤價；觀察期間內收盤曾低於它，不要求當天剛跌破。",
        X5_MA60:
            "60 日均線是近期 60 個交易日的平均收盤價；觀察期間內收盤曾低於它，不要求當天剛跌破。",
        X6_10: "觀察收盤是否比起點價格低至少 10%。",
        X6_15: "觀察收盤是否比起點價格低至少 15%。",
        X7: "布林下軌是依近期價格波動估出的下方界線；觀察收盤是否低於它。",
        X8: "觀察新的波段高點是否低於前一個已確認高點。",
    };

    function verdictExplanation(row) {
        const verdict = key(row, "verdict");
        const explanations = {
            weakens_beyond_drop:
                "把觀察點時漲跌幅相近的事件分組比較後，仍支持出現訊號組的翻倍比例較低。這是歷史關聯，不代表訊號造成結果。",
            weakens_with_drop:
                "直接比較時，出現訊號組的翻倍比例較低；考慮觀察點時的漲跌幅後，證據還不夠明確。這不代表訊號已被證明有或沒有額外作用。",
            inseparable: "可比較的資料不足，無法清楚區分兩組。",
            opposite: "這一格的直接比較沒有顯示出現訊號組的比例較低。",
            unresolved: "這一格的資料還沒有給出明確方向。",
            not_applicable: "此訊號在研究中不適用。",
        };
        return explanations[verdict] || "此格沒有保存判讀。";
    }

    function guidedSelect(labelText, options, value, onChange) {
        const labelNode = make("label", "filter-label", labelText);
        const select = document.createElement("select");
        select.setAttribute("aria-label", labelText);
        options.forEach(([optionValue, optionLabel]) => {
            const option = document.createElement("option");
            option.value = optionValue;
            option.textContent = optionLabel;
            option.selected = optionValue === value;
            select.append(option);
        });
        select.addEventListener("change", () => onChange(select.value));
        labelNode.append(select);
        return labelNode;
    }

    function groupDescription(group) {
        return group === "LEAD_B1"
            ? "已大幅上漲、且起點當天漲至少 9.5% 的股票"
            : "已大幅上漲的股票";
    }

    function flagDescription(flag) {
        const descriptions = {
            Y3: "收盤跌破起點時已確認的固定支撐價",
            X5_MA20: "收盤曾低於 20 日均線",
            X5_MA60: "收盤曾低於 60 日均線",
            X6_10: "收盤比起點價低至少 10%",
            X6_15: "收盤比起點價低至少 15%",
            X7: "收盤低於布林下軌",
            X8: "新確認高點低於前一個已確認高點",
        };
        return descriptions[flag] || human("flag", flag);
    }

    function mainFindingRow() {
        return rows.find(
            (row) =>
                baseFull(row) &&
                key(row, "group") === "CORE" &&
                Number(val(row, "target_multiple")) === 2 &&
                String(val(row, "horizon")).replace(/^H/, "") === "252" &&
                String(val(row, "landmark")).replace(/^L/, "") === "20" &&
                key(row, "flag") === "X5_MA60",
        );
    }

    function renderMainFinding() {
        const row = mainFindingRow();
        if (!row) {
            $("#main-triggered-rate").textContent = "—";
            $("#main-not-triggered-rate").textContent = "—";
            $("#main-triggered-count").textContent = "沒有可用的已知事件數";
            $("#main-not-triggered-count").textContent = "沒有可用的已知事件數";
            $("#main-difference").textContent =
                "此比較目前沒有可用的保存結果。";
            $("#main-cost-rate").textContent = "—";
            return;
        }
        $("#main-triggered-rate").textContent = fmtPct(
            val(row, "triggered_rate"),
        );
        $("#main-not-triggered-rate").textContent = fmtPct(
            val(row, "not_triggered_rate"),
        );
        $("#main-triggered-count").textContent =
            `結果已知的 ${fmtInt(val(row, "triggered_known_n"))} 筆觀察`;
        $("#main-not-triggered-count").textContent =
            `結果已知的 ${fmtInt(val(row, "not_triggered_known_n"))} 筆觀察`;
        const difference = val(row, "pooled_difference");
        $("#main-difference").textContent =
            typeof difference === "number"
                ? `直接比較時，曾低於均線組低 ${(Math.abs(difference) * 100).toFixed(2)} 個百分點。`
                : "兩組比例差目前沒有可用的保存數值。";
        $("#main-cost-rate").textContent = fmtPct(
            val(row, "false_abandonment_rate"),
        );
    }

    function renderGuidedExplorer() {
        const controls = $("#guided-controls");
        controls.replaceChildren();
        controls.append(
            guidedSelect(
                "比較哪一組",
                [
                    ["CORE", "已大幅上漲的股票"],
                    ["LEAD_B1", "已大幅上漲的股票，再加上當天漲至少9.5%"],
                ],
                guidedState.group,
                (value) => {
                    guidedState.group = value;
                    updateGuidedComparison();
                },
            ),
            guidedSelect(
                "轉弱訊號",
                [
                    ["Y3", human("flag", "Y3")],
                    ["X5_MA20", human("flag", "X5_MA20")],
                    ["X5_MA60", human("flag", "X5_MA60")],
                    ["X6_10", human("flag", "X6_10")],
                    ["X6_15", human("flag", "X6_15")],
                    ["X7", human("flag", "X7")],
                    ["X8", human("flag", "X8")],
                ],
                guidedState.flag,
                (value) => {
                    guidedState.flag = value;
                    updateGuidedComparison();
                },
            ),
            guidedSelect(
                "達標期限",
                [
                    ["126", "半年（126 個交易日）"],
                    ["252", "一年（252 個交易日）"],
                ],
                guidedState.horizon,
                (value) => {
                    guidedState.horizon = value;
                    updateGuidedComparison();
                },
            ),
        );
        $("#guided-evidence-button").addEventListener("click", () => {
            if (guidedState.row) pickRow(guidedState.row);
        });
        updateGuidedComparison();
    }

    function updateGuidedComparison() {
        const row = rows.find(
            (candidate) =>
                baseFull(candidate) &&
                key(candidate, "group") === guidedState.group &&
                Number(val(candidate, "target_multiple")) === 2 &&
                String(val(candidate, "horizon")).replace(/^H/, "") ===
                    guidedState.horizon &&
                String(val(candidate, "landmark")).replace(/^L/, "") === "20" &&
                key(candidate, "flag") === guidedState.flag,
        );
        guidedState.row = row || null;
        const host = $("#guided-comparison");
        host.replaceChildren();
        const evidenceButton = $("#guided-evidence-button");
        evidenceButton.disabled = !row;
        if (!row) {
            host.append(
                make(
                    "p",
                    "load-error",
                    "這個組合沒有可用的保存結果；沒有可比較的比例。",
                ),
            );
            $("#false-abandonment-card").replaceChildren();
            return;
        }

        const triggered = val(row, "triggered_rate");
        const notTriggered = val(row, "not_triggered_rate");
        const difference = val(row, "pooled_difference");
        const standardizedDifference = val(row, "standardized_difference");
        const comparison = make("div", "rate-comparison");
        comparison.append(
            make(
                "p",
                "comparison-heading",
                `${groupDescription(guidedState.group)} · ${guidedState.horizon === "126" ? "半年" : "一年"}內達到起點價 2 倍 · 前 20 日${flagDescription(guidedState.flag)}`,
            ),
            make(
                "p",
                "signal-explanation",
                flagExplanations[guidedState.flag] ||
                    "此訊號的定義請見完整研究細節。",
            ),
        );
        comparison.append(
            make("p", "scale-caption", "兩組共用 0% 到 100% 刻度"),
        );
        const bars = make("div", "rate-bars");
        [
            [
                "前20個交易日內曾出現訊號",
                triggered,
                "triggered",
                "triggered_known_n",
            ],
            [
                "前20個交易日內未出現訊號",
                notTriggered,
                "not-triggered",
                "not_triggered_known_n",
            ],
        ].forEach(([labelText, rate, stateClass, knownField]) => {
            const item = make("div", `rate-item ${stateClass}`);
            const heading = make("div", "rate-label");
            heading.append(
                make("span", "", labelText),
                make("strong", "", fmtPct(rate)),
            );
            const track = make("div", "rate-track");
            track.setAttribute("role", "img");
            track.setAttribute(
                "aria-label",
                typeof rate === "number"
                    ? `${labelText}翻倍比例 ${fmtPct(rate)}`
                    : `${labelText}沒有可用的翻倍比例數值`,
            );
            const fill = make("span", "rate-fill");
            if (typeof rate === "number") {
                fill.style.width = `${Math.max(0, Math.min(100, rate * 100))}%`;
                track.append(fill);
            } else {
                track.className = "rate-track is-missing";
                track.textContent = "沒有可用比例，不能視為 0%";
            }
            const axis = make("div", "rate-axis");
            axis.append(make("span", "", "0%"), make("span", "", "100%"));
            item.append(
                heading,
                track,
                axis,
                make(
                    "p",
                    "muted",
                    `比例依結果已知的 ${fmtInt(val(row, knownField))} 筆事件計算。`,
                ),
            );
            bars.append(item);
        });
        comparison.append(bars);
        comparison.append(
            make("p", "muted", "尚無法判定結果者另列，未計入上述比例。"),
        );
        const delta = make("p", "difference-callout");
        if (typeof difference === "number") {
            const direction =
                difference < 0 ? "較低" : difference > 0 ? "較高" : "相同";
            delta.textContent = `直接比較時，前20個交易日內曾出現訊號組的翻倍比例比未出現組${direction} ${(Math.abs(difference) * 100).toFixed(2)} 個百分點。`;
        } else {
            delta.textContent = "沒有可用的兩組翻倍比例差值。";
        }
        comparison.append(
            delta,
            make(
                "p",
                "standardized-readout",
                `把第20日漲跌幅相近的觀察分組比較後，兩組差異為 ${typeof standardizedDifference === "number" ? `${(standardizedDifference * 100).toFixed(2)} 個百分點` : "無法判定"}。負值表示出現訊號的一組較低；差異是否夠明確，還要看下方判讀。`,
            ),
            make("p", "saved-verdict", verdictExplanation(row)),
        );
        host.append(comparison);

        const costCard = $("#false-abandonment-card");
        costCard.replaceChildren();
        const costDetails = make("details", "cost-details");
        costDetails.append(
            make("summary", "", "查看計算方式、計數與資料不明時的範圍"),
            make(
                "p",
                "",
                "計算方式：第一次翻倍前已出現訊號的事件數，除以訊號狀態已知的最終翻倍事件數。訊號不明的事件另列，不當作未出現。",
            ),
            make(
                "p",
                "",
                `第一次翻倍前出現訊號：${fmtInt(val(row, "hit_triggered_n"))}；訊號已知但未出現：${fmtInt(val(row, "hit_not_triggered_n"))}；訊號狀態不明：${fmtInt(val(row, "hit_flag_unknown_n"))}。`,
            ),
            make(
                "p",
                "",
                `若未知訊號都當作未出現，下界為 ${fmtPct(val(row, "false_abandonment_lower"))}；若未知訊號都當作曾出現，上界為 ${fmtPct(val(row, "false_abandonment_upper"))}。這是邏輯範圍，不是信賴區間。`,
            ),
        );
        costCard.append(
            make(
                "h3",
                "",
                "最後真的翻倍的事件中，也有多少之前出現過這個訊號？",
            ),
            make("p", "cost-rate", fmtPct(val(row, "false_abandonment_rate"))),
            make(
                "p",
                "",
                `這裡只看資料觀察完整、而且在期限內確實翻倍的事件。訊號可以在起點後第 20 個交易日之後才出現，只要早於第一次翻倍。`,
            ),
            make(
                "p",
                "muted",
                "上方比較的是前 20 個交易日內的訊號，並排除到第 20 日（含當日）已翻倍的觀察。這張卡看的時間更長、對象也不同；不能把這個比例當成第 20 日賣出後會錯過翻倍的機率。",
            ),
            costDetails,
        );
    }

    function baseFull(row) {
        return splitAll(row) && eraAll(row) && full(row);
    }
    function isPrimary(row) {
        return (
            baseFull(row) &&
            yes(val(row, "primary", "is_primary", "primary_cell"))
        );
    }
    function label(row, field, kind) {
        return human(kind, val(row, field));
    }
    function pickRow(row) {
        selected = row;
        renderDetail();
        const disclosure = $("#evidence-disclosure");
        disclosure.open = true;
        const title = $("#detail-title");
        title.focus({ preventScroll: true });
        if (window.parent !== window) {
            window.parent.postMessage(
                {
                    type: "rk:reveal",
                    target: "detail-title",
                    height: document.documentElement.scrollHeight,
                },
                "*",
            );
        } else {
            title.scrollIntoView({ block: "start", behavior: "auto" });
        }
    }

    function renderPrimary() {
        const mainRows = rows
            .filter(isPrimary)
            .sort(
                (a, b) =>
                    ["group", "horizon", "flag"]
                        .map((f) => key(a, f).localeCompare(key(b, f)))
                        .find((x) => x !== 0) || 0,
            );
        table(
            $("#primary-table"),
            [
                { label: "組別", render: (r) => label(r, "group", "group") },
                {
                    label: "期限",
                    render: (r) => horizonLabel(val(r, "horizon")),
                },
                {
                    label: "觀察點",
                    render: (r) => landmarkLabel(val(r, "landmark")),
                },
                { label: "訊號", render: (r) => label(r, "flag", "flag") },
                {
                    label: "已觸發：達標率／已知數",
                    render: (r) =>
                        `${fmtPct(val(r, "triggered_rate", "rate_triggered", "flagged_rate"))}／${fmtInt(val(r, "triggered_known_n", "known_triggered_n", "triggered_n"))}`,
                },
                {
                    label: "未觸發：達標率／已知數",
                    render: (r) =>
                        `${fmtPct(val(r, "not_triggered_rate", "rate_not_triggered", "unflagged_rate"))}／${fmtInt(val(r, "not_triggered_known_n", "known_not_triggered_n", "not_triggered_n"))}`,
                },
                {
                    label: "合併差",
                    render: (r) =>
                        fmtPp(
                            val(
                                r,
                                "pooled_difference",
                                "difference_pooled",
                                "pooled_diff",
                            ),
                        ),
                    className: "numeric",
                },
                {
                    label: "標準化差",
                    render: (r) =>
                        fmtPp(
                            val(
                                r,
                                "standardized_difference",
                                "difference_standardized",
                                "standardized_diff",
                            ),
                        ),
                    className: "numeric",
                },
                {
                    label: "最終達標前曾有訊號比例 T/(T+F)",
                    render: (r) =>
                        fmtPct(
                            val(
                                r,
                                "false_abandonment_rate",
                                "false_alarm_cost",
                            ),
                        ),
                    className: "numeric",
                },
                {
                    label: "未知邏輯下／上界（非信賴區間）",
                    render: (r) =>
                        `${fmtPct(val(r, "false_abandonment_lower"))}／${fmtPct(val(r, "false_abandonment_upper"))}`,
                },
                {
                    label: "保存判讀",
                    render: (r) => label(r, "verdict", "verdict"),
                },
            ],
            mainRows,
            pickRow,
        );
        if (mainRows.length) {
            selected = mainRows[0];
            renderDetail();
        }
    }

    function renderGrid() {
        const controls = $("#grid-controls");
        controls.replaceChildren();
        const fields = [
            [
                "group",
                "組別",
                ["CORE", "LEAD_B1", "C-base-daily", "C-52w-daily"],
                "group",
            ],
            ["target_multiple", "目標倍數", ["2", "3", "5", "10"], "target"],
            ["horizon", "期限", ["126", "252", "504"], "horizon"],
            ["landmark", "觀察點", ["5", "10", "20", "40"], "landmark"],
            [
                "flag",
                "轉弱訊號",
                [
                    "Y1",
                    "Y2",
                    "Y3",
                    "X5_MA20",
                    "X5_MA60",
                    "X6_10",
                    "X6_15",
                    "X7",
                    "X8",
                ],
                "flag",
            ],
        ];
        const selects = {};
        fields.forEach(([field, title, options, kind]) => {
            const labelNode = make("label", "filter-label", title);
            const select = document.createElement("select");
            select.setAttribute("aria-label", title);
            const all = document.createElement("option");
            all.value = "*";
            all.textContent = "全部";
            all.selected = true;
            select.append(all);
            options.forEach((v) => {
                const op = document.createElement("option");
                op.value = v;
                op.textContent = human(kind, v);
                select.append(op);
            });
            select.addEventListener("change", renderGridTable);
            labelNode.append(select);
            controls.append(labelNode);
            selects[field] = select;
        });
        function selectedValue(field) {
            return selects[field].value;
        }
        function normalize(value, type) {
            if (type === "horizon") return String(value).replace(/^H/, "");
            if (type === "landmark") return String(value).replace(/^L/, "");
            return String(value);
        }
        function renderGridTable() {
            let candidates = rows.filter((r) => baseFull(r));
            const matching = (r, f) =>
                selectedValue(f) === "*" ||
                normalize(key(r, f), f) === normalize(selectedValue(f), f);
            candidates = candidates.filter((r) =>
                fields.every(([field]) => matching(r, field)),
            );
            table(
                $("#grid-table"),
                [
                    {
                        label: "組別",
                        render: (r) => label(r, "group", "group"),
                    },
                    {
                        label: "倍數",
                        render: (r) => `${text(val(r, "target_multiple"))} 倍`,
                    },
                    {
                        label: "期限",
                        render: (r) => horizonLabel(val(r, "horizon")),
                    },
                    {
                        label: "觀察點",
                        render: (r) => landmarkLabel(val(r, "landmark")),
                    },
                    { label: "訊號", render: (r) => label(r, "flag", "flag") },
                    {
                        label: "已觸發達標率",
                        render: (r) => fmtPct(val(r, "triggered_rate")),
                        className: "numeric",
                    },
                    {
                        label: "未觸發達標率",
                        render: (r) =>
                            fmtPct(
                                val(
                                    r,
                                    "not_triggered_rate",
                                    "rate_not_triggered",
                                    "unflagged_rate",
                                ),
                            ),
                        className: "numeric",
                    },
                    {
                        label: "合併差",
                        render: (r) =>
                            fmtPp(
                                val(
                                    r,
                                    "pooled_difference",
                                    "difference_pooled",
                                    "pooled_diff",
                                ),
                            ),
                        className: "numeric",
                    },
                    {
                        label: "最終達標前曾有訊號比例",
                        render: (r) => fmtPct(val(r, "false_abandonment_rate")),
                        className: "numeric",
                    },
                    {
                        label: "保存判讀",
                        render: (r) => label(r, "verdict", "verdict"),
                    },
                ],
                candidates,
                pickRow,
            );
        }
        renderGridTable();
    }

    function renderDetail() {
        if (!selected) return;
        const title = `${groupDescription(key(selected, "group"))} · 起點後第 ${text(val(selected, "horizon"))} 個交易日（${horizonLabel(val(selected, "horizon"))}）達到 ${text(val(selected, "target_multiple"))} 倍 · 第 1–${text(val(selected, "landmark"))} 日${flagDescription(key(selected, "flag"))}`;
        $("#detail-title").textContent = title;
        const host = $("#detail-content");
        host.replaceChildren();
        const summary = make("div", "detail-block");
        summary.append(make("h3", "", "所選完整合併格：點估計、區間與支持度"));
        const base = {
            group: key(selected, "group"),
            target: key(selected, "target_multiple"),
            horizon: key(selected, "horizon"),
            landmark: key(selected, "landmark"),
            flag: key(selected, "flag"),
        };
        const intervals = chunkRecords(window.REPORT_TABLES.intervals)
            .filter(
                (r) =>
                    key(r, "group") === base.group &&
                    key(r, "target_multiple") === base.target &&
                    key(r, "horizon") === base.horizon &&
                    key(r, "landmark") === base.landmark &&
                    key(r, "flag") === base.flag,
            )
            .filter((r) =>
                [
                    "pooled_difference",
                    "hit_rate_ratio",
                    "standardized_difference",
                ].includes(key(r, "metric")),
            );
        const detailStats = [
            [
                "已觸發／未觸發達標率",
                `${fmtPct(val(selected, "triggered_hit_rate"))}／${fmtPct(val(selected, "untriggered_hit_rate"))}`,
            ],
            ["達標率比", fmtRatio(val(selected, "hit_rate_ratio"))],
            [
                "合併差／標準化差",
                `${fmtPp(val(selected, "pooled_difference"))}／${fmtPp(val(selected, "standardized_difference"))}`,
            ],
            [
                "已觸發冷卻後已知數／股票數",
                `${fmtInt(val(selected, "triggered_cooled_known_n"))}／${fmtInt(val(selected, "triggered_cooled_stock_n"))}`,
            ],
            [
                "未觸發冷卻後已知數／股票數",
                `${fmtInt(val(selected, "all_false_cooled_known_n"))}／${fmtInt(val(selected, "all_false_cooled_stock_n"))}`,
            ],
            [
                "已觸發／未觸發結果不明數",
                `${fmtInt(val(selected, "triggered_unknown_n"))}／${fmtInt(val(selected, "all_false_unknown_n"))}`,
            ],
            [
                "已觸發／未觸發期限未走完數",
                `${fmtInt(val(selected, "triggered_censored_n"))}／${fmtInt(val(selected, "all_false_censored_n"))}`,
            ],
            ["訊號狀態未知事件數", fmtInt(val(selected, "unknown_event_n"))],
            [
                "未知訊號的結果不明／期限未走完數",
                `${fmtInt(val(selected, "unknown_unknown_n"))}／${fmtInt(val(selected, "unknown_censored_n"))}`,
            ],
            [
                "最終達標前曾有訊號比例及未知邏輯界限",
                `${fmtPct(val(selected, "false_abandonment_rate"))}（${fmtPct(val(selected, "false_abandonment_lower"))}–${fmtPct(val(selected, "false_abandonment_upper"))}）`,
            ],
            [
                "首次達標前訊號 T／F／U",
                `${fmtInt(val(selected, "hit_triggered_n"))}／${fmtInt(val(selected, "hit_not_triggered_n"))}／${fmtInt(val(selected, "hit_flag_unknown_n"))}`,
            ],
        ];
        const statsList = make("dl", "stats-list");
        detailStats.forEach(([k, v]) => {
            statsList.append(make("dt", "", k), make("dd", "", v));
        });
        summary.append(statsList);
        tableIn(summary, intervals, [
            {
                label: "重抽方法",
                render: (r) => human("method", val(r, "method", "bootstrap")),
            },
            {
                label: "估計量",
                render: (r) => human("measure", val(r, "metric")),
            },
            {
                label: "下界",
                render: (r) =>
                    key(r, "metric") === "hit_rate_ratio"
                        ? fmtRatio(val(r, "lower"))
                        : fmtPp(val(r, "lower")),
            },
            {
                label: "上界",
                render: (r) =>
                    key(r, "metric") === "hit_rate_ratio"
                        ? fmtRatio(val(r, "upper"))
                        : fmtPp(val(r, "upper")),
            },
            {
                label: "可定義／總重抽次數",
                render: (r) =>
                    `${fmtInt(val(r, "defined_replicates"))}／${fmtInt(val(r, "replicates"))}`,
            },
        ]);
        host.append(summary);

        const slices = rows.filter(
            (r) =>
                key(r, "group") === base.group &&
                key(r, "target_multiple") === base.target &&
                key(r, "horizon") === base.horizon &&
                key(r, "landmark") === base.landmark &&
                key(r, "flag") === base.flag &&
                (key(r, "row_kind") !== "full" ||
                    key(r, "era") !== "all" ||
                    key(r, "split") !== "all"),
        );
        const sliceBlock = make("div", "detail-block");
        sliceBlock.append(
            make("h3", "", "不同年代、股票分半與移除達標事件最多的年份或股票"),
        );
        sliceBlock.append(
            make(
                "p",
                "muted",
                "切片直接顯示保存結果。移除的年份或股票依各格分別決定；這些列沒有信賴區間或保存判讀。",
            ),
        );
        tableIn(sliceBlock, slices, [
            {
                label: "切片",
                render: (r) =>
                    `${human("era", val(r, "era"))} · ${human("split", val(r, "split"))} · ${human("row", val(r, "row_kind"))}`,
            },
            {
                label: "移除標的",
                keys: [
                    "dropped",
                    "removed_label",
                    "dropped_label",
                    "removed_value",
                    "dropped_value",
                ],
            },
            {
                label: "已觸發率",
                render: (r) =>
                    fmtPct(
                        val(
                            r,
                            "triggered_rate",
                            "rate_triggered",
                            "flagged_rate",
                        ),
                    ),
            },
            {
                label: "未觸發率",
                render: (r) =>
                    fmtPct(
                        val(
                            r,
                            "not_triggered_rate",
                            "rate_not_triggered",
                            "unflagged_rate",
                        ),
                    ),
            },
            {
                label: "已觸發／未觸發已知數",
                render: (r) =>
                    `${fmtInt(val(r, "triggered_known_n"))}／${fmtInt(val(r, "all_false_known_n"))}`,
            },
            {
                label: "合併差",
                render: (r) =>
                    fmtPp(
                        val(
                            r,
                            "pooled_difference",
                            "difference_pooled",
                            "pooled_diff",
                        ),
                    ),
            },
            {
                label: "標準化差",
                render: (r) => fmtPp(val(r, "standardized_difference")),
            },
            {
                label: "結果不明／期限未走完（各狀態加總）",
                render: (r) =>
                    `${fmtInt(sumStored(r, ["triggered_unknown_n", "all_false_unknown_n", "unknown_unknown_n", "not_applicable_unknown_n"]))}／${fmtInt(sumStored(r, ["triggered_censored_n", "all_false_censored_n", "unknown_censored_n", "not_applicable_censored_n"]))}`,
            },
        ]);
        host.append(sliceBlock);

        const strataRows = chunkRecords(window.REPORT_TABLES.strata).filter(
            (r) =>
                key(r, "group") === base.group &&
                key(r, "target_multiple") === base.target &&
                key(r, "horizon") === base.horizon &&
                key(r, "landmark") === base.landmark &&
                key(r, "flag") === base.flag,
        );
        const strata = make("div", "detail-block");
        strata.append(make("h3", "", "依起點後漲幅分層"));
        strata.append(
            make(
                "p",
                "muted",
                "展示保存的每日／冷卻後計數與狀態；不從事件原始列重算比率或筆數。",
            ),
        );
        tableIn(strata, strataRows, [
            {
                label: "資料口徑",
                render: (r) => human("basis", val(r, "basis")),
            },
            {
                label: "訊號狀態",
                render: (r) => human("state", val(r, "flag_state")),
            },
            {
                label: "漲幅分層",
                render: (r) => human("rise", val(r, "rise_bin", "rise")),
            },
            { label: "事件數", render: (r) => fmtInt(val(r, "event_n")) },
            {
                label: "已知／結果不明／期限未走完",
                render: (r) =>
                    `${fmtInt(val(r, "known_n"))}／${fmtInt(val(r, "unknown_n"))}／${fmtInt(val(r, "censored_n"))}`,
            },
            {
                label: "達標／未達標且收低／未達標但未收低",
                render: (r) =>
                    `${fmtInt(val(r, "hit_n"))}／${fmtInt(val(r, "loss_n"))}／${fmtInt(val(r, "flat_win_n"))}`,
            },
        ]);
        host.append(strata);
    }

    function tableIn(host, data, columns) {
        const wrap = make("div", "rk-table-wrap");
        const t = document.createElement("table");
        t.className = "rk-table";
        t.createTHead();
        t.createTBody();
        wrap.append(t);
        host.append(wrap);
        table(t, columns, data);
    }

    function linkMeta() {
        const meta = window.REPORT_META || {};
        if (meta.sourceUrl) $("#source-link").href = meta.sourceUrl;
        if (meta.reportUrl) $("#report-link").href = meta.reportUrl;
    }
    async function start() {
        $("#shared-data-link").addEventListener("click", (event) => {
            if (window.parent === window) return;
            event.preventDefault();
            window.parent.postMessage(
                { type: "rk:navigate", href: "#data" },
                "*",
            );
        });
        try {
            if (!window.ReportKit || !window.REPORT_READY)
                throw new Error("報告元件未初始化");
            await window.REPORT_READY;
            if (
                !window.REPORT_TABLES ||
                !window.REPORT_TABLES.summary ||
                !window.REPORT_TABLES.intervals ||
                !window.REPORT_TABLES.strata
            )
                throw new Error("摘要資料不完整");
            rows = summaryRows();
            if (!rows.length) throw new Error("摘要資料為空");
            linkMeta();
            renderMainFinding();
            renderGuidedExplorer();
            renderPrimary();
            renderGrid();
        } catch (error) {
            $("#load-error").hidden = false;
            $("#primary-table tbody").replaceChildren();
            const tr = document.createElement("tr");
            const td = make(
                "td",
                "",
                `載入失敗：${error && error.message ? error.message : "資料不可用"}`,
            );
            tr.append(td);
            $("#primary-table tbody").append(tr);
        }
    }
    document.addEventListener("DOMContentLoaded", start, { once: true });
})();
