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
