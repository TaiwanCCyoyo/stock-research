import { safeStudyBack } from "../data-overview/datasetJourney.ts";
import { CELLS, casePage, initialSelection } from "./model.ts";
import type { ComparisonView, SavedCase, Selection } from "./model.ts";

export interface ComparisonLocation {
    resultId: string;
    back: string;
    selection: Selection;
    openCase?: string;
}
const PARAMETERS = [
    "result",
    "h",
    "group",
    "filter",
    "page",
    "sort",
    "event",
    "open",
    "back",
];

/** Only research-list and report destinations; no arbitrary route or URL. */
export function comparisonBack(value: string | null): string {
    if (
        value &&
        /^#report\/[A-Za-z0-9][A-Za-z0-9._-]*$/.test(value) &&
        value.length < 256
    )
        return value;
    const study = safeStudyBack(value);
    return study === "#overview" ? "#studies" : study;
}
export function comparisonHref(
    selection: Selection,
    back = "#studies",
    openCase?: string,
): string {
    const query = new URLSearchParams({
        result: selection.resultId,
        h: String(selection.horizon),
        group: selection.group,
        filter: selection.filter,
        page: String(selection.page),
        sort: selection.sort,
        back: comparisonBack(back),
    });
    if (selection.eventId) query.set("event", selection.eventId);
    if (openCase) query.set("open", openCase);
    return "#condition-comparison?" + query;
}
export function parseComparisonLocation(hash: string): ComparisonLocation {
    if (!hash.startsWith("#condition-comparison?") || hash.length > 8192)
        throw new Error("比較網址不完整或過長。");
    const query = new URLSearchParams(hash.slice(hash.indexOf("?") + 1));
    for (const key of query.keys()) {
        if (!PARAMETERS.includes(key) || query.getAll(key).length !== 1)
            throw new Error("比較網址有未知或重複設定；請返回研究頁重新選取。");
    }
    const resultId = query.get("result") ?? "";
    if (!/^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$/.test(resultId))
        throw new Error("缺少有效的保存結果識別。");
    const horizon = Number(query.get("h") ?? "126");
    const group = query.get("group") ?? "all";
    const filter = query.get("filter") ?? "all";
    const sort = query.get("sort") ?? "date-desc";
    const rawPage = query.get("page") ?? "0";
    if (
        ![126, 252].includes(horizon) ||
        !["all", ...CELLS].includes(group) ||
        !["all", "hit", "not-hit", "unknown"].includes(filter) ||
        !["date-asc", "date-desc"].includes(sort) ||
        !/^(0|[1-9][0-9]{0,5})$/.test(rawPage)
    )
        throw new Error("比較視窗、篩選或頁碼不受支援。");
    const eventId = query.get("event") ?? undefined;
    const openCase = query.get("open") ?? undefined;
    for (const value of [eventId, openCase])
        if (
            value !== undefined &&
            (!value ||
                value.length > 256 ||
                Array.from(value).some(
                    (char) =>
                        char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127,
                ))
        )
            throw new Error("個案識別不正確。");
    return {
        resultId,
        back: comparisonBack(query.get("back")),
        openCase,
        selection: {
            resultId,
            horizon: horizon as Selection["horizon"],
            group: group as Selection["group"],
            filter: filter as Selection["filter"],
            sort: sort as Selection["sort"],
            page: Number(rawPage),
            eventId,
        },
    };
}
/** Check identity against the actual saved view, not URL-supplied provenance. */
export function validateComparisonLocation(
    view: ComparisonView,
    route: ComparisonLocation,
): SavedCase | undefined {
    if (view.id !== route.resultId || view.source.resultId !== route.resultId)
        throw new Error("保存結果與網址版本不一致。");
    const page = casePage(
        view.windows[route.selection.horizon],
        route.selection,
    );
    if (page.page !== route.selection.page)
        throw new Error("此保存清單沒有指定頁碼。");
    if (
        route.selection.eventId &&
        !page.rows.some((item) => item.eventId === route.selection.eventId)
    )
        throw new Error("選取個案不在目前格、篩選與頁碼內。");
    if (!route.openCase) return;
    const item = page.rows.find((item) => item.eventId === route.openCase);
    if (!item || item.eventId !== route.selection.eventId || !item.readerRef)
        throw new Error("此情境沒有可讀個案；未替換成其他股票或版本。");
    return item;
}
export function comparisonEntryHref(
    view: ComparisonView,
    back: string,
): string {
    return comparisonHref(initialSelection(view), back);
}
