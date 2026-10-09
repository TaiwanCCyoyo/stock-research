import type { OpportunityRow } from "../../domain/opportunities/types.ts";

export const seriesColor = (index: number) =>
    `var(--compare-${(index % 4) + 1})`;
export const pct = (n: number | null | undefined, signed = true) =>
    n == null
        ? "不知道"
        : `${signed && n >= 0 ? "+" : ""}${n.toLocaleString("zh-TW", { maximumFractionDigits: 1 })}%`;
export const share = (n: number | null | undefined) =>
    n == null ? "不知道" : `${(n * 100).toFixed(1)}%`;
export const reasonText = (value: string | null) =>
    value == null
        ? ""
        : ((
              {
                  "before-launch": "還沒開始大漲",
                  "after-observed-through": "資料不足",
                  "missing-or-flagged-price": "價格缺漏或品質待核對",
                  "missing-representative-interval": "尚未選定這一天的代表波段",
                  "no-same-date-allocation": "沒有這一天的資金配置紀錄",
                  "partial-allocation":
                      "只知道部分資金配置，保留未能分類的餘額",
                  "unknown-cash-weight": "這一天的現金比例尚未提供",
                  "unclassified-or-unobserved-capital":
                      "部分股票不在這份案例範圍，尚不能判定是否屬於大漲股",
                  "allocation-assets-outside-reliable-catalog":
                      "資產不在可核對的案例範圍",
                  "unknown-holding-on-positive-day": "部分上漲日期沒有持股紀錄",
                  "no-positive-price-moves": "這段期間沒有正漲幅，比例未定義",
                  "partial-holding-coverage": "部分日期的持股狀態未知",
              } as Record<string, string>
          )[value] ?? "資料不足；可展開研究工具查看原始欄位");
export function stateLabel(row: OpportunityRow, date: string): string {
    if (row.state === "unknown") return "資料不足";
    if (row.state === "ended") return "漲勢結束";
    if (row.state === "unlaunched") return "尚未開始大漲";
    if (row.wave.launch && date === row.wave.launch.date) return "剛開始大漲";
    if (row.phase == null) return "";
    return {
        slow: "慢慢上漲",
        rising: "大漲中",
        resting: "漲多休息",
        retreat: "從最高點拉回",
    }[row.phase];
}
