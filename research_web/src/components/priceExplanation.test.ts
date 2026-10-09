import assert from "node:assert/strict";
import test from "node:test";
import { priceExplanation, priceSummary } from "./priceExplanation.ts";

test("adjustment and dividend assumptions are only applied to recognized price bases", () => {
    const known =
        "raw: official price_daily.parquet Close, unadjusted; adjusted: Raw Close multiplied by subsequent valid permanent corporate-action price factors; cash dividends are not reinvested";
    assert.match(priceExplanation(known), /公司行動/);
    assert.match(priceExplanation(known), /不含股息再投入/);
    assert.match(priceExplanation("adjusted close"), /股息是否再投入尚未確認/);
    assert.match(priceExplanation("合成 raw/adjusted 價格"), /模擬價格/);
    assert.match(
        priceExplanation("raw: private/history.parquet; dividends included"),
        /尚待確認/,
    );
    assert.doesNotMatch(priceExplanation(known), /parquet|raw:|Close/);
    assert.match(priceSummary(known), /不含股息再投入/);
    const savedHistory = "收盤價經已記錄的公司行動調整；不含股息再投資";
    assert.match(priceSummary(savedHistory), /調整後收盤價/);
    assert.match(priceExplanation(savedHistory), /不含股息再投入/);
    for (const unknown of ["raw close", "total return", "unknown"]) {
        assert.match(priceSummary(unknown), /待確認/);
        assert.doesNotMatch(priceSummary(unknown), /調整後|不含股息/);
        assert.match(priceExplanation(unknown), /待確認/);
    }
});
