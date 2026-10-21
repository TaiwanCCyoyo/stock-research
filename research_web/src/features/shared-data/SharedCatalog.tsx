import { useState } from "react";
import {
    groupCatalog,
    selectedCatalogVersion,
    metadataText,
    versionLabel,
    type CatalogEntry,
    type Families,
} from "./model";
const repository = "https://github.com/TaiwanCCyoyo/stock-research/blob/main/";
const contract = `${repository}docs/en/research-derived-data.md`;
const catalogGuide = `${repository}tasks/20261012-research-data-entry/data-contract.md`;
const assetIndex = `${repository}docs/en/research-program.md`;

function CatalogCard({ entries }: { entries: CatalogEntry[] }) {
    const [version, setVersion] = useState<string>();
    const entry = selectedCatalogVersion(entries, version);
    return (
        <article className="shared-card">
            <span className="shared-badge">
                {entry.kind} · {entry.status}
            </span>
            <h2>{entry.display_title || "資產索引未登記名稱"}</h2>
            <p>{entry.purpose || "資產索引未登記用途；請查閱資料契約。"}</p>
            <p className="shared-note">
                {entry.data_id} · {entries.length} 個版本
            </p>
            <label>
                檢視版本{" "}
                <select
                    value={entry.version_id}
                    onChange={(event) => setVersion(event.target.value)}
                >
                    {entries.map((item, i) => (
                        <option key={item.version_id} value={item.version_id}>
                            {i + 1} · {item.definition_version || "定義未提供"}{" "}
                            · {item.status}
                            {item.recommended === true ? " · 推薦" : ""}
                        </option>
                    ))}
                </select>
            </label>
            <strong>{versionLabel(entry)}</strong>
            <p>
                {entry.coverage?.raw_input_period?.start ?? "期間未提供"} –{" "}
                {entry.coverage?.raw_input_period?.end ?? "未提供"}
            </p>
            <p>
                涵蓋股票：
                {entry.viewer_metadata?.security_count != null
                    ? `${entry.viewer_metadata.security_count.toLocaleString()} 檔`
                    : "manifest 未提供"}
                {entry.viewer_metadata?.analyzed_security_count != null &&
                    `；已分析 ${entry.viewer_metadata.analyzed_security_count.toLocaleString()} 檔`}
            </p>
            <p>
                資料欄位：
                {entry.viewer_metadata?.columns?.join("、") ||
                    "manifest 未提供實體欄位清單"}
            </p>
            {entry.metadata_error && <p role="alert">{entry.metadata_error}</p>}
            <details>
                <summary>版本識別、定義、限制與取得位置</summary>
                <p>
                    版本：<code>{entry.version_id}</code>
                </p>
                <p>定義版本：{entry.definition_version ?? "未提供"}</p>
                <p>限制：{metadataText(entry.limitations)}</p>
                <p>完整涵蓋範圍：{metadataText(entry.coverage)}</p>
                <p>Manifest：{metadataText(entry.manifest)}</p>
                <p>
                    Manifest 成員檔案：
                    {entry.viewer_metadata?.manifest_member_count?.toLocaleString() ??
                        "未提供"}
                    ；此處只驗證 manifest 本身，未驗證或載入成員資料。
                </p>
            </details>
            <footer>
                <a href={catalogGuide} target="_blank" rel="noreferrer">
                    目錄取用契約 ↗
                </a>
                <a href={assetIndex} target="_blank" rel="noreferrer">
                    研究用途與各資料契約索引 ↗
                </a>
                <span>研究資料包，不支援 K 線</span>
            </footer>
        </article>
    );
}
export function SharedCatalog({
    data,
    onViewer,
}: {
    data: Families;
    onViewer: () => void;
}) {
    const [filter, setFilter] = useState("all");
    const groups = groupCatalog(data.catalog?.entries ?? []);
    return (
        <>
            <div className="shared-controls" aria-label="目錄篩選">
                {[
                    ["all", "全部"],
                    ["maintained", "持續維護"],
                    ["bundle", "研究資料包"],
                ].map(([value, label]) => (
                    <button
                        key={value}
                        aria-pressed={filter === value}
                        onClick={() => setFilter(value)}
                    >
                        {label}
                    </button>
                ))}
            </div>
            {data.catalogError && (
                <p role="alert">
                    研究資料目錄無法讀取：{data.catalogError}
                    ；下方仍可查看維護家族。
                </p>
            )}
            <div className="shared-catalog">
                {filter !== "bundle" &&
                    data.families.map((family) => (
                        <article className="shared-card" key={family.family}>
                            <span className="shared-badge">
                                現行世代 · 持續維護
                            </span>
                            <h2>
                                {family.display_title || "資產索引未登記名稱"}
                            </h2>
                            <p>
                                {family.purpose ||
                                    "資產索引未登記用途；請查閱資料契約。"}
                            </p>
                            <p className="shared-note">{family.family}</p>
                            <p>
                                {family.calendar.first} – {family.calendar.last}{" "}
                                · {family.codes.toLocaleString()} 檔 ·{" "}
                                {family.calendar.sessions.toLocaleString()}{" "}
                                交易日
                            </p>
                            <p>資料截至 {family.asof}</p>
                            <details>
                                <summary>世代識別、定義、欄位與基準</summary>
                                <p>
                                    使用版本：<code>{family.generation}</code>
                                </p>
                                <p>定義：{metadataText(family.definition)}</p>
                                <p>基準：{metadataText(family.bases)}</p>
                                <p>
                                    技術欄位：{metadataText(family.technical)}
                                </p>
                                <p>
                                    Status SHA-256：
                                    <code>{family.status_sha256}</code>
                                </p>
                            </details>
                            <footer>
                                <a
                                    href={contract}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    資料定義與維護說明 ↗
                                </a>
                                {family.family === "adjusted-daily-v1" && (
                                    <button onClick={onViewer}>
                                        在 K 線檢視
                                    </button>
                                )}
                            </footer>
                        </article>
                    ))}
                {filter !== "maintained" &&
                    groups.map(([id, entries]) => (
                        <CatalogCard key={id} entries={entries} />
                    ))}
            </div>
            <p className="shared-note">
                未標示現行版的資料包，不會依日期或名稱自動推定推薦版本；選單僅切換檢視內容。
            </p>
            <details>
                <summary>目錄快照識別</summary>
                <code>{data.catalog?.version_id ?? "不可讀"}</code>
            </details>
            {data.catalog && data.catalog.retired.length > 0 && (
                <details>
                    <summary>
                        已退役紀錄 ({data.catalog.retired.length})
                    </summary>
                    <pre>{JSON.stringify(data.catalog.retired, null, 2)}</pre>
                </details>
            )}
        </>
    );
}
