import {
    assertHistoryVersion,
    validateHistoryVersion,
    type HistoryBundleIdentity,
} from "./versionIdentity.ts";
import { readHistory } from "./api.ts";
import {
    HISTORY_SCHEMA,
    type HistoryMetadata,
    type HistoryFrame,
    type HistoryRow,
    type HistoryDetail,
} from "./types.ts";

/** URL context, not a new research-data schema. Keys are supplied by the producer. */
export interface WaveContext {
    bundleIdentity?: HistoryBundleIdentity;
    securityKey: string;
    securityId: string;
    seriesId: string;
    waveId: string;
    catalogId: string;
    date: string;
    from: string;
    to: string;
    priceBasis: string;
    mode: "catalog" | "launched";
    threshold: number;
}
const fields = [
    "securityKey",
    "securityId",
    "seriesId",
    "waveId",
    "catalogId",
    "date",
    "from",
    "to",
    "priceBasis",
    "mode",
    "threshold",
];
function date(value: string) {
    return (
        /^\d{4}-\d{2}-\d{2}$/.test(value) &&
        Number.isFinite(Date.parse(value)) &&
        new Date(value).toISOString().slice(0, 10) === value
    );
}
export function validateWaveContext(value: unknown): WaveContext {
    if (!value || typeof value !== "object" || Array.isArray(value))
        throw new Error("波段來源脈絡缺漏。");
    const item = value as Record<string, unknown>;
    if (
        Object.keys(item).length !==
            fields.length + ("bundleIdentity" in item ? 1 : 0) ||
        fields.some((key) => !(key in item))
    )
        throw new Error("波段來源欄位不完整。");
    for (const key of fields.filter((key) => key !== "threshold")) {
        const text = item[key];
        if (
            typeof text !== "string" ||
            !text.trim() ||
            text.length > 1024 ||
            [...text].some(
                (char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127,
            )
        )
            throw new Error("波段來源識別無效。");
    }
    const identity =
        "bundleIdentity" in item
            ? validateHistoryVersion(item.bundleIdentity)
            : undefined;
    const context = {
        ...item,
        ...(identity ? { bundleIdentity: identity } : {}),
    } as unknown as WaveContext;
    if (identity && context.catalogId !== identity.manifestSha256)
        throw new Error("波段目錄與版本識別不一致。");
    if (
        !["catalog", "launched"].includes(context.mode) ||
        ![60, 80, 100, 200].includes(context.threshold) ||
        ![context.date, context.from, context.to].every(date) ||
        context.from > context.to ||
        context.date < context.from ||
        context.date > context.to
    )
        throw new Error("波段區間或地圖設定無效。");
    return context;
}
export function waveContext(
    metadata: HistoryMetadata,
    frame: HistoryFrame,
    row: HistoryRow,
    mode: WaveContext["mode"],
    threshold: number,
): WaveContext {
    if (!row.securityKey)
        throw new Error(
            "來源未提供可核對的 opaque security key；不能由股票代碼推測個股身分。",
        );
    const context = validateWaveContext({
        ...(metadata.bundleIdentity
            ? { bundleIdentity: metadata.bundleIdentity }
            : {}),
        securityKey: row.securityKey,
        securityId: row.securityId,
        seriesId: row.seriesId,
        waveId: row.waveId,
        catalogId: frame.catalogId,
        date: frame.date,
        from: row.start,
        to: row.observedThrough,
        priceBasis: metadata.basisLabel,
        mode,
        threshold,
    });
    matchWaveFrame(context, metadata, frame);
    return context;
}
export function waveHref(context: WaveContext, target: "stock" | "market") {
    const c = validateWaveContext(context);
    const query = new URLSearchParams({ wave: JSON.stringify(c) });
    return (
        (target === "stock"
            ? `#stock/${encodeURIComponent(c.securityKey)}`
            : "#market") +
        "?" +
        query
    );
}
export function hasWaveContext(hash: string) {
    return new URLSearchParams(hash.split("?")[1] ?? "").has("wave");
}
export function readWaveContext(hash: string): WaveContext | null {
    if (!hasWaveContext(hash)) return null;
    const [path, raw] = hash.split("?");
    const query = new URLSearchParams(raw);
    if (
        hash.length > 16000 ||
        query.getAll("wave").length !== 1 ||
        [...query.keys()].some((key) => key !== "wave")
    )
        throw new Error("波段網址含重複或未知設定。");
    const context = validateWaveContext(JSON.parse(query.get("wave")!));
    if (
        path !== "#market" &&
        path !== `#stock/${encodeURIComponent(context.securityKey)}`
    )
        throw new Error("個股識別與波段來源不一致。");
    return context;
}
export function matchWaveFrame(
    context: WaveContext,
    metadata: HistoryMetadata,
    frame: HistoryFrame,
): HistoryRow {
    if (context.bundleIdentity) {
        assertHistoryVersion(metadata, context.bundleIdentity);
        assertHistoryVersion(frame, context.bundleIdentity);
    }
    if (
        metadata.schema !== HISTORY_SCHEMA ||
        frame.schema !== HISTORY_SCHEMA ||
        metadata.catalogId !== context.catalogId ||
        frame.catalogId !== context.catalogId ||
        metadata.basisLabel !== context.priceBasis ||
        frame.date !== context.date ||
        !metadata.dates.includes(context.date)
    )
        throw new Error("指定歷史版本、日期或價格基準不可用；未改讀現況。");
    const rows = frame.rows.filter(
        (row) =>
            row.securityKey === context.securityKey &&
            row.securityId === context.securityId &&
            row.seriesId === context.seriesId &&
            row.waveId === context.waveId,
    );
    if (
        rows.length !== 1 ||
        rows[0].start !== context.from ||
        rows[0].observedThrough !== context.to
    )
        throw new Error("指定版本的波段成員或區間不可用；未替換其他波段。");
    return rows[0];
}
export function matchWaveDetail(
    context: WaveContext,
    detail: HistoryDetail,
): HistoryDetail {
    if (context.bundleIdentity)
        assertHistoryVersion(detail, context.bundleIdentity);
    const row = detail.row;
    if (
        detail.schema !== HISTORY_SCHEMA ||
        detail.catalogId !== context.catalogId ||
        detail.date !== context.date ||
        !row ||
        row.securityKey !== context.securityKey ||
        row.securityId !== context.securityId ||
        row.seriesId !== context.seriesId ||
        row.waveId !== context.waveId ||
        row.start !== context.from ||
        row.observedThrough !== context.to ||
        detail.sample.source.catalogHash !== context.catalogId ||
        detail.sample.source.priceBasis !== context.priceBasis ||
        !detail.sample.source.hash ||
        ![context.from, context.date, context.to].every((day) =>
            detail.sample.points.some(
                (p) =>
                    p.date === day &&
                    p.adjusted !== null &&
                    Number.isFinite(p.adjusted),
            ),
        )
    )
        throw new Error(
            "指定波段的歷史價格、成員或來源不可用；未改讀現況行情。",
        );
    return detail;
}
export async function readWaveDetail(
    context: WaveContext,
    signal: AbortSignal,
    reader: typeof readHistory = readHistory,
) {
    const metadata = await reader<HistoryMetadata>(
        "/metadata",
        signal,
        context.bundleIdentity,
    );
    if (context.bundleIdentity)
        assertHistoryVersion(metadata, context.bundleIdentity);
    signal.throwIfAborted();
    if (
        metadata.catalogId !== context.catalogId ||
        metadata.basisLabel !== context.priceBasis
    )
        throw new Error("指定歷史版本或價格基準不可用。");
    const frame = await reader<HistoryFrame>(
        `/frame?date=${encodeURIComponent(context.date)}`,
        signal,
        context.bundleIdentity,
    );
    signal.throwIfAborted();
    const row = matchWaveFrame(context, metadata, frame);
    // The existing reader takes a code, obtained only from the verified saved member.
    const detail = await reader<HistoryDetail>(
        `/security/${encodeURIComponent(row.code)}?date=${encodeURIComponent(context.date)}`,
        signal,
        context.bundleIdentity,
    );
    signal.throwIfAborted();
    return matchWaveDetail(context, detail);
}
