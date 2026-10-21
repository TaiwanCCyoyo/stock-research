import { createElement } from "react";
import type { StudioHistoryItem } from "../../domain/strategies/types.ts";

type RegistrationState = Pick<
    StudioHistoryItem,
    "id" | "status" | "evidenceState" | "sourceNote"
>;

/** Keep the warning outside disclosures while leaving saved evidence intact. */
export function RecentResearchNotice({ item }: { item: RegistrationState }) {
    if (item.status !== "登錄需更新") return null;
    const label =
        item.evidenceState === "registration_unavailable"
            ? "登錄需更新"
            : "登錄需更新 · 保留舊版";
    return createElement(
        "p",
        { className: "ss-warning", role: "status" },
        createElement("strong", null, label),
        ` ${item.id}：${item.sourceNote || "請至研究歷程查看登錄狀態。"}`,
    );
}
