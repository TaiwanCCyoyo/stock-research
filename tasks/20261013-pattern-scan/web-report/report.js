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

    function downloadList(target, values, fallback) {
        const entries = array(values).filter(
            (item) => item && dataHref(item.href),
        );
        if (!entries.length) {
            if (fallback) target.append(node("p", fallback, "rk-foot"));
            return;
        }
        const ul = node("ul", null, "download-list");
        for (const item of entries) {
            const li = node("li");
            const a = node("a", item.label || item.href);
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
            cell.textContent = `${numberFormat.format(value * 100)}%`;
        else if (kind === "percentage_points" || kind === "pp")
            cell.textContent = `${formatPoints(value)} pt`;
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
        if (value > 0) return `+${numberFormat.format(value)}`;
        if (value < 0) return `−${numberFormat.format(Math.abs(value))}`;
        return "0";
    }

    function renderTable(definition, index, questionId) {
        const collapsible = definition.collapsible === true;
        const article = node(
            collapsible ? "details" : "article",
            null,
            "rk-card question-table",
        );
        const title = definition.title || `資料表 ${index + 1}`;
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
        const columns = array(definition.columns).filter(
            (column) => column && typeof column.key === "string",
        );
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
                    tr.append(tableCell(rows[rowIndex]?.[column.key], column));
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
        downloadList(article, definition.downloads);
        renderRows();
        return article;
    }

    function renderFamilySummary(comparison) {
        const selector = byId("family-summary-horizon");
        const rowsElement = byId("family-summary-rows");
        const scopeElement = byId("family-summary-scope");
        const baselineElement = byId("family-summary-baseline");
        const statusElement = byId("family-summary-status");
        const fixedScope =
            "Q1 固定口徑：無額外條件 · split=all · era=all · mkt=all · cohort=union";
        selector.value = "126";
        scopeElement.textContent = fixedScope;

        const recordedScope = comparison?.scope;
        if (typeof recordedScope === "string" && recordedScope.trim()) {
            scopeElement.textContent += ` · 記錄 scope：${recordedScope}`;
        } else if (
            recordedScope &&
            typeof recordedScope === "object" &&
            !Array.isArray(recordedScope)
        ) {
            const details = Object.entries(recordedScope)
                .map(([key, value]) => {
                    const text =
                        value && typeof value === "object"
                            ? JSON.stringify(value)
                            : String(value);
                    return `${key}=${text}`;
                })
                .join(" · ");
            if (details)
                scopeElement.textContent += ` · 記錄 scope：${details}`;
        }

        if (!comparison || !Array.isArray(comparison.rows)) {
            statusElement.textContent =
                "尚未提供跨家族對照摘要；不以空白或零代替資料。";
            baselineElement.textContent =
                "C-base-daily 基準：N/A（比較摘要尚未提供）。";
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
            baselineElement.textContent = `H${horizon} 倍數基準：C-base-daily 命中率 ${rateText(baseline?.hit_rate, baselineKnown)}（K=${countText(baselineKnown)}）。`;

            const fragment = document.createDocumentFragment();
            for (const row of rows) {
                const known = row.known_n;
                const controlKnown = row.control_known_n;
                const tr = node("tr");
                tr.append(
                    cell(
                        present(row.target) ? row.target : "N/A",
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
                            ? `${row.delta_pp > 0 ? "+" : row.delta_pp < 0 ? "−" : ""}${headlineFormat.format(Math.abs(row.delta_pp))} pt`
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
                    ? `已列出 H${horizon} 的十二家族資料。`
                    : `H${horizon} 目前提供 ${intFormat.format(rows.length)} 列／${intFormat.format(familyCount)} 個家族；未提供的家族不推定為零。`;
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
    byId("as-of").textContent =
        `資料更新時間：${present(report.asOf) ? report.asOf : "未提供"}`;
    if (report.status === "complete") {
        byId("completion-banner").hidden = true;
    }
    const study = report.study || {};
    const period = array(study.period);
    const meta = [];
    if (period.length === 2) meta.push(`${period[0]} 至 ${period[1]}`);
    if (numeric(study.stockN))
        meta.push(`${intFormat.format(study.stockN)} 檔股票`);
    if (array(study.horizons).length)
        meta.push(`觀察期 ${study.horizons.join("／")} 個交易日`);
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
            label: "價格等價移交世代",
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
