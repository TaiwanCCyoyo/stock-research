(function () {
    "use strict";

    const byId = (id) => document.getElementById(id);
    const array = (value) => (Array.isArray(value) ? value : []);
    const present = (value) =>
        value !== null && value !== undefined && value !== "";
    const numeric = (value) =>
        typeof value === "number" && Number.isFinite(value);
    const intFormat = new Intl.NumberFormat("zh-TW", {
        maximumFractionDigits: 0,
    });
    const numberFormat = new Intl.NumberFormat("zh-TW", {
        maximumFractionDigits: 6,
    });
    const headlineFormat = new Intl.NumberFormat("zh-TW", {
        maximumFractionDigits: 2,
    });
    const statuses = {
        complete: "本題完成",
        partial: "部分完成",
        pending: "尚未完成",
    };

    const familyNames = {
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
    const familyLabel = (code) =>
        familyNames[code] ? `${familyNames[code]}（${code}）` : code;

    // Reader view: which columns, with plain-language headers, each table shows.
    // Rows, values and downloads are untouched; the full column set stays in the files.
    const horizonText = (value) =>
        value === 126
            ? "126 日（約半年）"
            : value === 252
              ? "252 日（約一年）"
              : present(value)
                ? `${value} 日`
                : null;
    const controlNames = {
        pattern: "有型態的日子",
        "C-base-no-pattern": "同條件、沒有型態的日子",
        "C-base-all": "同條件的所有日子（含有型態者）",
        "C-base-daily": "所有合格日",
        "C-base-random": "隨機日期",
        "C-52w": "股價在 52 週高點附近的日子",
        "C-dip": "股價跌深的日子",
        "C-trend": "股價走在趨勢上的日子",
    };
    const controlName = (code) => controlNames[code] || code;
    const populationNames = {
        hit: "後來翻倍",
        nonhit: "最後沒翻倍",
        unknown: "無法判斷",
    };
    const flagNames = {
        Y1: "跌破支撐價（Y1）",
        Y2: "跌破較低價位（Y2）",
        Y3: "跌破已確認前低（Y3）",
        X5_MA20: "收盤跌破 20 日均線",
        X5_MA60: "收盤跌破 60 日均線",
        X6_10: "從起點跌 10%",
        X6_15: "從起點跌 15%",
        X7: "跌破布林通道下緣",
        X8: "高點降低",
    };
    const stateNames = {
        triggered: "有出現",
        all_false: "沒出現",
        unknown: "無法判斷",
    };
    const pathNames = {
        direct_failure: "先跌 10% 才漲 10%（或一直沒漲 10%）",
        rise_then_fall: "沒有先跌 10%，且曾漲 20% 以上",
        sideways: "沒有先跌 10%，最高未達 +20%、最低未跌破 −15%",
        slow_decline: "先漲過 10%，之後跌破 −15%（最高未達 +20%）",
        unknown: "無法判斷",
    };
    const binNames = {
        pooled: "全部",
        lt1: "低於起點",
        b1_1p10: "高於起點 0–10%",
        b1p10_1p25: "高於起點 10–25%",
        ge1p25: "高於起點 25% 以上",
    };
    const mapped = (names, key) => (row) =>
        present(row[key]) ? names[row[key]] || row[key] : null;
    const familyOf = (code) =>
        present(code) ? familyLabel(String(code).split(":")[0]) : null;
    // "H1:original", "H1:original:C-52w", "H1:candidate:pattern-scan.v1:H1:<atoms>", "C-base-daily"
    const splitGroup = (group) => {
        const text = String(group ?? "");
        const parts = text.split(":");
        if (!familyNames[parts[0]])
            return { code: null, what: controlName(text) };
        if (parts[1] === "candidate") {
            const tail = parts.slice(4);
            const control = controlNames[tail[tail.length - 1]]
                ? tail.pop()
                : null;
            const atoms = tail.join(":").split("&").join(" & ");
            return {
                code: parts[0],
                what: `條件組合 ${atoms}${control ? `，對照：${controlName(control)}` : ""}`,
            };
        }
        const rest = parts.slice(2).join(":");
        return {
            code: parts[0],
            what: rest ? `型態，對照：${controlName(rest)}` : "型態本身",
        };
    };
    const groupLabel = (key) => (row) => {
        const { code, what } = splitGroup(row[key]);
        return code ? `${familyLabel(code)}｜${what}` : what;
    };
    const candidateParts = (id) => {
        const parts = String(id ?? "").split(":");
        return {
            code: parts[2],
            atoms: parts.slice(3).join(":").split("&").join(" & "),
        };
    };
    const col = (label, kind, key, extra) => ({ label, kind, key, ...extra });
    const familyCol = (key) =>
        col("型態", "text", key, { get: (row) => familyOf(row[key]) });
    const horizonCol = col("追蹤期限", "text", "horizon", {
        get: (row) => horizonText(row.horizon),
    });
    const flagCol = col("轉弱訊號", "text", "flag_id", {
        get: mapped(flagNames, "flag_id"),
    });
    const outcomeCol = col("事件結果", "text", "population", {
        get: mapped(populationNames, "population"),
    });
    const fullDownload = "完整欄位下載";
    const views = {
        "Q1:0": {
            title: "十二種型態的翻倍比例（另一半股票）",
            downloadLabel: fullDownload,
            columns: [
                familyCol("target"),
                horizonCol,
                col("比較對象", "text", "control_id", {
                    get: (row) => controlName(row.control_id),
                }),
                col("事件數", "integer", "event_n"),
                col("可判定樣本數", "integer", "known_n"),
                col("翻倍比例", "percent", "hit_rate"),
                col("期滿仍虧損比例", "percent", "loss_rate"),
                col("股票檔數", "integer", "distinct_stock_n"),
            ],
        },
        "Q2:0": {
            title: "固定的十組條件：有型態比沒有型態高多少（百分點）",
            downloadLabel: fullDownload,
            columns: [
                familyCol("target"),
                col("篩選條件（研究代號）", "text", "atoms"),
                horizonCol,
                col(
                    "比沒有型態高（百分點）",
                    "percentage_points",
                    "pattern_minus_no_pattern_pp",
                ),
                col(
                    "比所有日子高（百分點）",
                    "percentage_points",
                    "pattern_minus_all_pp",
                ),
                col("有型態樣本數", "integer", "pattern_known_n"),
                col("沒型態樣本數", "integer", "no_pattern_known_n"),
                col("期滿仍虧損比例", "percent", "loss_rate"),
            ],
        },
        "Q3:0": {
            title: "附錄：每組條件下，有型態與各種對照的翻倍比例",
            downloadLabel: fullDownload,
            columns: [
                col("型態", "text", "candidate_id", {
                    get: (row) =>
                        familyLabel(candidateParts(row.candidate_id).code),
                }),
                col("篩選條件（研究代號）", "text", "candidate_id", {
                    get: (row) => candidateParts(row.candidate_id).atoms,
                }),
                col("比較對象", "text", "control_id", {
                    get: (row) => controlName(row.control_id),
                }),
                horizonCol,
                col("事件數", "integer", "event_n"),
                col("可判定樣本數", "integer", "known_n"),
                col("翻倍比例", "percent", "hit_rate"),
                col("期滿仍虧損比例", "percent", "loss_rate"),
            ],
        },
        "Q4:0": {
            title: "已翻倍段落中，出現過型態的比例，對照同數量隨機日期",
            downloadLabel: fullDownload,
            columns: [
                col("型態或條件組合", "text", "group", {
                    get: groupLabel("group"),
                }),
                col("翻倍段落數", "integer", "episode_n"),
                col("型態出現比例", "percent", "pattern_coverage_rate"),
                col("隨機日期出現比例", "percent", "random_coverage_rate"),
                col("差距（百分點）", "percentage_points", "coverage_delta_pp"),
                col("無法判斷的段數", "integer", "pattern_unknown_n"),
            ],
        },
        "Q4:1": {
            title: "附錄：出現比例的上下限與其他對照",
            downloadLabel: fullDownload,
            columns: [
                col("型態或對照", "text", "group_id", {
                    get: groupLabel("group_id"),
                }),
                col("翻倍段落數", "integer", "episode_n"),
                col("有出現", "integer", "matched_n"),
                col("沒出現", "integer", "unmatched_n"),
                col("無法判斷", "integer", "unknown_n"),
                col("出現比例", "percent", "coverage_rate"),
                col(
                    "下限（無法判斷都算沒出現）",
                    "percent",
                    "coverage_lower_bound",
                ),
                col(
                    "上限（無法判斷都算有出現）",
                    "percent",
                    "coverage_upper_bound",
                ),
            ],
        },
        "Q5:0": {
            title: "附錄：途中走勢分布",
            downloadLabel: fullDownload,
            columns: [
                familyCol("target_pattern_id"),
                horizonCol,
                outcomeCol,
                col("途中走勢", "text", "path_category", {
                    get: mapped(pathNames, "path_category"),
                }),
                col("事件數", "integer", "path_n"),
                col("股票檔數", "integer", "distinct_stock_n"),
            ],
        },
        "Q5:1": {
            title: "附錄：追蹤期間的報酬（中位數）",
            downloadLabel: fullDownload,
            columns: [
                familyCol("target_pattern_id"),
                horizonCol,
                outcomeCol,
                col("事件數", "integer", "sample_n"),
                col("該型態報酬中位數", "percent", "own_return_median"),
                col(
                    "同期 0050 報酬中位數",
                    "percent",
                    "benchmark_return_median",
                ),
                col("同行報酬中位數", "percent", "peer_return_median"),
            ],
        },
        "Q5:2": {
            title: "附錄：最早出現的轉弱訊號",
            downloadLabel: fullDownload,
            columns: [
                familyCol("target_pattern_id"),
                horizonCol,
                outcomeCol,
                flagCol,
                col("訊號狀態", "text", "first_state", {
                    get: mapped(stateNames, "first_state"),
                }),
                col("事件數", "integer", "first_n"),
                col(
                    "最早出現日（第幾個交易日，中位數）",
                    "number",
                    "first_day_median",
                ),
            ],
        },
        "Q6:0": {
            title: "附錄：轉弱訊號出現的比例",
            downloadLabel: fullDownload,
            columns: [
                familyCol("target_pattern_id"),
                horizonCol,
                flagCol,
                col("沒翻倍者的樣本數", "integer", "nonhit_known_n"),
                col("沒翻倍者出現訊號的比例", "percent", "nonhit_known_rate"),
                col("翻倍者的樣本數", "integer", "hit_cost_known_n"),
                col(
                    "翻倍者在翻倍前出現訊號的比例",
                    "percent",
                    "hit_cost_known_rate",
                ),
            ],
        },
        "Q6:1": {
            title: "附錄：型態出現後第 10 個交易日仍未翻倍者的後續",
            downloadLabel: fullDownload,
            columns: [
                familyCol("target_pattern_id"),
                horizonCol,
                flagCol,
                col("觀察日", "text", "landmark", {
                    get: (row) =>
                        numeric(row.landmark) ? `第 ${row.landmark} 日` : null,
                }),
                col("訊號", "text", "flag_state", {
                    get: mapped(stateNames, "flag_state"),
                }),
                col("當時價位（對起點）", "text", "return_bin", {
                    get: mapped(binNames, "return_bin"),
                }),
                col("樣本數", "integer", "known_n"),
                col("最後翻倍比例", "percent", "hit_rate"),
            ],
        },
        "Q6:2": {
            title: "附錄：訊號的取捨",
            downloadLabel: fullDownload,
            columns: [
                familyCol("target_pattern_id"),
                horizonCol,
                flagCol,
                col("沒翻倍者出現訊號的比例", "percent", "nonhit_trigger_rate"),
                col(
                    "翻倍者在翻倍前出現訊號的比例",
                    "percent",
                    "hit_before_target_cost",
                ),
                col("沒翻倍者樣本數", "integer", "nonhit_population_n"),
                col("翻倍者樣本數", "integer", "hit_population_n"),
            ],
        },
    };
    const viewFor = (questionId, index, columns) => {
        const view = views[`${questionId}:${index}`];
        if (!view) return null;
        const keys = new Set(columns.map((column) => column.key));
        return view.columns.every((column) => keys.has(column.key))
            ? view
            : null;
    };

    function node(tag, text, className) {
        const element = document.createElement(tag);
        if (present(text)) element.textContent = String(text);
        if (className) element.className = className;
        return element;
    }

    function badge(status) {
        return node(
            "span",
            statuses[status] || "尚未完成",
            `rk-badge ${status === "complete" ? "is-accent" : "is-warn"}`,
        );
    }

    function list(target, values, fallback) {
        const entries = array(values).filter(present);
        for (const value of entries) target.append(node("li", value));
        if (!entries.length && fallback) target.append(node("li", fallback));
    }

    // Downloads stay inside the report. The exporter verifies these files exist.
    function dataHref(value) {
        if (typeof value !== "string" || !value.startsWith("data/"))
            return null;
        if (!/^[A-Za-z0-9_./-]+$/.test(value)) return null;
        const parts = value.split("/");
        if (parts.some((part) => !part || part === "." || part === ".."))
            return null;
        return value;
    }

    function downloadList(target, values, fallback, labelOverride) {
        const seen = new Set();
        const entries = array(values).filter((item) => {
            if (!item || !dataHref(item.href) || seen.has(item.href))
                return false;
            seen.add(item.href);
            return true;
        });
        if (!entries.length) {
            if (fallback) target.append(node("p", fallback, "rk-foot"));
            return;
        }
        const ul = node("ul", null, "download-list");
        for (const item of entries) {
            const li = node("li");
            const extension = /\.csv\.gz$/.test(item.href)
                ? "CSV.gz"
                : /\.csv$/.test(item.href)
                  ? "CSV"
                  : null;
            const a = node(
                "a",
                labelOverride && extension
                    ? `${labelOverride}（${extension}）`
                    : item.label || item.href,
            );
            a.href = dataHref(item.href);
            a.setAttribute("download", "");
            li.append(a);
            const details = [];
            if (numeric(item.rows))
                details.push(`${intFormat.format(item.rows)} 列`);
            if (numeric(item.bytes))
                details.push(`${intFormat.format(item.bytes)} bytes`);
            if (details.length)
                li.append(node("span", details.join(" · "), "download-size"));
            ul.append(li);
        }
        target.append(ul);
    }

    function tableCell(value, column) {
        const cell = node("td");
        const kind = column.kind || "text";
        if (kind === "text") cell.classList.add("text-cell");
        if (!present(value) || (kind !== "text" && !numeric(value))) {
            cell.textContent = "—";
            cell.classList.add("is-na");
            cell.title = "未提供或不適用；不代表零";
            return cell;
        }
        if (kind === "integer") cell.textContent = intFormat.format(value);
        else if (kind === "number")
            cell.textContent = numberFormat.format(value);
        else if (kind === "percent")
            cell.textContent = `${headlineFormat.format(value * 100)}%`;
        else if (kind === "percentage_points" || kind === "pp")
            cell.textContent = `${formatPoints(value)} 百分點`;
        else if (kind === "multiple")
            cell.textContent = `${numberFormat.format(value)}×`;
        else cell.textContent = String(value);
        if (numeric(value))
            cell.title =
                kind === "percent"
                    ? `原始比例：${String(value)}；百分比：${String(value * 100)}%`
                    : kind === "percentage_points" || kind === "pp"
                      ? `原始百分點：${String(value)}；顯示未再乘 100`
                      : kind === "multiple"
                        ? `原始倍數：${String(value)}`
                        : `原始值：${String(value)}`;
        return cell;
    }

    function formatPoints(value) {
        if (value > 0) return `+${headlineFormat.format(value)}`;
        if (value < 0) return `−${headlineFormat.format(Math.abs(value))}`;
        return "0";
    }

    function renderTable(definition, index, questionId) {
        const collapsible = definition.collapsible === true;
        const article = node(
            collapsible ? "details" : "article",
            null,
            "rk-card question-table",
        );
        const allColumns = array(definition.columns).filter(
            (column) => column && typeof column.key === "string",
        );
        const view = viewFor(questionId, index, allColumns);
        const title = view?.title || definition.title || `資料表 ${index + 1}`;
        const headingId = `${questionId}-table-${index + 1}`;
        if (collapsible) {
            const summary = node("summary", title, "table-details-summary");
            summary.id = headingId;
            article.append(summary);
        } else {
            const heading = node("h3", title);
            heading.id = headingId;
            article.append(heading);
        }
        const columns = view ? view.columns : allColumns;
        const rows = array(definition.rows);
        if (!columns.length || !rows.length) {
            article.append(node("p", "尚未提供表格資料。", "rk-foot"));
            downloadList(article, definition.downloads);
            return article;
        }

        const wrap = node("div", null, "rk-table-wrap");
        wrap.tabIndex = 0;
        wrap.setAttribute("role", "region");
        wrap.setAttribute("aria-labelledby", headingId);
        const table = node("table", null, "rk-table");
        table.append(
            node(
                "caption",
                `${title}；共 ${intFormat.format(rows.length)} 列，可切換頁次查看全部資料。`,
            ),
        );
        const thead = node("thead");
        const headRow = node("tr");
        for (const column of columns) {
            const th = node("th", column.label || column.key);
            th.scope = "col";
            if (!column.kind || column.kind === "text")
                th.classList.add("text-cell");
            headRow.append(th);
        }
        thead.append(headRow);
        const tbody = node("tbody");
        table.append(thead, tbody);
        wrap.append(table);
        article.append(wrap);

        let page = 0;
        let pageSize = 50;
        const controls = node("div", null, "table-pagination");
        const summary = node("p", null, "table-summary");
        summary.setAttribute("aria-live", "polite");
        const previous = node("button", "上一頁");
        const next = node("button", "下一頁");
        previous.type = next.type = "button";
        const pageLabel = node("label", "頁次");
        const pageInput = node("input");
        pageInput.type = "number";
        pageInput.min = "1";
        pageInput.step = "1";
        pageInput.setAttribute("aria-label", `${title}頁次`);
        pageLabel.append(pageInput);
        const sizeLabel = node("label", "每頁");
        const size = node("select");
        size.setAttribute("aria-label", `${title}每頁列數`);
        for (const value of [25, 50, 100]) {
            const option = node("option", `${value} 列`);
            option.value = String(value);
            option.selected = value === pageSize;
            size.append(option);
        }
        sizeLabel.append(size);

        function renderRows() {
            const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
            page = Math.min(Math.max(0, page), pageCount - 1);
            const start = page * pageSize;
            const end = Math.min(rows.length, start + pageSize);
            const fragment = document.createDocumentFragment();
            for (let rowIndex = start; rowIndex < end; rowIndex += 1) {
                const tr = node("tr");
                for (const column of columns)
                    tr.append(
                        tableCell(
                            column.get
                                ? column.get(rows[rowIndex] || {})
                                : rows[rowIndex]?.[column.key],
                            column,
                        ),
                    );
                fragment.append(tr);
            }
            tbody.replaceChildren(fragment);
            summary.textContent = `第 ${intFormat.format(start + 1)}–${intFormat.format(end)} 列／共 ${intFormat.format(rows.length)} 列 · ${page + 1}／${pageCount} 頁`;
            pageInput.value = String(page + 1);
            pageInput.max = String(pageCount);
            previous.disabled = page === 0;
            next.disabled = page === pageCount - 1;
        }
        previous.addEventListener("click", () => {
            page -= 1;
            renderRows();
        });
        next.addEventListener("click", () => {
            page += 1;
            renderRows();
        });
        pageInput.addEventListener("change", () => {
            const requested = Number(pageInput.value);
            if (Number.isInteger(requested) && requested >= 1)
                page = requested - 1;
            renderRows();
        });
        size.addEventListener("change", () => {
            const firstRow = page * pageSize;
            pageSize = Number(size.value);
            page = Math.floor(firstRow / pageSize);
            renderRows();
        });
        controls.append(summary, previous, pageLabel, next, sizeLabel);
        article.append(controls);
        downloadList(
            article,
            definition.downloads,
            undefined,
            view?.downloadLabel,
        );
        renderRows();
        return article;
    }

    function renderFamilySummary(comparison) {
        const selector = byId("family-summary-horizon");
        const rowsElement = byId("family-summary-rows");
        const scopeElement = byId("family-summary-scope");
        const baselineElement = byId("family-summary-baseline");
        const statusElement = byId("family-summary-status");
        selector.value = "126";
        scopeElement.textContent =
            "不加額外條件 · 全部股票 · 全部年份 · 全部市場（與問題 2–6 用的另一半股票不是同一批樣本）";

        if (!comparison || !Array.isArray(comparison.rows)) {
            statusElement.textContent =
                "尚未提供跨型態對照摘要；不以空白或零代替資料。";
            baselineElement.textContent =
                "所有合格日的翻倍比例：N/A（比較摘要尚未提供）。";
            return;
        }

        const baselines = array(comparison.baselines);
        const countText = (value) =>
            Number.isInteger(value) && value >= 0
                ? intFormat.format(value)
                : "N/A";
        const rateText = (value, count) =>
            numeric(value) && Number.isInteger(count) && count > 0
                ? `${headlineFormat.format(value * 100)}%`
                : "N/A";
        const cell = (value, className) => node("td", value, className);

        function renderHorizon() {
            const horizon = Number(selector.value);
            const rows = comparison.rows.filter(
                (row) => row && row.horizon === horizon,
            );
            const familyCount = new Set(
                rows.map((row) => row.target).filter(present),
            ).size;
            const baseline = baselines.find(
                (row) => row && row.horizon === horizon,
            );
            const baselineKnown =
                baseline && Number.isInteger(baseline.known_n)
                    ? baseline.known_n
                    : null;
            baselineElement.textContent = `追蹤 ${horizon} 個交易日：所有合格日的翻倍比例 ${rateText(baseline?.hit_rate, baselineKnown)}（樣本 ${countText(baselineKnown)}）。`;

            const fragment = document.createDocumentFragment();
            for (const row of rows) {
                const known = row.known_n;
                const controlKnown = row.control_known_n;
                const tr = node("tr");
                tr.append(
                    cell(
                        present(row.target) ? familyLabel(row.target) : "N/A",
                        "family-name",
                    ),
                    cell(
                        baselineKnown > 0 &&
                            known > 0 &&
                            numeric(row.baseline_multiple)
                            ? `${headlineFormat.format(row.baseline_multiple)}×`
                            : "N/A",
                    ),
                    cell(
                        known > 0 && controlKnown > 0 && numeric(row.delta_pp)
                            ? `${row.delta_pp > 0 ? "+" : row.delta_pp < 0 ? "−" : ""}${headlineFormat.format(Math.abs(row.delta_pp))} 百分點`
                            : "N/A",
                    ),
                    cell(countText(known)),
                    cell(countText(controlKnown)),
                    cell(rateText(row.loss_rate, known)),
                );
                fragment.append(tr);
            }
            rowsElement.replaceChildren(fragment);
            statusElement.textContent =
                rows.length === 12 && familyCount === 12
                    ? `已列出追蹤 ${horizon} 個交易日的十二種型態。`
                    : `追蹤 ${horizon} 個交易日目前提供 ${intFormat.format(rows.length)} 列／${intFormat.format(familyCount)} 種型態；未提供的不推定為零。`;
        }

        selector.addEventListener("change", renderHorizon);
        renderHorizon();
    }

    const data = window.REPORT_DATA;
    if (!data || typeof data !== "object") {
        byId("completion-banner").replaceChildren(
            node("strong", "尚未載入研究資料。"),
            document.createTextNode(
                " 請確認報告旁的 data/summary.js 已隨頁面提供；本頁未提供的數值不代表零。",
            ),
        );
    }
    const report = data && typeof data === "object" ? data : {};
    if (present(report.title)) {
        byId("report-title").textContent = report.title;
        document.title = report.title;
    }
    // The cut-off is shown once in the header chips; the sources section explains the gap to the completion date.
    byId("as-of").textContent = "";
    byId("as-of").hidden = true;
    if (report.status === "complete") {
        byId("completion-banner").hidden = true;
    }
    const study = report.study || {};
    const meta = [];
    if (numeric(study.stockN))
        meta.push(`${intFormat.format(study.stockN)} 檔股票`);
    if (present(study.cutoff)) meta.push(`資料截止 ${study.cutoff}`);
    for (const text of meta)
        byId("study-meta").append(node("span", text, "rk-badge"));

    renderFamilySummary(report.comparisonSummary);

    for (const item of array(report.overview)) {
        const li = node("li", null, "rk-finding");
        li.append(node("span", item.label || "未提供"));
        li.append(node("b", present(item.value) ? item.value : "未提供"));
        if (present(item.note)) li.append(node("p", item.note));
        byId("overview-values").append(li);
    }

    for (let number = 1; number <= 6; number += 1) {
        const id = `Q${number}`;
        const question =
            array(report.questions).find((item) => item?.id === id) || {};
        const status = statuses[question.status] ? question.status : "pending";
        const title = question.title || "尚未提供研究結果";
        const link = node("a", null, "question-link");
        link.href = `#${id}`;
        const label = `問題 ${number}`;
        link.append(node("span", label, "question-id"));
        if (status !== "complete") link.append(badge(status));
        link.append(node("p", title));
        byId("question-progress").append(link);

        const section = node("section", null, "rk-section");
        section.id = id;
        section.setAttribute("aria-labelledby", `${id}-title`);
        const header = node("header");
        const heading = node("div");
        const h2 = node("h2", title);
        h2.id = `${id}-title`;
        heading.append(node("span", label, "rk-q"), h2);
        header.append(heading);
        if (status !== "complete") header.append(badge(status));
        section.append(
            header,
            node(
                "p",
                question.conclusion || "尚未完成，暫無可呈現的結論。",
                "rk-answer",
            ),
        );
        const notes = node("ul", null, "question-notes");
        list(notes, question.notes);
        const evidence = node("details", null, "question-evidence");
        evidence.append(node("summary", "查看比較口徑、數據與下載"));
        if (notes.childElementCount) evidence.append(notes);
        const tables = array(question.tables);
        tables.forEach((table, index) => {
            if (table && typeof table === "object")
                evidence.append(renderTable(table, index, id));
        });
        if (!tables.length)
            section.append(node("p", "本題尚未提供成果表。", "rk-note"));
        section.append(evidence);
        byId("questions").append(section);
    }

    const audit = report.audit || {};
    byId("audit-status").textContent =
        audit.status === "complete"
            ? "既定範圍核對已完成。"
            : audit.status === "partial"
              ? "已完成固定範圍核對；其他研究階段仍未完成。"
              : "稽核狀態尚未提供；既定範圍核對不代表全研究驗收。";
    list(byId("audit-notes"), audit.notes, "未提供其他稽核細節。 ");
    list(byId("limitations"), report.limitations, "尚未提供完整限制說明。 ");
    const provenance = [...array(report.provenance)];
    if (present(study.generation))
        provenance.unshift({
            label: "價格資料版本",
            value: study.generation,
        });
    for (const item of provenance) {
        if (!item || typeof item !== "object") continue;
        const dd = node("dd");
        const href = dataHref(item.href);
        if (href) {
            const a = node("a", present(item.value) ? item.value : "未提供");
            a.href = href;
            a.setAttribute("download", "");
            dd.append(a);
        } else
            dd.textContent = present(item.value)
                ? String(item.value)
                : "未提供";
        byId("provenance").append(node("dt", item.label || "來源"), dd);
    }
    if (!provenance.length)
        byId("provenance").append(
            node("dt", "來源紀錄"),
            node("dd", "尚未提供"),
        );
    downloadList(
        byId("downloads"),
        report.downloads,
        "尚未提供可下載的成果檔。",
    );
})();
