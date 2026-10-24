/** Shown above study cards kept from an earlier read when a refresh failed,
 *  with a retry that re-reads the research cards themselves. */
export function StudiesRefreshNotice({ onRetry }: { onRetry: () => void }) {
    return (
        <div className="u-notice st-partial" role="status">
            研究卡片暫時無法更新，下面是稍早讀到的內容。
            <button type="button" className="u-btn st-retry" onClick={onRetry}>
                重新讀取
            </button>
        </div>
    );
}
