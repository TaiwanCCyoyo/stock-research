import assert from "node:assert/strict";
import test from "node:test";
import { LayoutCache, layoutKey } from "./layoutCache.ts";

const node = (id: string, groupId = "g", weight = 1) => ({
    id,
    groupId,
    weight,
});
const key = (nodes = [node("a"), node("b")], over = {}) =>
    layoutKey({
        date: "2020-01-02",
        aspectKey: 2,
        radiusScale: 30,
        nodes,
        ...over,
    });

test("evicts the least recently used entry beyond capacity", () => {
    const cache = new LayoutCache<number>(3);
    cache.set("a", 1);
    cache.set("b", 2);
    cache.set("c", 3);
    assert.equal(cache.get("a"), 1);
    cache.set("d", 4);
    assert.equal(cache.get("b"), undefined);
    assert.equal(cache.get("a"), 1);
    assert.equal(cache.size, 3);
});

test("setting an existing key replaces it without growing", () => {
    const cache = new LayoutCache<number>(2);
    cache.set("a", 1);
    cache.set("a", 2);
    assert.equal(cache.size, 1);
    assert.equal(cache.get("a"), 2);
});

test("a heavy entry pushes out older ones but the newest always stays", () => {
    const cache = new LayoutCache<number>(10, 100, (value) => value);
    cache.set("a", 40);
    cache.set("b", 40);
    cache.set("c", 40);
    assert.equal(cache.get("a"), undefined);
    assert.equal(cache.get("b"), 40);
    cache.set("huge", 500);
    assert.equal(cache.size, 1);
    assert.equal(cache.get("huge"), 500);
});

test("the key changes with date, frame shape, scale and any stock detail", () => {
    const base = key();
    assert.equal(key(), base);
    assert.notEqual(key(undefined, { date: "2020-01-03" }), base);
    assert.notEqual(key(undefined, { aspectKey: 3 }), base);
    assert.notEqual(key(undefined, { radiusScale: 20 }), base);
    assert.notEqual(key([node("a"), node("c")]), base);
    assert.notEqual(key([node("a"), node("b", "other")]), base);
    assert.notEqual(key([node("a"), node("b", "g", 1.5)]), base);
    assert.notEqual(key([node("a")]), base);
});
