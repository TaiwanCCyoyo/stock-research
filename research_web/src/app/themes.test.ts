import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { themeId, THEMES } from "./themes.ts";
import {
    readReportThemeTokens,
    REPORT_KIT_COLOR_TOKEN_NAMES,
    STUDIO_THEME_TOKEN_NAMES,
} from "../features/report-library/themeBridge.ts";

test("saved palette ids keep working and unknown ids fall back", () => {
    for (const id of ["forest", "ocean", "plum", "sand"])
        assert.equal(themeId(id), id);
    assert.equal(themeId("sakura"), "sakura");
    assert.equal(themeId("neon"), "forest");
    assert.equal(themeId(null), "forest");
});

test("every theme defines both appearances in the stylesheet", () => {
    const css = readFileSync(new URL("./themes.css", import.meta.url), "utf8");
    for (const theme of THEMES.filter((t) => t.id !== "forest")) {
        assert.ok(css.includes(`.studio[data-palette="${theme.id}"] {`));
        assert.ok(
            css.includes(
                `.studio[data-appearance="dark"][data-palette="${theme.id}"] {`,
            ),
            theme.id,
        );
    }
});

test("all eight themes define the shared report tokens for light and dark", () => {
    const kitCss = readFileSync(
        new URL("../../report-kit/v1/report-kit.css", import.meta.url),
        "utf8",
    );
    const kitRoot = kitCss.match(/:root\s*\{([^}]*)\}/)?.[1] ?? "";
    const kitColorTokens = [...kitRoot.matchAll(/(--[a-z0-9-]+)\s*:/gi)]
        .map(([, name]) => name)
        .filter(
            (name) =>
                !name.startsWith("--font-") &&
                name !== "--radius" &&
                name !== "--radius-sm",
        )
        .sort();
    assert.deepEqual([...REPORT_KIT_COLOR_TOKEN_NAMES].sort(), kitColorTokens);

    const css = [
        readFileSync(new URL("../index.css", import.meta.url), "utf8"),
        readFileSync(new URL("./themes.css", import.meta.url), "utf8"),
    ]
        .join("\n")
        .replace(/\/\*[\s\S]*?\*\//g, "");
    const rules = [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map(
        ([, selectors = "", body = ""]) => ({
            selectors: selectors.split(",").map((selector) => selector.trim()),
            declarations: new Map(
                [...body.matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/gi)].map(
                    ([, name, value]) => [name, value.trim()],
                ),
            ),
        }),
    );

    for (const theme of THEMES) {
        for (const appearance of ["light", "dark"]) {
            const selectors = new Set([":root", ".studio"]);
            if (appearance === "dark")
                selectors.add('.studio[data-appearance="dark"]');
            selectors.add(`.studio[data-palette="${theme.id}"]`);
            if (appearance === "dark")
                selectors.add(
                    `.studio[data-appearance="dark"][data-palette="${theme.id}"]`,
                );
            const computed = new Map<string, string>();
            for (const rule of rules)
                if (rule.selectors.some((selector) => selectors.has(selector)))
                    for (const [name, value] of rule.declarations)
                        computed.set(name, value);

            for (const token of STUDIO_THEME_TOKEN_NAMES)
                assert.ok(
                    computed.has(token),
                    `${theme.id}/${appearance} source: ${token}`,
                );
            const tokens = readReportThemeTokens(
                (name) => computed.get(name) ?? "",
            );
            assert.ok(tokens, `${theme.id}/${appearance}`);
            for (const name of STUDIO_THEME_TOKEN_NAMES)
                assert.equal(
                    tokens[name],
                    computed.get(name),
                    `${theme.id}/${appearance} source value: ${name}`,
                );
            for (const token of REPORT_KIT_COLOR_TOKEN_NAMES)
                assert.ok(
                    tokens[token],
                    `${theme.id}/${appearance} kit color: ${token}`,
                );
            assert.equal(tokens["--warn"], "#ffb547");
            assert.equal(tokens["--compare"], "var(--muted)");
            assert.equal(
                tokens["--warn-soft"],
                "color-mix(in srgb, var(--warn) 14%, var(--surface))",
            );
            assert.equal(
                tokens["--line-strong"],
                "color-mix(in srgb, var(--line) 60%, var(--ink))",
            );
            assert.notEqual(
                computed.get("--muted"),
                computed.get("--accent"),
                `${theme.id}/${appearance}: compare must remain distinct from accent`,
            );
        }
    }
});

test("every theme defines an emphasis colour that is neither red nor green", () => {
    const css = readFileSync(new URL("./themes.css", import.meta.url), "utf8");
    const values = [...css.matchAll(/--highlight:\s*(#[0-9a-f]{6})/gi)].map(
        (match) => match[1]!,
    );
    assert.equal(values.length, THEMES.length * 2);
    for (const hex of values) {
        const [r, g, b] = [1, 3, 5].map((i) =>
            parseInt(hex.slice(i, i + 2), 16),
        ) as [number, number, number];
        const max = Math.max(r, g, b),
            min = Math.min(r, g, b);
        if (max - min < 24) continue; // neutral grey (墨色極簡)
        let hue =
            max === r
                ? ((g - b) / (max - min)) * 60
                : max === g
                  ? (2 + (b - r) / (max - min)) * 60
                  : (4 + (r - g) / (max - min)) * 60;
        if (hue < 0) hue += 360;
        assert.ok(
            !(hue < 20 || hue > 340) && !(hue > 90 && hue < 150),
            `${hex} reads as gain red or loss green (hue ${hue.toFixed(0)})`,
        );
    }
});
