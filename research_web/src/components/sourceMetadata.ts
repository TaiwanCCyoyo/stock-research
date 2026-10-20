export interface SnapshotSource {
    kind: "saved-snapshot";
    mode: "public-synthetic" | "local-private";
    schema: string;
    version: string;
    asOf: string | null;
    from: string | null;
    through: string | null;
    historyThrough: string | null;
}

export function snapshotDescription(
    source: SnapshotSource | undefined,
    history = false,
): string {
    if (!source)
        return "此服務尚未提供來源版本；無法確認目前顯示的研究快照版本。";
    const label =
        source.mode === "public-synthetic"
            ? "目前是合成示範，設定方式見 README"
            : "真實研究固定快照";
    const coverage = history
        ? `研究登錄截至 ${source.historyThrough ?? "未知"}`
        : `帳戶期間 ${source.from ?? "未知"} 至 ${source.through ?? "未知"}；資料截至 ${source.asOf ?? "未知"}`;
    return `${label} · ${coverage} · 版本 ${source.version.slice(0, 12)}。固定研究快照不會隨共用資料更新；執行中的研究尚未列入已完成結果。`;
}
