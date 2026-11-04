/** Transport identity of a catalog-registered immutable bundle, not a filesystem path. */
export interface HistoryBundleIdentity {
    versionId: string;
    manifestSha256: string;
}

export function validateHistoryVersion(value: unknown): HistoryBundleIdentity {
    if (!value || typeof value !== "object" || Array.isArray(value))
        throw new Error("歷史版本識別不完整。");
    const item = value as Record<string, unknown>;
    const version = item.versionId;
    const sha = item.manifestSha256;
    if (
        Object.keys(item).length !== 2 ||
        typeof version !== "string" ||
        !version.trim() ||
        version.length > 1024 ||
        /[\\:]/.test(version) ||
        Array.from(version).some((char) => {
            const point = char.charCodeAt(0);
            return point < 32 || (point >= 127 && point <= 159);
        }) ||
        version
            .split("/")
            .some((part) => !part || part === "." || part === "..") ||
        typeof sha !== "string" ||
        !/^[a-f0-9]{64}$/i.test(sha)
    )
        throw new Error("歷史版本或 manifest 雜湊無效。");
    return { versionId: version, manifestSha256: sha.toLowerCase() };
}

export function historyVersionKey(identity?: HistoryBundleIdentity): string {
    return identity
        ? JSON.stringify([identity.versionId, identity.manifestSha256])
        : "legacy-default";
}

export function assertHistoryVersion(
    value: unknown,
    expected: HistoryBundleIdentity,
): void {
    if (!value || typeof value !== "object")
        throw new Error("缺少已保存版本識別。");
    const payload = value as Record<string, unknown>;
    const actual = validateHistoryVersion(payload.bundleIdentity);
    expected = validateHistoryVersion(expected);
    if (
        historyVersionKey(actual) !== historyVersionKey(expected) ||
        ("catalogId" in payload &&
            payload.catalogId !== expected.manifestSha256)
    )
        throw new Error("回應不是指定的歷史版本；不改讀目前資料。");
}

export function historyVersionPath(
    path: string,
    identity?: HistoryBundleIdentity,
): string {
    if (!identity) return path;
    const pin = validateHistoryVersion(identity);
    const [base, query = ""] = path.split("?");
    const params = new URLSearchParams(query);
    if (params.has("version_id") || params.has("manifest_sha256"))
        throw new Error("重複的歷史版本參數。");
    params.set("version_id", pin.versionId);
    params.set("manifest_sha256", pin.manifestSha256);
    return `${base}?${params}`;
}

export function readMarketVersion(
    hash: string,
): HistoryBundleIdentity | undefined {
    const [page, query = ""] = hash.split("?");
    if (page !== "#market") return undefined;
    const params = new URLSearchParams(query);
    if (!params.has("version_id") && !params.has("manifest_sha256"))
        return undefined;
    if (
        params.getAll("version_id").length !== 1 ||
        params.getAll("manifest_sha256").length !== 1 ||
        params.has("wave")
    )
        throw new Error("歷史網址的版本參數缺漏、重複或與波段來源衝突。");
    return validateHistoryVersion({
        versionId: params.get("version_id"),
        manifestSha256: params.get("manifest_sha256"),
    });
}

export function historyMarketHref(identity?: HistoryBundleIdentity): string {
    return historyVersionPath("#market", identity);
}
