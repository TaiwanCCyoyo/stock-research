import assert from "node:assert/strict";
import { test } from "node:test";
import {
    currencyMoney,
    gainClass,
    money,
    percentage,
    ratio,
} from "./format.ts";
import { strategyTitle } from "./presentation.ts";

test("TWD keeps compact display and requested precise amounts", () => {
    for (const value of [0, 5000, 4968993.15, -100000]) {
        assert.equal(currencyMoney(value, "TWD"), money(value));
        assert.equal(currencyMoney(value, "TWD", true), money(value, true));
    }
});

test("foreign account values retain their currency without converting units", () => {
    assert.equal(currencyMoney(1200000.25, "USD"), "USD 1,200,000.25");
    assert.equal(currencyMoney(-10000, "EUR"), "EUR -10,000");
});

test("missing or invalid amounts stay unknown in every currency", () => {
    for (const value of [null, undefined, NaN, Infinity]) {
        assert.equal(currencyMoney(value, "USD"), money(value));
        assert.notEqual(currencyMoney(value, "USD"), currencyMoney(0, "USD"));
    }
});

test("ratios have no positive sign while actual returns remain signed", () => {
    assert.equal(ratio(0.281), "28.1%");
    assert.equal(percentage(0.281), "+28.1%");
    assert.equal(ratio(0.281, 2), "28.10%");
    assert.equal(ratio(-0.281), "−28.1%");
    assert.equal(ratio(0), "0.0%");
    assert.equal(ratio(-0), "0.0%");
    assert.equal(percentage(0), "0.0%");
});

test("unknown and nonfinite ratios and returns stay unknown and neutral", () => {
    for (const value of [null, undefined, NaN, Infinity, -Infinity]) {
        assert.equal(ratio(value), "未知");
        assert.equal(percentage(value), "未知");
        assert.equal(gainClass(value), "");
    }
    assert.equal(gainClass(0), "");
    assert.equal(gainClass(0.1), "ss-gain");
    assert.equal(gainClass(-0.1), "ss-loss");
});

test("known strategy ids use distinct short names without changing the saved name", () => {
    const normal = {
        id: "stock:20261002-add-retry:normal-v1",
        plainTitle: "long title",
        name: "original name",
    };
    const cap = { ...normal, id: "stock:20261002-entry-extension-cap:cap-v1" };
    assert.equal(strategyTitle(normal), "小量試單、漲了再加碼");
    assert.equal(strategyTitle(cap), "小量試單，避免追高");
    assert.equal(normal.name, "original name");
    assert.equal(cap.plainTitle, "long title");
});

test("unknown and prototype-property strategy ids fall back to supplied titles", () => {
    for (const id of ["unknown", "constructor", "__proto__", "toString"]) {
        assert.equal(
            strategyTitle({
                id,
                plainTitle: "fallback title",
                name: "original name",
            }),
            "fallback title",
        );
        assert.equal(
            strategyTitle({ id, plainTitle: "", name: "original name" }),
            "original name",
        );
    }
});
