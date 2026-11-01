/* Display saved candidate-direction counts; no research calculation. */
(() => {
    // Related-report links: inside the viewer iframe, ask the host to navigate.
    function relatedReportLinks() {
        const hosted = ["http:", "https:"].includes(window.location.protocol);
        for (const link of document.querySelectorAll(
            "a[data-related-report]",
        )) {
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

    // Headline table: per-pattern unconditional comparison from the saved
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
    function renderHeadlineTable() {
        const body = document.getElementById("headline-rows");
        const summary = window.REPORT_DATA?.comparisonSummary;
        if (!body || !summary || !Array.isArray(summary.rows)) return;
        const base = (summary.baselines || []).find((r) => r.horizon === 252);
        if (!base || !(base.hit_rate > 0)) return;
        const pct = (v) => `${(v * 100).toFixed(1)}%`;
        const int = (v) => v.toLocaleString("en-US");
        const rows = summary.rows
            .filter((r) => r.horizon === 252 && names[r.target])
            .map((r) => ({ ...r, rate: r.baseline_multiple * base.hit_rate }))
            .sort((x, y) => y.delta_pp - x.delta_pp);
        const fragment = document.createDocumentFragment();
        for (const r of rows) {
            const [higher, lower, incomparable] = conditionCounts[r.target];
            const tr = document.createElement("tr");
            const name = document.createElement("td");
            name.textContent = `${names[r.target]}（${r.target}）`;
            const plain = document.createElement("td");
            const conditional = document.createElement("td");
            if (!(r.known_n >= 100 && r.control_known_n >= 100)) {
                plain.textContent = "樣本不足，不下結論";
            } else {
                const control = r.rate - r.delta_pp / 100;
                const sign = r.delta_pp > 0 ? "高" : "低";
                const strong = document.createElement("span");
                strong.className = r.delta_pp > 0 ? "delta-up" : "delta-down";
                strong.textContent = `${pct(r.rate)} 對 ${pct(control)}`;
                const small = document.createElement("small");
                const size = Math.abs(r.delta_pp);
                small.textContent = `${sign} ${size < 0.05 ? "不到 0.1" : size.toFixed(1)} 個百分點 · 樣本 ${int(r.known_n)}`;
                plain.append(strong, small);
            }
            if (higher + lower < 10) {
                conditional.textContent = "樣本不足，不下結論";
            } else {
                conditional.textContent = `${higher} 組較高 · ${lower} 組較低`;
                if (incomparable > 0) {
                    const small = document.createElement("small");
                    small.textContent = `另有 ${incomparable} 組無法比較`;
                    conditional.append(small);
                }
            }
            tr.append(name, plain, conditional);
            fragment.append(tr);
        }
        body.replaceChildren(fragment);
    }
    renderHeadlineTable();

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
