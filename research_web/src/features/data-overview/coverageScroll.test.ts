import assert from "node:assert/strict";
import test from "node:test";
import {
    restoreCoverageScroll,
    type CoverageScrollAdapter,
} from "./coverageScroll.ts";

class MemoryStorage {
    values = new Map<string, string>();
    getItem(key: string) {
        return this.values.get(key) ?? null;
    }
    setItem(key: string, value: string) {
        this.values.set(key, value);
    }
}

class FakeWindow extends EventTarget {
    scrollY = 0;
    scrollTo(options: ScrollToOptions) {
        this.scrollY = Number(options.top ?? 0);
        this.dispatchEvent(new Event("scroll"));
    }
}

class FakeTable extends EventTarget {
    isConnected = true;
    scrollTop = 0;
    scrollLeft = 0;
}

function makeAdapter() {
    const storage = new MemoryStorage();
    const fakeWindow = new FakeWindow();
    const table = new FakeTable();
    let currentTable = table;
    const frames = new Map<number, FrameRequestCallback>();
    let nextFrame = 1;
    const adapter: CoverageScrollAdapter = {
        storage,
        window: fakeWindow as unknown as CoverageScrollAdapter["window"],
        table: () => currentTable as unknown as HTMLElement,
        requestFrame: ((callback: FrameRequestCallback) => {
            const id = nextFrame++;
            frames.set(id, callback);
            return id;
        }) as typeof requestAnimationFrame,
        cancelFrame: ((id: number) =>
            frames.delete(id)) as typeof cancelAnimationFrame,
    };
    return {
        adapter,
        storage,
        fakeWindow,
        table,
        replaceTable(next: FakeTable) {
            currentTable = next;
        },
        runNextFrame() {
            const entry = frames.entries().next().value as
                [number, FrameRequestCallback] | undefined;
            if (!entry) return false;
            frames.delete(entry[0]);
            entry[1](0);
            return true;
        },
        get pendingFrames() {
            return frames.size;
        },
    };
}

test("restore gates native/window scroll events and keeps matrix coordinates intact", () => {
    const key =
        "kind=&status=all&q=SCROLL&page=2&dataset=institutional&mark=partial";
    const harness = makeAdapter();
    harness.storage.setItem(`coverage-scroll:${key}`, "283");
    harness.storage.setItem(
        `coverage-table-scroll:${key}`,
        JSON.stringify({ top: 2797, left: 33 }),
    );

    const cleanup = restoreCoverageScroll(key, harness.adapter);
    // A browser may restore the outer page while the layout frame is pending.
    harness.fakeWindow.scrollY = 0;
    harness.fakeWindow.dispatchEvent(new Event("scroll"));
    assert.equal(harness.storage.getItem(`coverage-scroll:${key}`), "283");
    assert.equal(
        harness.storage.getItem(`coverage-table-scroll:${key}`),
        JSON.stringify({ top: 2797, left: 33 }),
    );

    assert.equal(harness.runNextFrame(), true);
    assert.equal(harness.fakeWindow.scrollY, 283);
    assert.equal(harness.table.scrollTop, 2797);
    assert.equal(harness.table.scrollLeft, 33);
    // A synchronous scroll event from scrollTo remains gated until next paint.
    assert.equal(harness.storage.getItem(`coverage-scroll:${key}`), "283");
    assert.equal(
        harness.storage.getItem(`coverage-table-scroll:${key}`),
        JSON.stringify({ top: 2797, left: 33 }),
    );
    assert.equal(harness.runNextFrame(), true);

    harness.fakeWindow.scrollY = 501;
    harness.fakeWindow.dispatchEvent(new Event("scroll"));
    assert.equal(harness.storage.getItem(`coverage-scroll:${key}`), "501");
    assert.equal(
        harness.storage.getItem(`coverage-table-scroll:${key}`),
        JSON.stringify({ top: 2797, left: 33 }),
    );

    harness.table.isConnected = false;
    harness.table.scrollTop = 0;
    harness.table.dispatchEvent(new Event("scroll"));
    harness.fakeWindow.scrollY = 99;
    harness.fakeWindow.dispatchEvent(new Event("scroll"));
    assert.equal(harness.storage.getItem(`coverage-scroll:${key}`), "501");
    assert.equal(
        harness.storage.getItem(`coverage-table-scroll:${key}`),
        JSON.stringify({ top: 2797, left: 33 }),
    );

    const replacement = new FakeTable();
    harness.replaceTable(replacement);
    harness.table.isConnected = true;
    harness.table.scrollTop = 777;
    harness.table.dispatchEvent(new Event("scroll"));
    replacement.scrollTop = 123;
    replacement.dispatchEvent(new Event("scroll"));
    harness.fakeWindow.scrollY = 123;
    harness.fakeWindow.dispatchEvent(new Event("scroll"));
    assert.equal(harness.storage.getItem(`coverage-scroll:${key}`), "501");
    assert.equal(
        harness.storage.getItem(`coverage-table-scroll:${key}`),
        JSON.stringify({ top: 2797, left: 33 }),
    );

    cleanup();
    harness.fakeWindow.scrollY = 10;
    harness.fakeWindow.dispatchEvent(new Event("scroll"));
    replacement.scrollTop = 10;
    replacement.dispatchEvent(new Event("scroll"));
    assert.equal(harness.storage.getItem(`coverage-scroll:${key}`), "501");
    assert.equal(
        harness.storage.getItem(`coverage-table-scroll:${key}`),
        JSON.stringify({ top: 2797, left: 33 }),
    );
});

test("cleanup cancels a pending restore frame", () => {
    const harness = makeAdapter();
    const cleanup = restoreCoverageScroll("q=cancel", harness.adapter);
    cleanup();
    assert.equal(harness.pendingFrames, 0);
    assert.equal(harness.runNextFrame(), false);
});
