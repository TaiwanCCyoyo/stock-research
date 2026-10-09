import { useRef, useState } from "react";
import { validateBundle } from "../../domain/opportunities/model.ts";
import type { OpportunityBundle } from "../../domain/opportunities/types.ts";

function download(value: unknown, filename: string) {
    const url = URL.createObjectURL(
        new Blob([JSON.stringify(value, null, 2)], {
            type: "application/json",
        }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    setTimeout(() => URL.revokeObjectURL(url), 2000);
}

/** Complete source metadata stays available outside the reader's main workflow. */
export function OpportunityTools({
    bundle,
    date,
    evidence,
    onImport,
    onNotice,
    loadError,
}: {
    bundle: OpportunityBundle;
    date: string;
    evidence: () => unknown;
    onImport: (bundle: OpportunityBundle) => void;
    onNotice: (text: string) => void;
    loadError: string;
}) {
    const fileRef = useRef<HTMLInputElement>(null);
    const [exportText, setExportText] = useState("");
    return (
        <details className="op-card op-provenance-details op-research-tools">
            <summary>研究者工具</summary>
            <p>匯入、匯出與完整技術紀錄；一般瀏覽不需要使用這些工具。</p>
            <div className="op-tool-actions">
                <button onClick={() => fileRef.current?.click()}>
                    匯入資料包
                </button>
                <button onClick={() => download(bundle, `${bundle.id}.json`)}>
                    匯出完整資料包
                </button>
                <button
                    onClick={() => {
                        const data = evidence();
                        setExportText(JSON.stringify(data, null, 2));
                        download(data, `opportunity-${date}.json`);
                    }}
                >
                    匯出／複製比較紀錄
                </button>
            </div>
            <input
                ref={fileRef}
                type="file"
                accept="application/json,.json"
                hidden
                onChange={async (event) => {
                    const input = event.currentTarget;
                    const file = input.files?.[0];
                    if (!file) return;
                    try {
                        if (file.size > 50_000_000)
                            throw new Error(
                                "資料包超過 50 MB，請使用研究端分段輸出。",
                            );
                        onImport(validateBundle(JSON.parse(await file.text())));
                        onNotice("已開啟資料包。");
                    } catch (error) {
                        onNotice(
                            error instanceof Error
                                ? error.message
                                : "資料包格式不符",
                        );
                    } finally {
                        input.value = "";
                    }
                }}
            />
            {exportText && (
                <div className="op-export">
                    <p>這是上次匯出時的紀錄；日期與比較對象以紀錄內容為準。</p>
                    <label>
                        完整比較紀錄
                        <textarea
                            aria-label="可複製的查證 JSON"
                            readOnly
                            value={exportText}
                        />
                    </label>
                    <button onClick={() => setExportText("")}>關閉紀錄</button>
                </div>
            )}
            <details>
                <summary>原始資料限制與辨識設定</summary>
                {loadError && <p>{loadError}</p>}
                <pre>
                    {JSON.stringify(
                        {
                            id: bundle.id,
                            ruleVersion: bundle.ruleVersion,
                            selectionPolicy: bundle.selectionPolicy,
                            limitations: bundle.limitations,
                            priceBasis: bundle.priceBasis,
                            sources: bundle.sources,
                        },
                        null,
                        2,
                    )}
                </pre>
            </details>
        </details>
    );
}
