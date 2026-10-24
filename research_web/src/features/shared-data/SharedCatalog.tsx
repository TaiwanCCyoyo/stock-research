import { useState } from "react";
import { SourceInfo } from "../../components/ui/primitives";
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
        <article className="u-card shared-card">
            <span className="shared-badge">研究資料包</span>
            <h2>{entry.display_title || "研究資料"}</h2>
            {entries.length > 1 && (
                <label>
                    檢視內容{" "}
                    <select
                        value={entry.version_id}
                        onChange={(event) => setVersion(event.target.value)}
                    >
                        {entries.map((item, i) => (
                            <option
                                key={item.version_id}
                                value={item.version_id}
                            >
                                資料 {i + 1}
                                {item.recommended === true ? " · 建議選用" : ""}
                            </option>
                        ))}
                    </select>
                </label>
            )}
            <p>
                {entry.coverage?.raw_input_period?.start ?? "期間未提供"} –{" "}
                {entry.coverage?.raw_input_period?.end ?? "未提供"}
            </p>
            <p>
                涵蓋股票：
                {entry.viewer_metadata?.security_count != null
                    ? `${entry.viewer_metadata.security_count.toLocaleString()} 檔`
                    : "未提供"}
                {entry.viewer_metadata?.analyzed_security_count != null &&
                    `；已分析 ${entry.viewer_metadata.analyzed_security_count.toLocaleString()} 檔`}
            </p>
            <p className="shared-note">
                研究資料包，請先確認適用範圍與研究限制。
            </p>
            {entry.metadata_error && (
                <p role="alert">資料說明暫時無法讀取，請查看來源資訊。</p>
            )}
            <SourceInfo>
                <p>用途：{entry.purpose || "未提供"}</p>
                <p>
                    資料欄位：
                    {entry.viewer_metadata?.columns?.join("、") ||
                        "未提供欄位清單"}
                </p>
                {entry.metadata_error && <p>{entry.metadata_error}</p>}
                <p className="shared-note">
                    {entry.data_id} · {entries.length} 個版本
                </p>
                <strong>{versionLabel(entry)}</strong>
                <p>
                    類型與狀態：{entry.kind} · {entry.status}
                </p>
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
            </SourceInfo>
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
            <div className="shared-controls u-chips" aria-label="目錄篩選">
                {[
                    ["all", "全部"],
                    ["maintained", "持續維護"],
                    ["bundle", "研究資料包"],
                ].map(([value, label]) => (
                    <button
                        className="u-chip"
                        key={value}
                        aria-pressed={filter === value}
                        onClick={() => setFilter(value)}
                    >
                        {label}
                    </button>
                ))}
            </div>
            {data.catalogError && (
                <div role="alert" className="u-notice">
                    <p>研究資料包暫時無法讀取；仍可查看持續維護的資料。</p>
                    <SourceInfo>
                        <p>{data.catalogError}</p>
                    </SourceInfo>
                </div>
            )}
            <div className="shared-catalog">
                {filter !== "bundle" &&
                    data.families.map((family) => (
                        <article
                            className="u-card shared-card"
                            key={family.family}
                        >
                            <span className="shared-badge">持續維護</span>
                            <h2>{family.display_title || "研究資料"}</h2>
                            <p>
                                {family.calendar.first} – {family.calendar.last}{" "}
                                · {family.codes.toLocaleString()} 檔 ·{" "}
                                {family.calendar.sessions.toLocaleString()}{" "}
                                交易日
                            </p>
                            <p>資料截至 {family.asof}</p>
                            <SourceInfo>
                                <p>資料家族：{family.family}</p>
                                <p>用途：{family.purpose || "未提供"}</p>
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
                            </SourceInfo>
                            <footer>
                                <a
                                    href={contract}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    資料定義與維護說明 ↗
                                </a>
                                {family.family === "adjusted-daily-v1" && (
                                    <button
                                        className="u-btn"
                                        onClick={onViewer}
                                    >
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
                資料包若未標示推薦內容，請先查看來源說明；選單只切換顯示內容。
            </p>
            <SourceInfo>
                <p>目錄快照識別</p>
                <code>{data.catalog?.version_id ?? "不可讀"}</code>
            </SourceInfo>
            {data.catalog && data.catalog.retired.length > 0 && (
                <SourceInfo
                    label={`已退役資料來源（${data.catalog.retired.length}）`}
                >
                    <pre>{JSON.stringify(data.catalog.retired, null, 2)}</pre>
                </SourceInfo>
            )}
        </>
    );
}
