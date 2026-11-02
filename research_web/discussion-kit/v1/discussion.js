/* Reusable direction discussion view. No network, storage or approval side effects. */
(function (global) {
    "use strict";

    const BRANCHES = ["supports", "does-not-support", "unclear"];
    const mounted = new WeakMap();
    let nextId = 0;

    function requireText(value, name) {
        if (typeof value !== "string" || !value.trim())
            throw new Error(`${name} 尚未填寫。`);
    }

    function unique(items, label) {
        if (new Set(items).size !== items.length)
            throw new Error(`${label} 有重複的識別碼。`);
    }

    function validateModel(model) {
        if (!model || model.schema !== "direction-discussion.v1")
            throw new Error("討論資料的版本不支援，請更新來源資料。");
        if (typeof model.demo !== "boolean")
            throw new Error("請明確標示這是示例或實際草稿。");
        for (const key of ["taskId", "draftPath", "revision"])
            requireText(model.source?.[key], `來源 ${key}`);
        if (!model.demo && !/^[a-f0-9]{40}$/i.test(model.source.revision))
            throw new Error(
                "正式討論須指定完整 Git commit，不能使用會變動的分支名稱。",
            );
        requireText(model.ownerPurpose, "研究目的");
        if (!["pending", "confirmed"].includes(model.purposeStatus))
            throw new Error("目的確認狀態無法辨識。");
        if (!Array.isArray(model.outcomes) || model.outcomes.length !== 3)
            throw new Error("請提供成立、不成立與分不出來三種結果。");
        unique(
            model.outcomes.map((item) => item.id),
            "結果分支",
        );
        for (const item of model.outcomes) {
            if (!BRANCHES.includes(item.id))
                throw new Error("結果分支的識別碼無法辨識。");
            for (const key of ["title", "headline", "decision", "limitation"])
                requireText(item[key], `結果分支 ${key}`);
            if (/[%％]|百分之/.test(item.headline.replace(/▢▢\s*[%％]/g, "")))
                throw new Error("假頭條請用 ▢▢% 佔位，不可填入研究結果。");
        }
        if (!Array.isArray(model.choices) || !Array.isArray(model.questions))
            throw new Error("選擇與前作問題必須是清單。");
        unique(
            model.choices.map((item) => item.id),
            "選擇",
        );
        for (const choice of model.choices) {
            if (!/^C[1-9]\d*$/.test(choice.id))
                throw new Error("選擇識別碼須為 C1、C2 等固定編號。");
            requireText(choice.question, `${choice.id} 問題`);
            if (!Array.isArray(choice.options) || choice.options.length < 2)
                throw new Error(`${choice.id} 至少需要兩個可比較的選項。`);
            unique(
                choice.options.map((item) => item.id),
                `${choice.id} 選項`,
            );
            for (const option of choice.options) {
                if (
                    typeof option.id !== "string" ||
                    !/^[a-z][a-z0-9-]*$/.test(option.id)
                )
                    throw new Error(`${choice.id} 選項識別碼格式不正確。`);
                requireText(option.label, `${choice.id} 選項名稱`);
                requireText(option.impact, `${choice.id} 選項影響`);
            }
        }
        unique(
            model.questions.map((item) => item.reference),
            "前作問題",
        );
        for (const item of model.questions) {
            if (!/^[A-Za-z0-9][A-Za-z0-9._-]*#Q[1-9]\d*$/.test(item.reference))
                throw new Error("前作問題須保留完整 task-id#Q1 識別碼。");
            for (const key of ["question", "status", "reason", "source"])
                requireText(item[key], `前作問題 ${key}`);
        }
        return model;
    }

    function createSession(input) {
        validateModel(input);
        // A mounted view owns a snapshot. Caller edits cannot silently change its revision.
        const model = JSON.parse(JSON.stringify(input));
        const selections = new Map(
            model.choices.map((choice) => [choice.id, null]),
        );
        let notes = "";
        return {
            select(choiceId, optionId) {
                const choice = model.choices.find(
                    (item) => item.id === choiceId,
                );
                if (
                    !choice ||
                    (optionId !== null &&
                        !choice.options.some((item) => item.id === optionId))
                )
                    throw new Error(
                        "選項不屬於目前的討論版本，請重新開啟草稿。",
                    );
                selections.set(choiceId, optionId);
            },
            setNotes(value) {
                if (typeof value !== "string")
                    throw new Error("備註必須是文字。");
                notes = value;
            },
            exportFeedback() {
                return {
                    schema: "direction-feedback.v1",
                    status: "proposed",
                    source: { ...model.source },
                    selections: Array.from(
                        selections,
                        ([choiceId, optionId]) => ({ choiceId, optionId }),
                    ),
                    notes,
                };
            },
        };
    }

    function markdownText(value) {
        return String(value)
            .replace(/\r?\n/g, " ")
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/\\/g, "\\\\")
            .replace(/([`*_{}[\]()#+.!|~-])/g, "\\$1");
    }

    function toMarkdown(model, feedback) {
        validateModel(model);
        if (
            feedback?.schema !== "direction-feedback.v1" ||
            feedback.status !== "proposed"
        )
            throw new Error("只能整理尚待確認的討論回饋。");
        for (const key of ["taskId", "draftPath", "revision"])
            if (feedback.source?.[key] !== model.source[key])
                throw new Error("回饋與草稿版本不同，請回到原版本核對。");
        if (
            !Array.isArray(feedback.selections) ||
            feedback.selections.length !== model.choices.length
        )
            throw new Error("回饋的選擇清單不完整。");
        unique(
            feedback.selections.map((item) => item.choiceId),
            "回饋選擇",
        );
        const check = createSession(model);
        feedback.selections.forEach(({ choiceId, optionId }) =>
            check.select(choiceId, optionId),
        );
        check.setNotes(feedback.notes);
        const lines = [
            "## 研究方向討論回饋",
            "",
            "這是我的討論提議，尚未確認方向，也未授權市場計算。",
            `來源：${markdownText(model.source.taskId)} / ${markdownText(model.source.draftPath)}`,
            `版本：${markdownText(model.source.revision)}`,
            "",
        ];
        for (const choice of model.choices) {
            const selection = feedback.selections.find(
                (item) => item.choiceId === choice.id,
            );
            const option = choice.options.find(
                (item) => item.id === selection.optionId,
            );
            lines.push(
                `- ${choice.id} ${markdownText(choice.question)}：${option ? markdownText(option.label) : "尚未選擇"}`,
            );
            if (option) lines.push(`  - 影響：${markdownText(option.impact)}`);
        }
        lines.push("", "### 我的備註", "");
        lines.push(
            ...(feedback.notes || "尚未填寫")
                .split(/\r?\n/)
                .map((line) => `> ${markdownText(line)}`),
        );
        return lines.join("\n");
    }

    function mount(root, input) {
        mounted.get(root)?.destroy();
        const document = root.ownerDocument;
        root.replaceChildren();
        let model;
        try {
            validateModel(input);
            model = JSON.parse(JSON.stringify(input));
        } catch (error) {
            const alert = document.createElement("p");
            alert.setAttribute("role", "alert");
            alert.className = "dd-error";
            alert.textContent = `暫時無法開啟討論：${error.message}`;
            root.append(alert);
            return {
                destroy: () => alert.remove(),
                exportFeedback: () => {
                    throw error;
                },
            };
        }
        const session = createSession(model);
        const disposers = [];
        const urls = new Set();
        const prefix = `dd-${++nextId}`;
        let active = true;
        let exportVisible = false;

        function el(tag, className, text) {
            const node = document.createElement(tag);
            if (className) node.className = className;
            if (text !== undefined) node.textContent = text;
            return node;
        }
        function listen(node, type, callback) {
            node.addEventListener(type, callback);
            disposers.push(() => node.removeEventListener(type, callback));
        }
        function section(number, title, subtitle) {
            const box = el("section", "dd-section");
            const heading = el("div", "dd-section-heading");
            heading.append(
                el("span", "dd-number", number),
                el("h2", "", title),
            );
            box.append(heading, el("p", "dd-muted", subtitle));
            return box;
        }

        const page = el("div", "dd-page");
        const hero = el("header", "dd-hero");
        hero.append(
            el(
                "span",
                "dd-badge",
                model.demo ? "互動示範・非研究結果" : "方向討論・非研究結果",
            ),
        );
        hero.append(el("h1", "", "一起把研究方向說清楚"));
        hero.append(
            el(
                "p",
                "dd-intro",
                "先看看不同答案能幫你做什麼，再選擇這次值得研究的問題。",
            ),
        );
        const purpose = el("div", "dd-purpose");
        purpose.append(
            el(
                "span",
                "dd-eyebrow",
                model.demo ? "示範目的（非擁有者原話）" : "這次想解決的事",
            ),
        );
        purpose.append(el("p", "", model.ownerPurpose));
        purpose.append(
            el(
                "span",
                "dd-purpose-state",
                model.purposeStatus === "confirmed"
                    ? "來源標記為已確認；本頁選擇仍是提議"
                    : "目的仍待確認",
            ),
        );
        hero.append(purpose);
        if (model.demo)
            hero.append(
                el(
                    "p",
                    "dd-muted",
                    "教學示例，未連接實際方向草稿。沒有載入市場資料。",
                ),
            );
        page.append(hero);

        const outcomes = section(
            "01",
            "如果答案不一樣，會怎麼說？",
            "切換的是可能的結果，不是選你想要的研究結論。所有數字都還是佔位符。",
        );
        const branches = el("div", "dd-branches");
        branches.setAttribute("role", "group");
        branches.setAttribute("aria-label", "探索可能的研究結果");
        const result = el("div", "dd-result");
        result.setAttribute("aria-live", "polite");
        const branchButtons = [];
        function showOutcome(id) {
            const item = model.outcomes.find((outcome) => outcome.id === id);
            branchButtons.forEach(({ button, id: buttonId }) =>
                button.setAttribute("aria-pressed", String(buttonId === id)),
            );
            result.replaceChildren();
            result.append(
                el("p", "dd-eyebrow", "假如報告的答案是…"),
                el("h3", "dd-headline", item.headline),
            );
            const implications = el("div", "dd-implications");
            const decision = el("div");
            decision.append(
                el("h4", "", "你接下來能做什麼"),
                el("p", "", item.decision),
            );
            const limit = el("div");
            limit.append(
                el("h4", "", "這還不能告訴你"),
                el("p", "", item.limitation),
            );
            implications.append(decision, limit);
            result.append(implications);
        }
        for (const item of model.outcomes) {
            const button = el("button", "dd-branch", item.title);
            button.type = "button";
            listen(button, "click", () => showOutcome(item.id));
            branchButtons.push({ button, id: item.id });
            branches.append(button);
        }
        outcomes.append(branches, result);
        showOutcome("supports");
        page.append(outcomes);

        const choices = section(
            "02",
            "這次，你比較想回答哪個問題？",
            "點選後會看到研究承諾與工作範圍的差別。可以改選，也可以先保留。",
        );
        const progress = el("p", "dd-progress");
        progress.setAttribute("aria-live", "polite");
        choices.append(progress);
        const feedback = section(
            "04",
            "把你的想法帶回討論",
            "整理後可複製回對話或 PR；此頁不會自動送出，也不會替你確認方向。",
        );
        const notesLabel = el("label", "dd-label", "還想補充什麼？");
        const notes = el("textarea", "dd-notes");
        notes.id = `${prefix}-notes`;
        notesLabel.htmlFor = notes.id;
        notes.rows = 4;
        notes.placeholder =
            "例如：我更在意能不能作為停損依據，而不只是比例有沒有下降。";
        const output = el("textarea", "dd-export");
        output.id = `${prefix}-export`;
        output.readOnly = true;
        output.rows = 12;
        output.setAttribute("aria-label", "可複製的討論回饋");
        const exportBox = el("div", "dd-export-box");
        exportBox.hidden = true;
        const status = el("p", "dd-muted");
        status.setAttribute("role", "status");
        function updateFeedback() {
            const snapshot = session.exportFeedback();
            const count = snapshot.selections.filter(
                (item) => item.optionId !== null,
            ).length;
            progress.textContent = `已提出 ${count} / ${model.choices.length} 個選擇；其餘保留為「尚未選擇」。`;
            if (exportVisible) output.value = toMarkdown(model, snapshot);
            status.textContent = "";
        }
        for (const choice of model.choices) {
            const card = el("div", "dd-choice");
            const title = el("h3", "", `${choice.id} · ${choice.question}`);
            title.id = `${prefix}-${choice.id}`;
            const options = el("div", "dd-options");
            options.setAttribute("role", "group");
            options.setAttribute("aria-labelledby", title.id);
            const impact = el(
                "p",
                "dd-impact",
                "尚未選擇。先點一個選項，看看這次會多回答什麼、還有哪些限制。",
            );
            impact.setAttribute("aria-live", "polite");
            const buttons = [];
            function choose(id) {
                session.select(choice.id, id);
                buttons.forEach(({ button, id: optionId }) =>
                    button.setAttribute(
                        "aria-pressed",
                        String(optionId === id),
                    ),
                );
                impact.textContent =
                    id === null
                        ? "尚未選擇，可以留待討論。"
                        : choice.options.find((option) => option.id === id)
                              .impact;
                updateFeedback();
            }
            for (const option of choice.options) {
                const button = el("button", "dd-option", option.label);
                button.type = "button";
                button.setAttribute("aria-pressed", "false");
                listen(button, "click", () => choose(option.id));
                buttons.push({ button, id: option.id });
                options.append(button);
            }
            const clear = el("button", "dd-clear", "先保留，不選");
            clear.type = "button";
            listen(clear, "click", () => choose(null));
            card.append(title, options, impact, clear);
            choices.append(card);
        }
        page.append(choices);

        const questions = section(
            "03",
            "前面的研究，還留下什麼？",
            "展開看看問題為什麼還在、來源在哪裡。新方向應承接，或說明這次不承接的理由。",
        );
        for (const item of model.questions) {
            const detail = el("details", "dd-question");
            detail.append(el("summary", "", item.question));
            detail.append(
                el("p", "dd-reference", `${item.reference} · ${item.status}`),
            );
            detail.append(
                el("p", "", item.reason),
                el("p", "dd-muted", `來源：${item.source}`),
            );
            questions.append(detail);
        }
        if (!model.questions.length)
            questions.append(
                el(
                    "p",
                    "dd-muted",
                    "這份討論沒有列出前作問題；仍需作者核對是否遺漏。",
                ),
            );
        page.append(questions);

        listen(notes, "input", () => {
            session.setNotes(notes.value);
            updateFeedback();
        });
        const actions = el("div", "dd-actions");
        const organize = el("button", "dd-primary", "整理我的想法");
        organize.type = "button";
        listen(organize, "click", () => {
            exportVisible = true;
            exportBox.hidden = false;
            updateFeedback();
            output.focus();
        });
        const copy = el("button", "dd-secondary", "複製討論回饋");
        copy.type = "button";
        listen(copy, "click", async () => {
            try {
                await document.defaultView.navigator.clipboard.writeText(
                    output.value,
                );
                if (active) status.textContent = "已複製，可以貼回對話或 PR。";
            } catch {
                if (!active) return;
                output.focus();
                output.select();
                status.textContent =
                    "瀏覽器未開放自動複製，已選取文字，請按 Ctrl+C（或長按複製）。";
            }
        });
        const download = el("button", "dd-secondary", "下載選擇紀錄 JSON");
        download.type = "button";
        listen(download, "click", () => {
            const view = document.defaultView;
            try {
                const blob = new view.Blob(
                    [JSON.stringify(session.exportFeedback(), null, 2)],
                    { type: "application/json;charset=utf-8" },
                );
                const url = view.URL.createObjectURL(blob);
                urls.add(url);
                const anchor = el("a");
                anchor.href = url;
                anchor.download = "direction-feedback.json";
                page.append(anchor);
                anchor.click();
                anchor.remove();
                status.textContent =
                    "已請瀏覽器下載；若嵌入頁不允許下載，可複製上方回饋。";
            } catch {
                status.textContent = "這個環境無法下載，請複製上方討論回饋。";
            }
        });
        actions.append(organize);
        exportBox.append(output, copy, download, status);
        feedback.append(notesLabel, notes, actions, exportBox);
        page.append(feedback);
        const footer = el("footer", "dd-footer");
        footer.append(
            el(
                "p",
                "",
                `討論版本：${model.source.revision} · ${model.source.taskId}`,
            ),
        );
        footer.append(el("p", "", `來源：${model.source.draftPath}`));
        footer.append(
            el(
                "p",
                "",
                "選項與備註僅保存在目前頁面。重新載入或切換版本會清空，請先複製或下載。",
            ),
        );
        page.append(footer);
        root.append(page);
        updateFeedback();
        const api = {
            exportFeedback: () => session.exportFeedback(),
            destroy() {
                if (!active) return;
                active = false;
                disposers.forEach((dispose) => dispose());
                urls.forEach((url) =>
                    document.defaultView.URL.revokeObjectURL(url),
                );
                page.remove();
                if (mounted.get(root) === api) mounted.delete(root);
            },
        };
        mounted.set(root, api);
        return api;
    }

    global.DirectionDiscussion = Object.freeze({
        validateModel,
        createSession,
        toMarkdown,
        mount,
    });
})(globalThis);
