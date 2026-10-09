import type {
    OpportunityRow,
    SourceRef,
} from "../../domain/opportunities/types.ts";
import {
    classificationEvidence,
    classificationSourceHref,
    classificationSourceLabel,
} from "./classificationDisplay.ts";

const REFERENCE_LAYERS = {
    "official-value-chain": "官方產業鏈節點（參考）",
    "research-group": "研究分組（參考）",
    "business-role": "公司業務角色（參考）",
    "business-group": "業務群組（參考）",
    "business-sector": "業務領域（參考）",
};
const REFERENCE_TIMING = {
    snapshot:
        "這是後來保存的分類，當年是否適用還不確定，不用來判斷當年的族群。",
    "retrospective-period-summary":
        "依文件整理當年度業務；不能據此認定當時已經知道，也不是事前選股訊號。",
    "retrospective-event-context":
        "這一年發生的事件，不代表整年都屬於這個族群或持續經營這項業務。",
    "undated-reference": "還不知道適用年份，僅供參考。",
    "dated-profile-reference":
        "日期是資料頁標示的日期，不是分類或業務開始、結束的日期。",
};
const REFERENCE_PERIOD_LABEL = {
    snapshot: "參考記載期間",
    "retrospective-period-summary": "文件涵蓋期間",
    "retrospective-event-context": "事件所涉期間",
    "undated-reference": "參考記載期間",
    "dated-profile-reference": "資料頁日期",
};

function ClassificationSource({ source }: { source: SourceRef | null }) {
    const href = source ? classificationSourceHref(source) : null;
    return (
        <>
            <dt>來源／頁碼</dt>
            <dd>
                {classificationSourceLabel(source)}
                {href ? (
                    <>
                        {" "}
                        <a href={href} target="_blank" rel="noreferrer">
                            查看來源 ↗
                        </a>
                    </>
                ) : source?.url ? (
                    <> · 目前沒有可開啟的來源連結</>
                ) : null}
            </dd>
        </>
    );
}

export function ClassificationEvidence({
    row,
    sources,
}: {
    row: OpportunityRow;
    sources: readonly SourceRef[];
}) {
    const { group, snapshots, references } = classificationEvidence(
        row,
        sources,
    );
    const snapshotDetails = snapshots.map((snapshot, index) => (
        <dl key={`${snapshot.sourceId}:${index}`}>
            <dt>已知分類</dt>
            <dd>{snapshot.label}</dd>
            <dt>擷取時間</dt>
            <dd>{snapshot.observedAt ?? "未提供"}（非分類生效日）</dd>
            <ClassificationSource source={snapshot.source} />
        </dl>
    ));
    return (
        <details
            className="op-classification-evidence"
            style={{ overflowWrap: "anywhere", minWidth: 0 }}
        >
            <summary>分類來源</summary>
            {group ? (
                <>
                    <dl>
                        <dt>產業／業務族群</dt>
                        <dd>{group.label}</dd>
                        <dt>分組依據</dt>
                        <dd>
                            {group.basis === "document-period"
                                ? "依當年度年報整理"
                                : "已保存的歷史分類"}
                        </dd>
                        <dt>
                            {group.basis === "document-period"
                                ? "文件涵蓋期間"
                                : "已核對分類期間"}
                        </dt>
                        <dd>
                            {group.from} ～ {group.through ?? "未記載截止日"}
                            {group.through && "（含首尾日）"}
                        </dd>
                        <ClassificationSource source={group.source} />
                        {group.basis === "document-period" && (
                            <>
                                <dt>來源記載發布日</dt>
                                <dd>{group.source?.publishedAt ?? "未提供"}</dd>
                            </>
                        )}
                    </dl>
                    {group.basis === "document-period" && (
                        <p className="op-footnote">
                            這個族群是依年報整理的當年度業務。年報何時公開、正式分類何時生效還未確認，不能當成當時已知的選股依據。
                        </p>
                    )}
                </>
            ) : (
                <p className="op-footnote">
                    還沒有足夠資料確認當年的族群。下方的已知分類仍可供參考。
                </p>
            )}
            {snapshots.length > 0 && (
                <>
                    {snapshots.length > 1 ? (
                        <details>
                            <summary>
                                後來保存的分類 · {snapshots.length} 筆
                            </summary>
                            {snapshotDetails}
                        </details>
                    ) : (
                        snapshotDetails
                    )}
                    <p className="op-footnote">
                        這是後來保存的分類，當年歸屬仍待確認，不用來決定當年的族群。
                    </p>
                </>
            )}
            {Object.entries(REFERENCE_LAYERS).map(([layer, label]) => {
                const entries = references.filter(
                    (entry) => entry.layer === layer,
                );
                if (!entries.length) return null;
                return (
                    <details key={layer}>
                        <summary>
                            {label} · {entries.length} 項
                        </summary>
                        {entries.map((entry) => (
                            <section key={entry.id} aria-label={entry.label}>
                                <p>
                                    <strong>{entry.label}</strong>
                                </p>
                                <p className="op-footnote">
                                    {REFERENCE_TIMING[entry.temporalScope]}
                                </p>
                                <dl>
                                    <dt>
                                        {
                                            REFERENCE_PERIOD_LABEL[
                                                entry.temporalScope
                                            ]
                                        }
                                    </dt>
                                    <dd>
                                        {entry.from ?? "未提供"}
                                        {entry.through
                                            ? ` ～ ${entry.through}（含首尾日）`
                                            : entry.from &&
                                                entry.temporalScope !==
                                                    "dated-profile-reference"
                                              ? " ～ 截止日未提供"
                                              : ""}
                                    </dd>
                                    {entry.sources.length ? (
                                        entry.sources.map((binding) => (
                                            <ClassificationSource
                                                key={binding.sourceId}
                                                source={binding.source}
                                            />
                                        ))
                                    ) : (
                                        <>
                                            <dt>來源依據</dt>
                                            <dd>缺少可核對來源</dd>
                                        </>
                                    )}
                                </dl>
                            </section>
                        ))}
                    </details>
                );
            })}
            {references.length > 0 && (
                <p className="op-footnote">
                    同一家公司可能有多種業務，這些資料都保留供參考，不會自動選定主要業務；當天採用的族群依據列在上方。
                </p>
            )}
        </details>
    );
}
