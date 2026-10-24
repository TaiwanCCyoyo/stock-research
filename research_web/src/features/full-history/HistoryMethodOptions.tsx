import { InfoTip } from "../../components/ui/InfoTip";
import { useEffect, useState } from "react";
import { readHistory } from "./api.ts";
import { HISTORY_SCHEMA, type HistoryOptions } from "./types.ts";
import { SourceInfo } from "../../components/ui/primitives.tsx";

export function HistoryMethodOptions({
    catalogId,
    date,
    onDate,
}: {
    catalogId: string;
    date: string;
    onDate: (date: string) => void;
}) {
    const [opened, setOpened] = useState(false);
    const [value, setValue] = useState<HistoryOptions | null>(null);
    const [error, setError] = useState("");
    useEffect(() => {
        if (!opened || !date) return;
        const controller = new AbortController();
        setValue(null);
        setError("");
        readHistory<HistoryOptions>(
            `/options?date=${encodeURIComponent(date)}`,
            controller.signal,
        )
            .then((data) => {
                if (controller.signal.aborted) return;
                if (
                    data.schema !== HISTORY_SCHEMA ||
                    data.catalogId !== catalogId ||
                    data.date !== date
                )
                    throw new Error("方案與目前地圖版本不一致");
                setValue(data);
            })
            .catch((cause) => {
                if (!controller.signal.aborted) setError(String(cause));
            });
        return () => controller.abort();
    }, [opened, date, catalogId]);
    return (
        <details
            className="fh-method-options u-source"
            onToggle={(e) => setOpened(e.currentTarget.open)}
        >
            <summary>查看原有波段方法的收錄範圍</summary>

            <div className="fh-controls">
                {["2014-06-30", "2021-04-29", "2024-06-28"].map((day) => (
                    <button
                        className="u-chip"
                        key={day}
                        onClick={() => onDate(day)}
                    >
                        {day.slice(0, 4)} 案例日
                    </button>
                ))}
            </div>
            {error ? (
                <div className="u-notice" role="alert">
                    <p>目前無法載入比較方案，請稍後重試。</p>
                    <SourceInfo label="錯誤詳情">{error}</SourceInfo>
                </div>
            ) : !value ? (
                <p role="status">正在讀取 {date} 的保存結果…</p>
            ) : (
                <div className="fh-option-grid">
                    {value.rows.map((row) => (
                        <div className="fh-option u-card" key={row.id}>
                            <strong>{row.label}</strong>
                            <b>{row.count.toLocaleString()} 檔</b>
                        </div>
                    ))}
                </div>
            )}
            <p className="fh-caption">
                這些檔數怎麼來
                <InfoTip label="這些檔數怎麼來">
                    這是各方法原本收錄的檔數，還沒套用本頁的年化／實際漲幅門檻。多年十倍的行情也留在目錄裡，是否畫進版圖另外判斷。
                </InfoTip>
            </p>
        </details>
    );
}
