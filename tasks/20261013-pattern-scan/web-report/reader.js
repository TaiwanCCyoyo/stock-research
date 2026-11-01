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
