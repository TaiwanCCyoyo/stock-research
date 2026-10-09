import { useMemo, useState } from "react";
import "./FundsPage.css";

type Fund = {
    symbol: string;
    name: string;
    role: string;
    market: string;
    method: string;
    methodDate: string;
    methodUrl: string;
    holdingDate: string;
    holdings: string[];
    holdingNote: string;
    holdingUrl: string;
    gap: string;
};
const FUNDS: Fund[] = [
    {
        symbol: "0050",
        name: "元大台灣50",
        role: "台股大型股比較基準",
        market: "台灣上市大型公司",
        method: "追蹤臺灣50指數；官方月報說明採完全複製。定期調整在 3、6、9、12 月第三個星期五後的下一交易日生效；完整資格、流動性與權重仍應依當期 FTSE/TWSE 規則。",
        methodDate: "2026-10-01 研究摘錄",
        methodUrl:
            "https://www.yuantaetfs.com/product/detail/0050/Basic_information",
        holdingDate: "2026-10-01",
        holdings: [
            "2330 台積電 56.52%",
            "2454 聯發科 6.75%",
            "2308 台達電 3.39%",
        ],
        holdingNote: "官網「商品權重」；另有期貨，股票表不能當全部曝險。",
        holdingUrl: "https://www.yuantaetfs.com/product/detail/0050/ratio",
        gap: "已有當期持股樣本；還沒確認每日歷史持股是否完整、能查到多久以前，以及能否穩定取得。",
    },
    {
        symbol: "0052",
        name: "富邦科技",
        role: "分辨成果是否主要來自科技集中",
        market: "台灣上市科技公司",
        method: "從臺灣50與臺灣中型100成分公司選取 ICB 科技分類者，採公眾流通量市值加權；成分數不固定。季度調整，重大事件可不定期變動。",
        methodDate: "2026-10-01 研究摘錄",
        methodUrl:
            "https://websys.fsit.com.tw/FubonETF/Fund/IndexIntro.aspx?stkId=0052",
        holdingDate: "2026-08-31",
        holdings: ["台積電 64.37%", "聯發科 6.34%", "鴻海 3.35%"],
        holdingNote:
            "官方月報比例；每日基金資產頁解析失敗，不能稱為 10 月最新持股。",
        holdingUrl: "https://etrade.fsit.com.tw/homelink/report/27.pdf",
        gap: "已有月報持股樣本；還沒確認歷年每一天的完整持股名單。",
    },
    {
        symbol: "00981A",
        name: "主動統一台股增長",
        role: "主動選股方法與資料透明度範例",
        market: "台灣上市櫃公司",
        method: "大型、創新、成長為核心方向；60% 以上投資台灣上市櫃市值前 300 大。由經理人主動調整，完整決策規則未公開。",
        methodDate: "2026-10-01 研究摘錄；募集資料為 2025 年",
        methodUrl: "https://www.ezmoney.com.tw/events/2025TGA/00981A-DM.pdf",
        holdingDate: "當期尚未核對",
        holdings: [
            "2025-10-31 舊搜尋快照：台積電 8.79%",
            "奇鋐 7.70%",
            "貿聯-KY 6.60%",
        ],
        holdingNote: "僅為歷史文獻樣本，不是目前持股。",
        holdingUrl:
            "https://www.ezmoney.com.tw/docUpload/ETF/FundMR/MR-49YTW.pdf",
        gap: "已有較舊持股樣本；最新官方績效、完整持股與當期基金說明書仍待核對。",
    },
    {
        symbol: "VOO",
        name: "Vanguard S&P 500 ETF",
        role: "美國大型股比較基準",
        market: "美國大型公司",
        method: "被動完全複製 S&P 500。指數有正式選取標準與委員會維護程序，不能簡化為市值前 500 檔；官方列季度再平衡。",
        methodDate: "2026-10-01 研究摘錄",
        methodUrl: "https://www.spglobal.com/spdji/en/indices/equity/sp-500/",
        holdingDate: "2026-08-31",
        holdings: ["NVIDIA 8.07623%", "Apple 7.02889%", "Microsoft 5.69171%"],
        holdingNote:
            "官方比例以持股市值計算（原欄 % of market value）；保留原始比例。",
        holdingUrl:
            "https://www.vanguardsouthamerica.com/en/product/etf/equity/0968/vanguard-sp-500-etf",
        gap: "已有持股與績效摘錄；還沒確認每日歷史資料是否完整。",
    },
    {
        symbol: "QQQM",
        name: "Invesco NASDAQ 100 ETF",
        role: "科技傾向且跨產業的成長比較",
        market: "Nasdaq 大型非金融公司",
        method: "至少 90% 總資產投資 Nasdaq-100 成分證券；季度再平衡、年度重新選取，並有修正市值權重及特殊再平衡條件。",
        methodDate: "2026-10-01 研究摘錄",
        methodUrl: "https://indexes.nasdaq.com/docs/Methodology_NDX.pdf",
        holdingDate: "2026-05-31；申報公開日 2026-07-30",
        holdings: [
            "NVIDIA 8.130358884899%",
            "Apple 7.259730570265%",
            "Microsoft 5.298096063406%",
        ],
        holdingNote: "SEC 原欄為投資價值占基金淨資產；是較舊申報快照。",
        holdingUrl:
            "https://www.sec.gov/Archives/edgar/data/1378872/000137887226001400/xslFormNPORT-P_X01/primary_doc.xml",
        gap: "已有較舊申報持股；仍需補最新每日持股，並確認哪些年月還缺資料。",
    },
    {
        symbol: "SMH",
        name: "VanEck Semiconductor ETF（美國版）",
        role: "單一產業集中比較",
        market: "美國上市半導體及設備企業，含外國企業",
        method: "以半導體營收、公司規模與交易流動性篩選，目標 25 個成分，採修正流通市值權重；3、9 月重新選取，季度調整權重。",
        methodDate: "2026-09 方法版本；2026-10-01 研究摘錄",
        methodUrl:
            "https://www.marketvector.com/rulebooks/download/MVSMH_Index_Guide.pdf",
        holdingDate: "2026-09-30",
        holdings: ["NVIDIA 19.37%", "TSM 9.24%", "AMD 5.57%"],
        holdingNote: "官網 % of Net Assets；含 ADR 等，不等於美國企業名單。",
        holdingUrl:
            "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh/?audience=retail&country=us",
        gap: "已有當期持股樣本；每日歷史持股檔案能查到多久以前，以及公司的法律註冊地仍待核對。",
    },
];

const PERFORMANCE: Record<
    string,
    { asOf: string; oneYear: string; basis: string; gap: string }
> = {
    "0050": {
        asOf: "2026-08-31",
        oneYear: "近 1 年累積 108.23%",
        basis: "官方月報基金績效；以台幣計算，未直接說明使用基金淨值或市場價格。",
        gap: "已有官方報酬數值；配息如何再投入、如何計入報酬，還需要核對。",
    },
    "0052": {
        asOf: "2026-08-31",
        oneYear: "近 1 年 115.91%",
        basis: "官方基金報酬率；以台幣計算，未直接說明使用基金淨值或市場價格。",
        gap: "這份摘錄沒有說清楚配息、稅與各項費用如何計入報酬。",
    },
    "00981A": {
        asOf: "未取得符合要求的當期官方績效",
        oneYear: "無可展示數值",
        basis: "基金以台幣計價。",
        gap: "不能以其他基金績效或上市前試算代替。",
    },
    VOO: {
        asOf: "2026-06-30",
        oneYear: "近 1 年 22.28%",
        basis: "按基金淨值計算的總報酬（NAV total return）；以美元計算。",
        gap: "仍需相同期間的每日報酬資料，並先確認美元換成台幣的計算方式。",
    },
    QQQM: {
        asOf: "2026-06-30",
        oneYear: "近 1 年 34.17%",
        basis: "按基金淨值（NAV）計算的報酬；以美元計算。",
        gap: "配息如何再投入、費用如何計入報酬，還需要補齊說明。",
    },
    SMH: {
        asOf: "2026-08-31",
        oneYear: "近 1 年 92.36%",
        basis: "按基金淨值計算的總報酬（NAV total return）；以美元計算。",
        gap: "配息何時再投入、費用與稅如何計入報酬，還需要補齊說明。",
    },
};

const PERFORMANCE_SOURCES: Record<string, string> = {
    "0050": "https://www.yuantafunds.com/fund/download/1066%E5%85%83%E5%A4%A7%E5%8F%B0%E7%81%A3%E5%8D%93%E8%B6%8A50%E5%9F%BA%E9%87%91%E6%9C%88%E5%A0%B1.pdf",
    "0052": "https://websys.fsit.com.tw/FubonETF/Fund/Performance.aspx?stkId=0052",
    VOO: "https://fund-docs.vanguard.com/F0968.pdf",
    QQQM: "https://www.invesco.com/us-rest/contentdetail?contentId=5b4d8e58e0737710VgnVCM1000006e36b50aRCRD",
    SMH: "https://www.vaneck.com/us/en/investments/semiconductor-etf-smh-fact-sheet.pdf",
};
export function FundsPage() {
    const [query, setQuery] = useState("");
    const [selected, setSelected] = useState("0050");
    const [compare, setCompare] = useState<string[]>([]);
    const visible = useMemo(
        () =>
            FUNDS.filter((fund) =>
                `${fund.symbol} ${fund.name} ${fund.role} ${fund.market}`
                    .toLocaleLowerCase()
                    .includes(query.toLocaleLowerCase()),
            ),
        [query],
    );
    const fund = FUNDS.find((item) => item.symbol === selected) ?? FUNDS[0];
    const performance = PERFORMANCE[fund.symbol];
    const compared = FUNDS.filter((item) => compare.includes(item.symbol));
    function toggle(symbol: string) {
        setCompare((current) =>
            current.includes(symbol)
                ? current.filter((item) => item !== symbol)
                : current.length < 3
                  ? [...current, symbol]
                  : current,
        );
    }
    return (
        <section className="fund-page">
            <header className="fund-hero">
                <h1>ETF 圖鑑</h1>
                <span>
                    查看六檔 ETF 的選股方法、持股與官方績效。資料摘錄於
                    2026-10-01，非即時更新；各檔資料日期不同，不能直接當作績效排名或買賣建議。
                </span>
            </header>
            <section className="fund-toolbar">
                <label htmlFor="fund-search">搜尋 ETF</label>
                <input
                    id="fund-search"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="代號、名稱、市場或角色"
                />
                <span>
                    最多選 3
                    檔並列查看；歷史資料與報酬算法尚未核對完整，目前還不能畫比較曲線或排名。
                </span>
            </section>
            <div className="fund-layout">
                <section className="fund-list" aria-label="ETF 候選列表">
                    {visible.map((item) => (
                        <article
                            key={item.symbol}
                            className={`fund-card${item.symbol === fund.symbol ? " fund-active" : ""}`}
                        >
                            <button
                                type="button"
                                className="fund-select"
                                onClick={() => setSelected(item.symbol)}
                                aria-pressed={item.symbol === fund.symbol}
                            >
                                <strong>{item.symbol}</strong>
                                <span>{item.name}</span>
                                <small>{item.role}</small>
                            </button>
                            <label className="fund-compare">
                                <input
                                    type="checkbox"
                                    checked={compare.includes(item.symbol)}
                                    onChange={() => toggle(item.symbol)}
                                    disabled={
                                        !compare.includes(item.symbol) &&
                                        compare.length === 3
                                    }
                                />{" "}
                                比較
                            </label>
                        </article>
                    ))}
                </section>
                <section className="fund-detail">
                    <div className="fund-title">
                        <div>
                            <p>{fund.market}</p>
                            <h2>
                                {fund.symbol} {fund.name}
                            </h2>
                            <span>{fund.role}</span>
                        </div>
                        <a
                            href={fund.methodUrl}
                            target="_blank"
                            rel="noreferrer"
                        >
                            原文方法 ↗
                        </a>
                    </div>
                    <details open>
                        <summary>方法與公開程度</summary>
                        <p>{fund.method}</p>
                        <dl>
                            <dt>來源日期</dt>
                            <dd>{fund.methodDate}</dd>
                            <dt>原文 URL</dt>
                            <dd>
                                <a
                                    href={fund.methodUrl}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    {fund.methodUrl}
                                </a>
                            </dd>
                        </dl>
                    </details>
                    <details open>
                        <summary>官方績效摘錄</summary>
                        <p>
                            <strong>{performance.oneYear}</strong>（截至{" "}
                            {performance.asOf}）
                        </p>
                        <p className="fund-note">{performance.basis}</p>
                        <p className="fund-note">
                            還需要確認：{performance.gap}
                        </p>
                        {PERFORMANCE_SOURCES[fund.symbol] && (
                            <a
                                href={PERFORMANCE_SOURCES[fund.symbol]}
                                target="_blank"
                                rel="noreferrer"
                            >
                                績效來源原文 ↗
                            </a>
                        )}
                    </details>
                    <details open>
                        <summary>持股樣本</summary>
                        <p>
                            最近可核對持股日期：
                            <strong>{fund.holdingDate}</strong>
                        </p>
                        <ul>
                            {fund.holdings.map((holding) => (
                                <li key={holding}>{holding}</li>
                            ))}
                        </ul>
                        <p className="fund-note">{fund.holdingNote}</p>
                        <a
                            href={fund.holdingUrl}
                            target="_blank"
                            rel="noreferrer"
                        >
                            持股原文 URL ↗
                        </a>
                    </details>
                    <aside>
                        <strong>哪些資料還不完整？</strong>
                        <p>{fund.gap}</p>
                        <span>
                            畫比較曲線前，還需核對完整歷史資料，並統一幣別、配息與費用的計算方式。
                        </span>
                    </aside>
                </section>
            </div>
            <section className="fund-compare-panel">
                <div>
                    <p>比較籃</p>
                    <h2>{compare.length ? compare.join(" · ") : "尚未選擇"}</h2>
                </div>
                <button type="button" disabled>
                    比較曲線（資料不足）
                </button>
                <p>
                    各檔截止日、幣別與報酬定義不同，以下只並列原始摘錄，不能排名。
                </p>
                {compared.length > 0 && (
                    <div className="fund-compare-table">
                        <table>
                            <thead>
                                <tr>
                                    <th>ETF</th>
                                    <th>市場／角色</th>
                                    <th>方法</th>
                                    <th>持股日期</th>
                                    <th>官方 1 年摘錄</th>
                                    <th>已知缺口</th>
                                </tr>
                            </thead>
                            <tbody>
                                {compared.map((item) => {
                                    const itemPerformance =
                                        PERFORMANCE[item.symbol];
                                    return (
                                        <tr key={item.symbol}>
                                            <th scope="row">
                                                {item.symbol}
                                                <br />
                                                <small>{item.name}</small>
                                            </th>
                                            <td>
                                                {item.market}
                                                <br />
                                                <small>{item.role}</small>
                                            </td>
                                            <td>{item.method}</td>
                                            <td>{item.holdingDate}</td>
                                            <td>
                                                {itemPerformance.oneYear}
                                                <br />
                                                <small>
                                                    {itemPerformance.asOf}；
                                                    {itemPerformance.basis}
                                                </small>
                                            </td>
                                            <td>
                                                {item.gap}
                                                <br />
                                                <small>
                                                    {itemPerformance.gap}
                                                </small>
                                            </td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>
        </section>
    );
}
