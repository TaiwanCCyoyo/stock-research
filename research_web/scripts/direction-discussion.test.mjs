import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const source = await readFile(
    new URL("../discussion-kit/v1/discussion.js", import.meta.url),
    "utf8",
);
const page = await readFile(
    new URL("../discussion-kit/v1/index.html", import.meta.url),
    "utf8",
);
const context = vm.createContext({});
vm.runInContext(source, context);
const kit = context.DirectionDiscussion;
const example = JSON.parse(
    page.match(
        /<script id="discussion-data" type="application\/json">([\s\S]*?)<\/script>/,
    )[1],
);
const copy = (value) => JSON.parse(JSON.stringify(value));

test("the standalone example is valid and has no implicit owner selections", () => {
    kit.validateModel(example);
    const session = kit.createSession(example);
    assert.equal(session.exportFeedback().status, "proposed");
    assert.equal(session.exportFeedback().source.revision, "demo-v1");
    assert.ok(
        session
            .exportFeedback()
            .selections.every((item) => item.optionId === null),
    );
});

test("selections remain proposals and reject choices outside the current model", () => {
    const session = kit.createSession(example);
    session.select("C1", "exit-comparison");
    const feedback = session.exportFeedback();
    assert.equal(feedback.status, "proposed");
    assert.equal(feedback.selections[0].optionId, "exit-comparison");
    assert.equal("fake_headline_approved" in feedback, false);
    assert.equal("stage" in feedback, false);
    assert.throws(() => session.select("C9", "exit-comparison"));
    assert.throws(() => session.select("C1", "all-primary"));
    session.select("C1", null);
    assert.equal(session.exportFeedback().selections[0].optionId, null);
});

test("model and exported objects cannot mutate the session source or decisions", () => {
    const model = copy(example);
    const session = kit.createSession(model);
    model.source.revision = "changed-by-caller";
    const exported = session.exportFeedback();
    exported.source.revision = "changed-export";
    exported.selections[0].optionId = "exit-comparison";
    assert.equal(session.exportFeedback().source.revision, "demo-v1");
    assert.equal(session.exportFeedback().selections[0].optionId, null);
});

test("new revision starts unanswered and rejects old feedback when formatting", () => {
    const first = kit.createSession(example);
    first.select("C1", "exit-comparison");
    first.setNotes("原版本備註");
    const newer = copy(example);
    newer.source.revision = "demo-v2";
    const second = kit.createSession(newer);
    assert.equal(second.exportFeedback().notes, "");
    assert.ok(
        second
            .exportFeedback()
            .selections.every((item) => item.optionId === null),
    );
    assert.throws(
        () => kit.toMarkdown(newer, first.exportFeedback()),
        /版本不同/,
    );
});

test("feedback retains multiline notes without turning them into approval markup", () => {
    const session = kit.createSession(example);
    const notes =
        "想先釐清分母\n# approved\n<script>alert('x')</script>\n[同意](https://example.invalid)";
    session.setNotes(notes);
    session.select("C2", "two-primary");
    const result = session.exportFeedback();
    assert.equal(result.notes, notes);
    const markdown = kit.toMarkdown(example, result);
    assert.ok(markdown.includes("尚未選擇"));
    assert.ok(markdown.includes("> \\# approved"));
    assert.ok(markdown.includes("&lt;script&gt;"));
    assert.ok(markdown.includes("> \\[同意\\]"));
    assert.ok(!markdown.includes("<script>"));
    assert.ok(markdown.includes("尚未確認方向，也未授權市場計算"));
});

test("malformed models fail rather than silently losing discussion identity", () => {
    const variants = [
        (model) => {
            model.source.revision = "";
        },
        (model) => {
            model.choices[1].id = "C1";
        },
        (model) => {
            model.choices[0].options[1].id = model.choices[0].options[0].id;
        },
        (model) => {
            model.outcomes[1].id = "supports";
        },
        (model) => {
            model.outcomes[0].headline = "真實結果為 42%。";
        },
        (model) => {
            model.questions[0].reference = "Q1";
        },
    ];
    for (const change of variants) {
        const model = copy(example);
        change(model);
        assert.throws(() => kit.validateModel(model));
    }
});

test("feedback formatting rejects forged approval, missing decisions and unknown IDs", () => {
    const session = kit.createSession(example);
    const valid = copy(session.exportFeedback());
    assert.throws(() =>
        kit.toMarkdown(example, { ...valid, status: "agreed" }),
    );
    assert.throws(() => kit.toMarkdown(example, { ...valid, selections: [] }));
    const forged = copy(valid);
    forged.selections[0].optionId = "not-an-option";
    assert.throws(() => kit.toMarkdown(example, forged));
    forged.selections = [valid.selections[0], valid.selections[0]];
    assert.throws(() => kit.toMarkdown(example, forged));
});

// Small DOM harness for mount lifecycle and text-node behavior. Browser layout is tested separately.
class Element {
    constructor(tag, document) {
        this.tagName = tag;
        this.ownerDocument = document;
        this.children = [];
        this.attributes = new Map();
        this.listeners = new Map();
        this._text = "";
        this.value = "";
    }
    set textContent(value) {
        this._text = String(value);
        this.children = [];
    }
    get textContent() {
        return (
            this._text +
            this.children.map((child) => child.textContent).join("")
        );
    }
    set innerHTML(_) {
        throw new Error("Untrusted HTML rendering is forbidden");
    }
    append(...children) {
        children.forEach((child) => {
            child.parent = this;
            this.children.push(child);
        });
    }
    replaceChildren(...children) {
        this.children.forEach((child) => {
            child.parent = null;
        });
        this.children = [];
        this._text = "";
        this.append(...children);
    }
    setAttribute(key, value) {
        this.attributes.set(key, value);
    }
    getAttribute(key) {
        return this.attributes.get(key);
    }
    addEventListener(type, callback) {
        if (!this.listeners.has(type)) this.listeners.set(type, new Set());
        this.listeners.get(type).add(callback);
    }
    removeEventListener(type, callback) {
        this.listeners.get(type)?.delete(callback);
    }
    dispatch(type) {
        for (const callback of this.listeners.get(type) || []) callback();
    }
    remove() {
        if (this.parent)
            this.parent.children = this.parent.children.filter(
                (child) => child !== this,
            );
        this.parent = null;
    }
    focus() {
        this.ownerDocument.activeElement = this;
    }
    select() {
        this.selected = true;
    }
    query(predicate) {
        if (predicate(this)) return this;
        for (const child of this.children) {
            const result = child.query(predicate);
            if (result) return result;
        }
        return null;
    }
}
function dom() {
    const document = { defaultView: { navigator: {} } };
    document.createElement = (tag) => new Element(tag, document);
    return document.createElement("main");
}

test("mount updates discussion, keeps outcomes exploratory, and remount removes old listeners", () => {
    const root = dom();
    const first = kit.mount(root, example);
    const option = root.query(
        (node) =>
            node.tagName === "button" &&
            node.textContent.includes("進一步比較"),
    );
    option.dispatch("click");
    assert.equal(
        first.exportFeedback().selections[0].optionId,
        "exit-comparison",
    );
    assert.equal(option.getAttribute("aria-pressed"), "true");
    const branch = root.query(
        (node) =>
            node.tagName === "button" && node.textContent === "如果分不出來",
    );
    branch.dispatch("click");
    assert.ok(root.textContent.includes("目前還分不出訊號是否有用"));
    assert.equal("outcome" in first.exportFeedback(), false);
    const newer = copy(example);
    newer.source.revision = "demo-v2";
    const second = kit.mount(root, newer);
    assert.equal(option.listeners.get("click").size, 0);
    assert.equal(branch.listeners.get("click").size, 0);
    assert.equal(second.exportFeedback().source.revision, "demo-v2");
    assert.ok(
        second
            .exportFeedback()
            .selections.every((item) => item.optionId === null),
    );
    assert.equal(root.children.length, 1);
    second.destroy();
    assert.equal(root.children.length, 0);
});

test("mount uses text content for model strings and shows errors for invalid models", () => {
    const root = dom();
    const hostile = copy(example);
    hostile.ownerPurpose = "<img src=x onerror=alert(1)>";
    kit.mount(root, hostile);
    assert.ok(root.textContent.includes(hostile.ownerPurpose));
    assert.equal(
        root.query((node) => node.tagName === "img"),
        null,
    );
    const invalid = copy(example);
    invalid.source.revision = "";
    const failed = kit.mount(root, invalid);
    assert.ok(root.textContent.includes("暫時無法開啟討論"));
    assert.ok(root.query((node) => node.getAttribute("role") === "alert"));
    kit.mount(root, example);
    failed.destroy();
    assert.ok(root.textContent.includes("一起把研究方向說清楚"));
});

test("visible export follows edited choices and notes without submitting anything", () => {
    const root = dom();
    kit.mount(root, example);
    root.query(
        (node) =>
            node.tagName === "button" && node.textContent === "整理我的想法",
    ).dispatch("click");
    const output = root.query((node) => node.className === "dd-export");
    assert.ok(output.value.includes("尚未選擇"));
    const notes = root.query((node) => node.className === "dd-notes");
    notes.value = "我想比較實際出場後的差別。";
    notes.dispatch("input");
    assert.ok(output.value.includes(notes.value));
    root.query(
        (node) =>
            node.tagName === "button" &&
            node.textContent.includes("進一步比較"),
    ).dispatch("click");
    assert.ok(output.value.includes("進一步比較停損後報酬與回撤"));
    assert.ok(output.value.includes("尚未確認方向，也未授權市場計算"));
});

test("JSON download carries the proposed feedback and releases blob URLs on destroy", () => {
    const root = dom();
    const document = root.ownerDocument;
    const blobs = new Map();
    const clicked = [];
    const revoked = [];
    document.defaultView.Blob = class {
        constructor(parts, options) {
            this.text = parts.join("");
            this.type = options.type;
        }
    };
    document.defaultView.URL = {
        createObjectURL(blob) {
            const url = `blob:discussion-${blobs.size + 1}`;
            blobs.set(url, blob);
            return url;
        },
        revokeObjectURL(url) {
            revoked.push(url);
        },
    };
    const createElement = document.createElement;
    document.createElement = (tag) => {
        const node = createElement(tag);
        if (tag === "a") {
            node.click = () => {
                assert.ok(
                    node.parent,
                    "download anchor must be attached when clicked",
                );
                clicked.push({ href: node.href, filename: node.download });
            };
        }
        return node;
    };

    const api = kit.mount(root, example);
    const notes = root.query((node) => node.className === "dd-notes");
    notes.value = "先保留所有選擇\n想討論停損後的差別。";
    notes.dispatch("input");
    const download = root.query(
        (node) =>
            node.tagName === "button" &&
            node.textContent === "下載選擇紀錄 JSON",
    );
    download.dispatch("click");
    download.dispatch("click");

    assert.equal(clicked.length, 2);
    for (const { href, filename } of clicked) {
        assert.equal(filename, "direction-feedback.json");
        const blob = blobs.get(href);
        assert.equal(blob.type, "application/json;charset=utf-8");
        const feedback = JSON.parse(blob.text);
        assert.equal(feedback.schema, "direction-feedback.v1");
        assert.equal(feedback.status, "proposed");
        assert.deepEqual(feedback.source, example.source);
        assert.equal(feedback.source.revision, "demo-v1");
        assert.equal(feedback.notes, notes.value);
        assert.deepEqual(feedback.selections, [
            { choiceId: "C1", optionId: null },
            { choiceId: "C2", optionId: null },
        ]);
    }
    assert.equal(
        root.query((node) => node.tagName === "a"),
        null,
    );
    assert.deepEqual(revoked, []);
    api.destroy();
    assert.deepEqual(revoked, Array.from(blobs.keys()));
    api.destroy();
    assert.equal(revoked.length, 2, "destroy is idempotent");
});
