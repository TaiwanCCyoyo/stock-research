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
        else cell.textContent = String(value);
        if (numeric(value))
            cell.title =
                kind === "percent"
                    ? `原始比例：${String(value)}；百分比：${String(value * 100)}%`
                    : `原始值：${String(value)}`;
        return cell;
    }

    function renderTable(definition, index, questionId) {
        const article = node("article", null, "rk-card question-table");
        const title = definition.title || `資料表 ${index + 1}`;
        const headingId = `${questionId}-table-${index + 1}`;
        const heading = node("h3", title);
        heading.id = headingId;
        article.append(heading);
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
        byId("completion-banner").className = "rk-note";
        byId("completion-banner").replaceChildren(
            node("strong", "研究結果已彙整。"),
            document.createTextNode(
                " 各題結果、稽核狀態與使用限制分別列於下方；此狀態不代表策略通過。",
            ),
        );
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
        link.append(
            node("span", id, "question-id"),
            badge(status),
            node("p", title),
        );
        byId("question-progress").append(link);

        const section = node("section", null, "rk-section");
        section.id = id;
        section.setAttribute("aria-labelledby", `${id}-title`);
        const header = node("header");
        const heading = node("div");
        const h2 = node("h2", title);
        h2.id = `${id}-title`;
        heading.append(node("span", id, "rk-q"), h2);
        header.append(heading, badge(status));
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
        if (notes.childElementCount) section.append(notes);
        const tables = array(question.tables);
        tables.forEach((table, index) => {
            if (table && typeof table === "object")
                section.append(renderTable(table, index, id));
        });
        if (!tables.length)
            section.append(node("p", "本題尚未提供成果表。", "rk-note"));
        byId("questions").append(section);
    }

    const audit = report.audit || {};
    byId("audit-status").textContent =
        audit.status === "complete"
            ? "已完成（範圍與結果依下列紀錄）"
            : audit.status === "partial"
              ? "部分完成；尚有稽核未完成"
              : "尚未完成";
    list(byId("audit-notes"), audit.notes, "尚未提供完整稽核結果。 ");
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
