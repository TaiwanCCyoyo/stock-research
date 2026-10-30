import assert from "node:assert/strict";
import test from "node:test";
import { CLOSED, TIP_NAVIGATION_EVENTS, tipReducer } from "./tipState.ts";
import {
    SOURCE_CLOSED,
    sourceHandleScroll,
    sourceNextTabStop,
    sourceOpen,
    sourcePanelPosition,
    sourceReducer,
    sourceRestoreFocus,
    sourceReturnFromClose,
    sourceTabStops,
} from "./sourceInfoState.ts";

test("focus-driven outer scrolling keeps the preview and repositions it; unrelated scrolling dismisses", () => {
    const triggerNode = {},
        panelLink = {},
        input = {},
        internalScroll = {};
    const document = { activeElement: triggerNode };
    const trigger = {
        ownerDocument: document,
        contains: (node: unknown) => node === triggerNode,
    } as unknown as HTMLElement;
    const panel = {
        contains: (node: unknown) =>
            node === panelLink || node === internalScroll,
    } as unknown as HTMLElement;
    let state = sourceReducer(SOURCE_CLOSED, "focus");
    let anchor = { left: 20, top: 900, bottom: 920 };
    let place = sourcePanelPosition(
        anchor,
        { width: 200, height: 100 },
        { width: 900, height: 640 },
    );
    const reposition = () => {
        place = sourcePanelPosition(
            anchor,
            { width: 200, height: 100 },
            { width: 900, height: 640 },
        );
    };
    const dismiss = () => {
        state = sourceReducer(state, "navigate");
    };
    // Tabbing to an offscreen trigger scrolls the host after its focus event.
    anchor = { left: 20, top: 100, bottom: 120 };
    sourceHandleScroll(trigger, panel, null, reposition, dismiss);
    assert.equal(sourceOpen(state), true);
    assert.deepEqual(place, { left: 20, top: 128 });
    document.activeElement = panelLink;
    sourceHandleScroll(trigger, panel, null, reposition, dismiss);
    assert.equal(sourceOpen(state), true);
    document.activeElement = input;
    sourceHandleScroll(
        trigger,
        panel,
        internalScroll as Node,
        reposition,
        dismiss,
    );
    assert.equal(sourceOpen(state), true); // Panel's own scrollbar never dismisses.
    sourceHandleScroll(trigger, panel, null, reposition, dismiss);
    assert.equal(sourceOpen(state), false);
});

test("Shift+Tab from close cancels portal-native traversal and restores the exact trigger", () => {
    const calls: string[] = [];
    const trigger = {
        focus: (options: FocusOptions) => {
            assert.equal(options.preventScroll, true);
            calls.push("trigger-focus");
        },
    } as unknown as HTMLElement;
    const event = {
        key: "Tab",
        shiftKey: true,
        preventDefault: () => calls.push("cancel-native-tab"),
        stopPropagation: () => calls.push("stop-portal-bubble"),
    };
    assert.equal(sourceReturnFromClose(event, trigger), true);
    assert.deepEqual(calls, [
        "cancel-native-tab",
        "stop-portal-bubble",
        "trigger-focus",
    ]);
    calls.length = 0;
    assert.equal(
        sourceReturnFromClose({ ...event, shiftKey: false }, trigger),
        false,
    );
    assert.equal(
        sourceReturnFromClose({ ...event, key: "Escape" }, trigger),
        false,
    );
    assert.equal(sourceReturnFromClose(event, null), false);
    assert.deepEqual(calls, []);
});

test("portal focus bridge preserves main-page Tab order and excludes unavailable controls", () => {
    const document = {
        querySelectorAll: () => controls,
        defaultView: {
            getComputedStyle: (element: { visibility: string }) => ({
                visibility: element.visibility,
            }),
        },
    };
    const control = (
        options: {
            disabled?: boolean;
            hidden?: boolean;
            inert?: boolean;
            panel?: boolean;
            visible?: boolean;
            tabIndex?: number;
            visibility?: string;
        } = {},
    ) =>
        ({
            tabIndex: options.tabIndex ?? 0,
            visibility: options.visibility ?? "visible",
            ownerDocument: document,
            matches: () => options.disabled ?? false,
            closest: (selector: string) =>
                selector === ".u-source-panel"
                    ? options.panel
                    : options.hidden || options.inert,
            getClientRects: () => (options.visible === false ? [] : [{}]),
        }) as unknown as HTMLElement;
    const before = control(),
        trigger = control(),
        nextInput = control(),
        nextLink = control();
    const close = control({ panel: true }),
        panelLink = control({ panel: true });
    const controls = [
        before,
        trigger,
        control({ disabled: true }),
        control({ hidden: true }),
        control({ inert: true }),
        control({ visible: false }),
        control({ tabIndex: -1 }),
        control({ visibility: "hidden" }),
        nextInput,
        nextLink,
        close,
        panelLink,
    ];
    assert.deepEqual(sourceTabStops(document as unknown as Document, true), [
        before,
        trigger,
        nextInput,
        nextLink,
    ]);
    assert.equal(sourceNextTabStop(trigger), nextInput);
    assert.equal(sourceNextTabStop(nextInput), nextLink);
    assert.equal(sourceNextTabStop(nextLink), null); // Caller returns to trigger; the following Tab is native.
    const panel = {
        querySelectorAll: () => [close, panelLink],
    } as unknown as HTMLElement;
    assert.deepEqual(sourceTabStops(panel), [close, panelLink]); // Native forward/reverse traversal inside the panel.
});

test("Escape restores only a panel's own keyboard focus, leaving hovered input focus alone", () => {
    const input = {},
        link = {};
    let focused = 0;
    const document = { activeElement: input };
    const panel = {
        ownerDocument: document,
        contains: (node: unknown) => node === link,
    } as unknown as HTMLElement;
    const trigger = {
        focus: () => {
            focused++;
        },
    } as unknown as HTMLElement;
    assert.equal(sourceRestoreFocus(panel, trigger), false);
    assert.equal(focused, 0);
    document.activeElement = link;
    assert.equal(sourceRestoreFocus(panel, trigger), true);
    assert.equal(focused, 1);
    assert.equal(sourceRestoreFocus(null, trigger), false);
});

const sourceRun = (...events: Parameters<typeof sourceReducer>[1][]) =>
    events.reduce(sourceReducer, SOURCE_CLOSED);

test("source preview bridges trigger and panel, and preserves focused links", () => {
    assert.equal(sourceOpen(sourceRun("enter")), true);
    assert.equal(sourceOpen(sourceRun("enter", "leave", "enter")), true);
    assert.equal(sourceOpen(sourceRun("focus", "enter", "leave")), true);
    assert.equal(sourceOpen(sourceRun("enter", "focus", "blur")), true);
    assert.equal(
        sourceOpen(sourceRun("enter", "focus", "leave", "blur")),
        false,
    );
});

test("first tap or Enter pins even after focus preview; second activation closes", () => {
    for (const preview of [[], ["focus"], ["enter", "focus"]] as const) {
        const pinned = sourceRun(...preview, "toggle");
        assert.equal(pinned.pinned, true);
        assert.equal(
            sourceOpen(sourceReducer(sourceReducer(pinned, "blur"), "leave")),
            true,
        );
        assert.equal(sourceOpen(sourceReducer(pinned, "toggle")), false);
    }
});

test("Escape can return focus without reopening; fresh entry and route cleanup work", () => {
    const escaped = sourceRun("focus", "toggle", "escape", "focus");
    assert.equal(sourceOpen(escaped), false);
    assert.equal(sourceOpen(sourceReducer(escaped, "enter")), true);
    assert.equal(
        sourceOpen(sourceReducer(sourceReducer(escaped, "blur"), "focus")),
        true,
    );
    for (const close of ["outside", "navigate"] as const)
        assert.equal(
            sourceOpen(sourceRun("enter", "focus", "toggle", close)),
            false,
        );
});

test("source panel placement stays within narrow viewport and uses space above", () => {
    assert.deepEqual(
        sourcePanelPosition(
            { left: 370, top: 500, bottom: 520 },
            { width: 366, height: 300 },
            { width: 390, height: 640 },
        ),
        { left: 12, top: 192 },
    );
    assert.deepEqual(
        sourcePanelPosition(
            { left: 20, top: 30, bottom: 50 },
            { width: 200, height: 100 },
            { width: 900, height: 640 },
        ),
        { left: 20, top: 58 },
    );
});

const run = (...events: Parameters<typeof tipReducer>[1][]) =>
    events.reduce(tipReducer, CLOSED);

test("a keyboard-pinned tip closes on hash, back and forward navigation", () => {
    // Focus, then Enter (a click on the button) pins it.
    const pinned = run("focus", "toggle");
    assert.deepEqual(pinned, { open: true, pinned: true });
    assert.deepEqual(tipReducer(pinned, "blur"), pinned);
    assert.deepEqual(tipReducer(pinned, "navigate"), CLOSED);
    assert.deepEqual([...TIP_NAVIGATION_EVENTS], ["hashchange", "popstate"]);
});

test("hover and focus preview without pinning; Escape and outside close", () => {
    assert.deepEqual(run("enter", "leave"), CLOSED);
    assert.deepEqual(run("focus", "blur"), CLOSED);
    assert.deepEqual(run("enter", "toggle", "leave"), {
        open: true,
        pinned: true,
    });
    assert.deepEqual(run("enter", "toggle", "toggle"), CLOSED);
    assert.deepEqual(run("focus", "toggle", "escape"), CLOSED);
    assert.deepEqual(run("focus", "toggle", "outside"), CLOSED);
});
