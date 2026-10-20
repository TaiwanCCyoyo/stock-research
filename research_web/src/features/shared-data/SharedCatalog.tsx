import { useState } from "react";
import { metadataText, versionLabel, type Families } from "./model";

const contract =
    "https://github.com/TaiwanCCyoyo/stock-research/blob/main/docs/en/research-derived-data.md";
const catalogGuide =
    "https://github.com/TaiwanCCyoyo/stock-research/blob/main/tasks/20261012-research-data-entry/data-contract.md";
const assetIndex =
    "https://github.com/TaiwanCCyoyo/stock-research/blob/main/docs/en/research-program.md";
export function SharedCatalog({
    data,
    onViewer,
}: {
    data: Families;
    onViewer: () => void;
}) {
    const [filter, setFilter] = useState("all");
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
                            <h2>{family.family}</h2>
                            <p>
                                {family.family === "adjusted-daily-v1"
                                    ? "查看個股原始與還原 OHLCV、每日技術指標、已確認高低點與資料品質。"
                                    : "依此家族的資料定義查閱可用內容。"}
                            </p>
                            <p>
                                {family.calendar.first} – {family.calendar.last}{" "}
                                · {family.codes.toLocaleString()} 檔 ·{" "}
                                {family.calendar.sessions.toLocaleString()}{" "}
                                交易日
                            </p>
                            <p>
                                使用版本：<code>{family.generation}</code> ·
                                截至 {family.asof}
                            </p>
                            <details>
                                <summary>定義、欄位與基準</summary>
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
                    data.catalog?.entries.map((entry) => (
                        <article
                            className="shared-card"
                            key={`${entry.data_id}:${entry.version_id}`}
                        >
                            <span className="shared-badge">
                                {entry.kind} · {entry.status}
                            </span>
                            <h2>{entry.data_id}</h2>
                            <p>
                                {entry.coverage?.scope ||
                                    "目錄未提供用途摘要；請查閱資料說明。"}
                            </p>
                            <p>
                                {entry.coverage?.raw_input_period?.start ??
                                    "期間未提供"}{" "}
                                –{" "}
                                {entry.coverage?.raw_input_period?.end ??
                                    "未提供"}
                            </p>
                            <p>
                                <strong>{versionLabel(entry)}</strong>
                            </p>
                            <p>
                                版本：<code>{entry.version_id}</code>
                            </p>
                            <details>
                                <summary>定義、限制與取得位置</summary>
                                <p>
                                    定義版本：
                                    {entry.definition_version ?? "未提供"}
                                </p>
                                <p>限制：{metadataText(entry.limitations)}</p>
                                <p>
                                    完整涵蓋範圍：{metadataText(entry.coverage)}
                                </p>
                                <p>Manifest：{metadataText(entry.manifest)}</p>
                                <p>
                                    欄位與檔數請依該版本
                                    manifest／資料說明核對；此目錄摘要不提供逐日行情。
                                </p>
                            </details>
                            <footer>
                                <a
                                    href={catalogGuide}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    目錄取用契約 ↗
                                </a>
                                <a
                                    href={assetIndex}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    研究用途與各資料契約索引 ↗
                                </a>
                                <span>研究資料包，不支援 K 線</span>
                            </footer>
                        </article>
                    ))}
            </div>
            <p className="shared-note">
                目錄版本：{data.catalog?.version_id ?? "不可讀"}
                。未標示現行版的資料包，不會依日期或名稱自動推定推薦版本。
            </p>
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
