/* ============================================================
   STOCK research report kit v1 — small helpers for AI-written reports.
   Optional: a report may use any of these or draw everything itself.
   Works standalone (file://) and inside the studio's sandboxed iframe,
   where the origin is opaque, so storage access is always guarded.
   ============================================================ */
(function () {
    "use strict";

    const root = document.documentElement;
    const inFrame = window.parent !== window;
    const PALETTES = new Set(["forest", "ocean", "plum", "sand"]);
    const APPEARANCES = new Set(["light", "dark"]);

    /* ---------- theme ---------- */
    function applyTheme(theme) {
        if (theme && PALETTES.has(theme.palette))
            root.dataset.palette = theme.palette;
        if (theme && APPEARANCES.has(theme.appearance))
            root.dataset.appearance = theme.appearance;
        document.dispatchEvent(new CustomEvent("rk:theme"));
    }
    function themeFromHash() {
        const params = new URLSearchParams(location.hash.replace(/^#/, ""));
        return {
            palette: params.get("palette"),
            appearance: params.get("appearance"),
        };
    }
    const initial = themeFromHash();
    if (!APPEARANCES.has(initial.appearance))
        initial.appearance = matchMedia("(prefers-color-scheme: dark)").matches
            ? "dark"
            : "light";
    if (!PALETTES.has(initial.palette)) initial.palette = "forest";
    applyTheme(initial);

    window.addEventListener("message", (event) => {
        // The sandboxed frame sees an opaque origin; trust only the host window.
        if (event.source !== window.parent || !event.data) return;
        if (event.data.type === "rk:theme") applyTheme(event.data);
    });

    /* ---------- height reporting for the studio frame ---------- */
    if (inFrame && "ResizeObserver" in window) {
        let last = 0;
        const report = () => {
            const height = Math.ceil(
                document.documentElement.getBoundingClientRect().height,
            );
            if (Math.abs(height - last) < 2) return;
            last = height;
            window.parent.postMessage({ type: "rk:height", height }, "*");
        };
        new ResizeObserver(report).observe(document.documentElement);
        window.addEventListener("load", report);
    }

    /* ---------- storage (opaque origins throw) ---------- */
    const store = {
        get(key) {
            try {
                return localStorage.getItem(key);
            } catch {
                return null;
            }
        },
        set(key, value) {
            try {
                localStorage.setItem(key, value);
            } catch {
                /* Storage is unavailable in sandboxed frames. */
            }
        },
    };

    /* ---------- formatting ---------- */
    const isNum = (v) => typeof v === "number" && Number.isFinite(v);
    const fmt = {
        pct(value, digits = 1) {
            return isNum(value) ? `${(value * 100).toFixed(digits)}%` : "—";
        },
        pp(delta, digits = 1) {
            if (!isNum(delta)) return "—";
            const v = delta * 100;
            return `${v > 0 ? "+" : v < 0 ? "−" : "±"}${Math.abs(v).toFixed(digits)} pp`;
        },
        int(value) {
            return isNum(value)
                ? Math.round(value).toLocaleString("zh-TW")
                : "—";
        },
        ratio(numerator, denominator) {
            return isNum(numerator) && isNum(denominator) && denominator > 0
                ? numerator / denominator
                : null;
        },
    };

    /* ---------- data ---------- */
    /** Convert a {columns, rows} table into an array of objects. */
    function records(table) {
        if (!table) return [];
        const { columns, rows } = table;
        return rows.map((row) => {
            const item = {};
            columns.forEach((name, i) => (item[name] = row[i]));
            return item;
        });
    }

    /* ---------- DOM / SVG ---------- */
    const SVG_NS = "http://www.w3.org/2000/svg";
    function svg(tag, attrs = {}, children = []) {
        const node = document.createElementNS(SVG_NS, tag);
        for (const [key, value] of Object.entries(attrs))
            if (value !== null && value !== undefined)
                node.setAttribute(key, value);
        for (const child of [].concat(children))
            if (child !== null && child !== undefined)
                node.append(
                    typeof child === "string"
                        ? document.createTextNode(child)
                        : child,
                );
        return node;
    }
    function html(tag, attrs = {}, children = []) {
        const node = document.createElement(tag);
        for (const [key, value] of Object.entries(attrs)) {
            if (value === null || value === undefined) continue;
            if (key === "class") node.className = value;
            else if (key.startsWith("on"))
                node.addEventListener(key.slice(2), value);
            else node.setAttribute(key, value);
        }
        for (const child of [].concat(children))
            if (child !== null && child !== undefined)
                node.append(
                    typeof child === "string"
                        ? document.createTextNode(child)
                        : child,
                );
        return node;
    }
    /** Read a design token, e.g. token("--gain"). */
    function token(name) {
        return getComputedStyle(root).getPropertyValue(name).trim();
    }

    /* ---------- segmented control ---------- */
    function segmented(container, { label, options, value, onChange }) {
        const group = html("span", {
            class: "rk-seg",
            role: "group",
            "aria-label": label,
        });
        let current = value;
        const buttons = options.map((option) =>
            html(
                "button",
                {
                    type: "button",
                    "aria-pressed": String(option.value === current),
                    onclick: () => {
                        current = option.value;
                        buttons.forEach((b, i) =>
                            b.setAttribute(
                                "aria-pressed",
                                String(options[i].value === current),
                            ),
                        );
                        onChange(current);
                    },
                },
                option.label,
            ),
        );
        group.append(...buttons);
        const wrapper = html(
            "span",
            { class: "rk-control" },
            label ? [label, group] : [group],
        );
        container.append(wrapper);
        return {
            get value() {
                return current;
            },
        };
    }

    /* ---------- tooltip ---------- */
    let tip = null;
    const tooltip = {
        show(event, content) {
            if (!tip) {
                tip = html("div", { class: "rk-tooltip", role: "tooltip" });
                document.body.append(tip);
            }
            tip.innerHTML = content;
            tip.classList.add("is-visible");
            const pad = 14;
            const { innerWidth, innerHeight } = window;
            const rect = tip.getBoundingClientRect();
            let x = event.clientX + pad;
            let y = event.clientY + pad;
            if (x + rect.width > innerWidth - 8)
                x = event.clientX - rect.width - pad;
            if (y + rect.height > innerHeight - 8)
                y = event.clientY - rect.height - pad;
            tip.style.left = `${Math.max(8, x)}px`;
            tip.style.top = `${Math.max(8, y)}px`;
        },
        hide() {
            tip?.classList.remove("is-visible");
        },
    };

    /* ---------- colour scales ---------- */
    function mix(a, b, t) {
        const pa = parse(a);
        const pb = parse(b);
        if (!pa || !pb) return b;
        const c = pa.map((v, i) => Math.round(v + (pb[i] - v) * t));
        return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
    }
    const parsed = new Map();
    function parse(color) {
        if (parsed.has(color)) return parsed.get(color);
        const probe = document.createElement("span");
        probe.style.color = color;
        document.body.append(probe);
        const value = getComputedStyle(probe).color;
        probe.remove();
        const match = value.match(/\d+(\.\d+)?/g);
        const rgb = match ? match.slice(0, 3).map(Number) : null;
        parsed.set(color, rgb);
        return rgb;
    }
    /**
     * Diverging scale around zero: positive → --gain, negative → --loss.
     * `limit` is the absolute value that reaches full colour.
     */
    function diverging(limit) {
        const base = token("--surface");
        const up = token("--gain");
        const down = token("--loss");
        return (value) => {
            if (!isNum(value)) return token("--surface-2");
            const t = Math.min(1, Math.abs(value) / limit);
            return mix(base, value >= 0 ? up : down, 0.12 + 0.78 * t);
        };
    }

    window.ReportKit = {
        version: "v1",
        applyTheme,
        store,
        fmt,
        records,
        svg,
        html,
        token,
        segmented,
        tooltip,
        diverging,
        mix,
    };
})();
