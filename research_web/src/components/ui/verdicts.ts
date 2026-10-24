export type Verdict =
    | "promising"
    | "no_edge"
    | "mixed"
    | "failed"
    | "running"
    | "not_evaluated"
    | "archived";

export const VERDICT_LABELS: Record<Verdict, string> = {
    promising: "有線索",
    no_edge: "沒有優勢",
    mixed: "結果不一",
    failed: "行不通",
    running: "進行中",
    not_evaluated: "尚未評估",
    archived: "舊資料",
};
