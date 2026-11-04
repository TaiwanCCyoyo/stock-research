import type {
    ComparisonView,
    Selection,
    TraceReference,
    WindowView,
} from "./model";

const statusNames: Record<string, string> = {
    known: "已知",
    feature_unknown: "條件未知",
    not_applicable: "不適用",
};
function References({ references }: { references: readonly TraceReference[] }) {
    return references.length ? (
        <ul>
            {references.map((ref) => (
                <li key={ref.event_id}>
                    {ref.security_id} · {ref.t0} · H{ref.horizon} ·{" "}
                    {ref.event_id}
                </li>
            ))}
        </ul>
    ) : (
        <p>此分區未提供追溯指標。</p>
    );
}
export function L1Evidence({
    window,
    selection,
}: {
    window: WindowView;
    selection: Selection;
}) {
    return (
        <section aria-label="L1 條件不可用分區與追溯指標">
            <h3>條件不可用的八種分區</h3>
            <p>
                這些事件仍屬共同母體；條件未知與不適用不會放進「沒有量縮／沒有放量」的格子。
            </p>
            <div className="cc-table-scroll">
                <table>
                    <thead>
                        <tr>
                            <th>G／VOL_a 狀態</th>
                            <th>事件數</th>
                            <th>命中／已知分母</th>
                            <th>股票數</th>
                            <th>unknown／censored</th>
                            <th>保存明細</th>
                        </tr>
                    </thead>
                    <tbody>
                        {window.unavailable?.map((item) => (
                            <tr key={item.id}>
                                <th scope="row">
                                    {statusNames[item.GStatus]}／
                                    {statusNames[item.volStatus]}
                                </th>
                                <td>{item.summary.saved?.event_n}</td>
                                <td>
                                    {item.summary.counts?.hit}／
                                    {item.summary.counts?.known}
                                </td>
                                <td>{item.summary.counts?.stocks}</td>
                                <td>
                                    {item.summary.counts?.unknown}／
                                    {item.summary.counts?.censored}
                                </td>
                                <td>
                                    <details>
                                        <summary>
                                            原因、完整計數與追溯指標
                                        </summary>
                                        <p>
                                            {item.summary.status ===
                                            "not-evaluated"
                                                ? "尚未評估"
                                                : "歷史描述"}{" "}
                                            · {item.summary.reason}
                                        </p>
                                        <pre>
                                            {JSON.stringify(
                                                {
                                                    reason_counts: item.reasons,
                                                    summary: item.summary.saved,
                                                },
                                                null,
                                                2,
                                            )}
                                        </pre>
                                        <References
                                            references={item.references}
                                        />
                                    </details>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>
            <h3>保存的追溯指標</h3>
            <p>
                每個分區最多三筆、依固定順序選取；不是完整或代表性案例，沒有結果標籤，也沒有可開啟的個案
                reader。
            </p>
            {selection.group === "all" ? (
                <p>
                    選擇其中一格可查看該格指標；共同母體沒有另外提供完整案例清單。
                </p>
            ) : (
                <References
                    references={window.references?.[selection.group] ?? []}
                />
            )}
        </section>
    );
}
export function L1Provenance({
    producer,
}: {
    producer: NonNullable<ComparisonView["producer"]>;
}) {
    return (
        <details>
            <summary>Producer 契約、完整來源與分母語意</summary>
            <p>
                {producer.schemaVersion} · {producer.scope}
                。結構檢查只核對送入資料，不能證明真實市場來源或驗收批准。
            </p>
            <pre>
                {JSON.stringify(
                    {
                        provenance: producer.provenance,
                        semantics: producer.semantics,
                    },
                    null,
                    2,
                )}
            </pre>
        </details>
    );
}
