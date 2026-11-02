import { SourceInfo } from "../../components/ui/primitives";
import type { ReportIndexIssue } from "./model";

export function ReportIndexNotice({
    issue,
    error,
    loading,
    retry,
    reload,
}: {
    issue: ReportIndexIssue;
    error: string;
    loading: boolean;
    retry: () => void;
    reload: () => void;
}) {
    const mismatch = issue === "version_mismatch";
    return (
        <div role="status" className="u-notice rv-notice" aria-live="polite">
            <strong>
                {mismatch ? "頁面與報告資訊的版本不同" : "暫時無法確認報告資訊"}
            </strong>
            <p>
                {mismatch
                    ? "目前頁面和報告清單不是同一個版本，因此暫時無法確認報告的標題與日期。"
                    : issue === "invalid_index"
                      ? "收到的報告清單內容不完整或格式不符，因此暫時無法確認報告的標題與日期。"
                      : "報告資訊未能順利載入，因此暫時無法確認報告的標題與日期。"}
            </p>
            <p>
                如果下方已顯示報告，你仍可繼續閱讀；如果沒有內容，請先重試，或返回研究列表。
            </p>
            <div className="u-actions">
                <button
                    type="button"
                    className="u-btn u-btn-primary"
                    disabled={loading}
                    onClick={mismatch ? reload : retry}
                >
                    {loading
                        ? "正在重新讀取…"
                        : mismatch
                          ? "重新整理頁面"
                          : "重新讀取報告資訊"}
                </button>
                <a className="u-btn" href="#studies">
                    返回研究列表
                </a>
            </div>
            <p className="u-muted">
                重試後仍出現這個提示，請提供頁面網址與下方錯誤詳情，以便檢查。
            </p>
            <SourceInfo label="查看錯誤詳情">
                <p>{error}</p>
            </SourceInfo>
        </div>
    );
}
