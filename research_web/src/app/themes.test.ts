import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { reportPalette, themeId, THEMES } from "./themes.ts";

test("saved palette ids keep working and unknown ids fall back", () => {
    for (const id of ["forest", "ocean", "plum", "sand"])
        assert.equal(themeId(id), id);
    assert.equal(themeId("sakura"), "sakura");
    assert.equal(themeId("neon"), "forest");
    assert.equal(themeId(null), "forest");
});

test("web reports only receive palettes report-kit v1 understands", () => {
    for (const theme of THEMES)
        assert.ok(
            ["forest", "ocean", "plum", "sand"].includes(
                reportPalette(theme.id),
            ),
        );
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
