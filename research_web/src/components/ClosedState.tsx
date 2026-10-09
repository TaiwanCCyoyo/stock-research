/** Full-screen replacement for the app shell once the dashboard server has stopped. */
export function ClosedState() {
    return (
        <div className="closed-state">
            <div className="closed-card">
                <div className="closed-icon" aria-hidden="true">
                    ⏻
                </div>
                <h1>Dashboard 已關閉</h1>
                <p>研究伺服器已停止，您可以安全關閉此瀏覽器分頁。</p>
            </div>
        </div>
    );
}
