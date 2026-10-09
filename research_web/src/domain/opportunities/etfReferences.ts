import type {
    OpportunityBundle,
    OpportunityPortfolio,
    SourceRef,
} from "./types.ts";

/** Dated research references, never inferred historical holdings or performance. */
const REFERENCES = [
    [
        "0050",
        "元大台灣50",
        "tw-etf",
        "臺灣50指數的大型股基準。",
        "https://www.yuantaetfs.com/product/detail/0050/Basic_information",
    ],
    [
        "0052",
        "富邦科技",
        "tw-etf",
        "臺灣科技產業指數型基金；方法與持股摘錄見 ETF 圖鑑。",
        "https://websys.fsit.com.tw/FubonETF/Fund/IndexIntro.aspx?stkId=0052",
    ],
    [
        "00981A",
        "主動統一台股增長",
        "tw-etf",
        "主動台股基金；完整歷史決策規則沒有公開。",
        "https://www.ezmoney.com.tw/events/2025TGA/00981A-DM.pdf",
    ],
    [
        "VOO",
        "Vanguard S&P 500 ETF",
        "us-etf",
        "美國大型股基準；不使用台灣個股目錄評斷美國市場機會。",
        "https://www.spglobal.com/spdji/en/indices/equity/sp-500/",
    ],
    [
        "QQQM",
        "Invesco NASDAQ 100 ETF",
        "us-etf",
        "Nasdaq-100 方法參考；須有美股目錄才能進行適當比較。",
        "https://indexes.nasdaq.com/docs/Methodology_NDX.pdf",
    ],
    [
        "SMH",
        "VanEck Semiconductor ETF",
        "us-etf",
        "美國版半導體基金；ADR 與台灣普通股不能直接視為相同證券。",
        "https://www.marketvector.com/rulebooks/download/MVSMH_Index_Guide.pdf",
    ],
] as const;

export function withEtfReferences(
    bundle: OpportunityBundle,
): OpportunityBundle {
    const sources: SourceRef[] = REFERENCES.map(([symbol, , , , url]) => ({
        id: `etf-reference:${symbol}`,
        label: `${symbol} · 2026-10-01 已保存方法摘錄，完整來源與持股日期見 ETF 圖鑑`,
        url,
        path: "docs/zh-TW/etf-benchmark-research.md",
    }));
    const portfolios: OpportunityPortfolio[] = REFERENCES.map(
        ([symbol, name, kind, description]) => ({
            id: `etf:${symbol}`,
            name: `${symbol} ${name}`,
            kind,
            description,
            sourceIds: [`etf-reference:${symbol}`],
            coverage: [],
            holdings: [],
            allocations: [],
            limitations: [
                "這是已保存的基金方法參考，不是最佳績效排行或最新持股。",
                "尚未取得可核對的逐日完整持股與資產配置；這一天持股未知，不能視為沒有持有。",
                ...(kind === "us-etf"
                    ? [
                          "台灣個股案例與美國基金的市場、幣別及證券範圍不同，目前不適合比較機會捕捉。",
                      ]
                    : []),
            ],
        }),
    );
    return {
        ...bundle,
        sources: [...bundle.sources, ...sources],
        portfolios: [...bundle.portfolios, ...portfolios],
    };
}
