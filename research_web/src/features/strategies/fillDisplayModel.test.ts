import assert from "node:assert/strict";
import { test } from "node:test";
import { money } from "./format.ts";
import { transactionCost } from "./fillDisplayModel.ts";

test("recorded zero and nonzero costs always take priority over event defaults", () => {
    for (const action of [
        "DIVIDEND",
        "DIVIDEND_ENTITLEMENT",
        "BUY",
        "SELL",
        "SPLIT",
        "unknown",
    ]) {
        for (const value of [0, 12.35, -2.5, 10001]) {
            assert.equal(transactionCost(value, action), money(value, true));
            assert.notEqual(transactionCost(value, action), "—");
        }
    }
});

test("only recognized dividend accounting events have absent transaction costs marked inapplicable", () => {
    for (const value of [null, undefined]) {
        assert.equal(transactionCost(value, "DIVIDEND"), "—");
        assert.equal(transactionCost(value, "DIVIDEND_ENTITLEMENT"), "—");
        for (const action of [
            "BUY",
            "SELL",
            "SPLIT",
            "CAPITAL_REDUCTION",
            "unknown",
            "dividend",
            "",
        ]) {
            assert.equal(transactionCost(value, action), "未知");
        }
    }
});

test("invalid recorded amounts are unknown even on dividends", () => {
    for (const action of [
        "DIVIDEND",
        "DIVIDEND_ENTITLEMENT",
        "BUY",
        "SELL",
        "unknown",
    ]) {
        for (const value of [NaN, Infinity, -Infinity]) {
            assert.equal(transactionCost(value, action), "未知");
        }
    }
});
