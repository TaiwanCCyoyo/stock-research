import { useEffect, useState } from "react";
import { readHistory } from "./api.ts";
import { HISTORY_SCHEMA, type HistoryOptions } from "./types.ts";

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
            className="fh-method-options"
            onToggle={(e) => setOpened(e.currentTarget.open)}
        >
            <summary>查看原有波段方法的收錄範圍</summary>
            <p>
                這裡是保存方法的原始檔數，尚未套用本頁的年化／短波實際漲幅遮罩。完整行情、候選開始日與事後最高漲幅是不同條件。
            </p>
            <div className="fh-controls">
                {["2014-06-30", "2021-04-29", "2024-06-28"].map((day) => (
                    <button key={day} onClick={() => onDate(day)}>
                        {day.slice(0, 4)} 案例日
                    </button>
                ))}
            </div>
            {error ? (
                <p role="alert">暫時無法比較方案：{error}</p>
            ) : !value ? (
                <p role="status">正在讀取 {date} 的保存結果…</p>
            ) : (
                <div className="fh-option-grid">
                    {value.rows.map((row) => (
                        <div className="fh-option" key={row.id}>
                            <strong>{row.label}</strong>
                            <b>{row.count.toLocaleString()} 檔</b>
                        </div>
                    ))}
                </div>
            )}
            <p className="fh-caption">
                多年十倍行情仍保留在目錄；是否畫入版圖，由目前時間調整指標與門檻另行判斷。
            </p>
        </details>
    );
}
