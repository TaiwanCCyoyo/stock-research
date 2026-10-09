const eventLabels: Record<string, string> = {
    BUY: "買進",
    SELL: "賣出",
    DIVIDEND_ENTITLEMENT: "除息（應收股息）",
    DIVIDEND: "股息入帳",
    CAPITAL_RETURN_ENTITLEMENT: "減資（應收退還款）",
    CAPITAL_RETURN: "減資退還款入帳",
    SPLIT: "股票分割",
};

export const eventLabel = (action: string) =>
    eventLabels[action] ?? "其他事件（說明待補）";

export const researchName = (name: string) =>
    ({
        "一張試單＋未成交加碼單重試一次": "試單與加碼重試",
        "一張試單＋初次買入不追高於 60 日漲幅 50%": "初次買進漲幅限制",
    })[name] ?? name;

// Translate only recorded wording we understand; unfamiliar records remain intact.
const recordedText: Record<string, string> = {
    "Recorded daily_evening 20:00 Asia/Taipei account equity using available raw marks; not adjusted-price or execution-price returns.":
        "每天台北時間晚上 8 點，沿用已保存的價格記錄帳戶價值；原始帳本也有具名估值紀錄，這些估算不是當日觀察價。不是用還原股價或成交價計算的報酬。",
    "持有經濟報酬達 +10% 時，以原 30 萬元 gross target 加碼；每日 rank>30 或未上榜退出。":
        "持有報酬（含公司行動）達 +10% 時，沿用原本 30 萬元的加碼目標（未扣交易成本）；每天排名掉出前 30 名或未上榜就賣出。",
    "保留同一 daily 基礎策略、收盤後決策及次交易日模型成交。":
        "沿用同一每日策略：收盤後決定買賣，下一個交易日模擬成交。",
    "僅於初始 BUY 前剔除決策日原始 ret60>50% 的提案；不重新排序、不用較低順位補入。":
        "第一次買進前，剔除決策日原始 60 日漲幅超過 50% 的股票；不重新排名，也不以較低名次股票遞補。",
    "不限制加碼，保留原每日 rank30／未上榜退出條件。":
        "加碼不受這項限制；沿用每天排名掉出前 30 名或未上榜就賣出的條件。",
    "原加碼單已確認終止且完全未成交後，僅在第一個允許決策時重查條件，最多多一次次交易日重試。":
        "原加碼委託確定已終止、完全沒有成交後，在下一次允許決策時重新檢查條件；最多再試一次，於次一交易日模擬成交。",
    "正常成交情境通過開發篩選，值得繼續研究；尚未最終批准，也未證明延遲問題已解決。":
        "正常成交的模擬結果達到初步研究要求，可繼續研究；尚未採用，也還沒證明延遲成交的問題已解決。",
    "候選已完成且失敗；開發期報酬與命中廣度不足以晉級。帳本對帳完成不改變失敗結論。 Retained only 13.694087917% of control net profit against 70% development floor; one captured-hit issuer against two required. Do not tune this failed cap after seeing results.":
        "這個候選策略已淘汰：淨利只達原策略的 13.694087917%，低於事先要求的 70%；只跟上 1 家大漲公司，未達要求的 2 家。帳目核對完成不改變結論，也不能看過結果後再調整這項漲幅限制。",
    "This replays saved accounting events; no strategy decisions, fills or research gates are recalculated.":
        "只展示已保存的帳戶紀錄，沒有重跑買賣決策、成交或研究驗證。",
    "20:00 account states use recorded available raw marks; these are not intraday execution observations.":
        "晚上 8 點的帳戶價值沿用已保存的價格與原始帳本具名估值，不代表盤中成交情況。",
    "Tradable positions exclude undelivered share claims; receivables and claims are not spendable cash.":
        "尚未交付的股票不算可交易持股；應收款與待交付股票也不能當現金使用。",
    "No adjusted-return series or wave-overlap metric is produced.":
        "這份結果沒有提供還原股價報酬曲線，也沒有計算持有期間跟上多少漲幅。",
    "Event-index presentation IDs are derived keys, not invented native order or event IDs.":
        "畫面上的事件編號用來查找紀錄，不是原始委託或事件編號。",
    "exposed development period": "這段期間已在研究時看過，不能當作獨立驗證。",
    "same-candidate delayed economics not reviewed in this handoff":
        "同一策略延遲成交後的盈虧尚未核對。",
    "other resilience and independent evidence outstanding":
        "其他成交異常情境與獨立驗證仍未完成。",
    "four open attempts": "仍有 4 筆嘗試未結案。",
    "one open attempt": "仍有 1 筆嘗試未結案。",
    "owner final loss budget not approved":
        "可接受的最終虧損額度尚未獲得確認。",
    "global non-hit window maximum unknown":
        "未跟上大漲股票的各段期間，其全期間最大值尚未確認（詳見原始研究限制）。",
    "not independent confirmation": "這份結果不是獨立驗證。",
    "兩個案例使用已暴露的開發期間，不是獨立驗證；final_strategy_approved=false。":
        "兩個案例都使用研究時已看過的期間，不是獨立驗證，策略尚未獲准採用。",
};

export const researchText = (text: string) => recordedText[text] ?? text;
