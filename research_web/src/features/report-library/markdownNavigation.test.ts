import assert from "node:assert/strict";
import test from "node:test";
import {
    headingSlug,
    imageUnavailableLabel,
    markdownFragmentId,
    markdownHeadingIds,
    scrollMarkdownFragment,
} from "./markdownNavigation.ts";

test("headings use stable Unicode IDs and collision-safe duplicate suffixes", () => {
    const headings = ["研究 結論", "研究 結論", "研究 結論-1", "研究 結論"].map(
        (value) => ({
            type: "element",
            tagName: "h2",
            properties: {} as Record<string, unknown>,
            children: [{ type: "text", value }],
        }),
    );
    const tree = { type: "root", children: headings };
    markdownHeadingIds({ prefix: "edition-" })(tree);
    assert.deepEqual(
        headings.map((h) => h.properties.id),
        [
            "edition-研究-結論",
            "edition-研究-結論-1",
            "edition-研究-結論-1-1",
            "edition-研究-結論-2",
        ],
    );
    markdownHeadingIds({ prefix: "edition-" })(tree);
    assert.equal(headings[1]?.properties.id, "edition-研究-結論-1");
    assert.equal(headingSlug("**Results** & Limits!"), "results--limits");
});

test("fragment lookup is bounded, decoded safely and confined to the document prefix", () => {
    assert.equal(
        markdownFragmentId("#%E7%B5%90%E8%AB%96", "source-"),
        "source-結論",
    );
    for (const href of [
        undefined,
        "#",
        "#%",
        "#%00",
        "https://example.com/#a",
        "javascript:alert(1)",
        "#" + "a".repeat(4096),
    ]) {
        assert.equal(markdownFragmentId(href, "edition-"), null);
    }
});

test("local navigation scrolls and focuses only its target without changing routing", () => {
    const seen: string[] = [];
    assert.equal(
        scrollMarkdownFragment("#result", "edition-", (id) => {
            seen.push(id);
            return {
                scrollIntoView: () => seen.push("scroll"),
                focus: (options) => {
                    assert.equal(options.preventScroll, true);
                    seen.push("focus");
                },
            };
        }),
        true,
    );
    assert.deepEqual(seen, ["edition-result", "scroll", "focus"]);
    assert.equal(
        scrollMarkdownFragment("#missing", "source-", () => null),
        false,
    );
});

test("image placeholders truthfully disclose the same limitation in both panes", () => {
    assert.match(
        imageUnavailableLabel("報酬圖"),
        /圖像：報酬圖.*不顯示圖片.*來源原文/,
    );
    assert.match(imageUnavailableLabel(undefined), /^原文圖像/);
    assert.doesNotMatch(imageUnavailableLabel("圖"), /請參閱來源/);
});
