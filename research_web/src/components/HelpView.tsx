/** Static usage/help view: artifact locations and re-run commands (spec requirement). */
export function HelpView() {
    return (
        <>
            <section className="panel">
                <h3 className="panel-title">資料位置</h3>
                <table className="data-table">
                    <tbody>
                        <tr>
                            <td style={{ color: "var(--text-muted)" }}>
                                任務產物
                            </td>
                            <td>
                                <code>tasks/&lt;任務id&gt;/</code> —
                                summary.json、summary_&lt;mode&gt;.json、comparison.json、stock_rankings.json、signal_events.json、strategy_diagnosis.md
                            </td>
                        </tr>
                        <tr>
                            <td style={{ color: "var(--text-muted)" }}>
                                回測 run 輸出
                            </td>
                            <td>
                                <code>
                                    tasks/&lt;任務id&gt;/runs/&lt;run名稱&gt;.json
                                </code>
                            </td>
                        </tr>
                        <tr>
                            <td style={{ color: "var(--text-muted)" }}>
                                策略檔
                            </td>
                            <td>
                                <code>
                                    tasks/&lt;任務id&gt;/candidates/*.py
                                </code>
                            </td>
                        </tr>
                        <tr>
                            <td style={{ color: "var(--text-muted)" }}>
                                價格資料
                            </td>
                            <td>
                                <code>shioaji_stock_prices/data/</code>（在{" "}
                                <code>shioaji_stock_prices/</code> 執行{" "}
                                <code>uv run python run_daily.py</code>{" "}
                                一鍵更新下載、轉檔、除權息與 parquet 快取）
                            </td>
                        </tr>
                    </tbody>
                </table>
            </section>
            <section className="panel">
                <h3 className="panel-title">重新回測（CLI）</h3>
                <pre className="log-tail">{`# 單一資金模式
uv run python -m scripts.run_task_backtest --task <任務id> \\
  --strategy candidates/<策略>.py --codes 2330,2454 \\
  --start 2024-01-01 --cash 1000000 --capital-mode shared

# 三種資金模式 + 比較（產生 comparison.json）
uv run python -m scripts.run_task_backtest --task <任務id> \\
  --strategy candidates/<策略>.py --codes 2330,2454 --capital-mode all

`}</pre>
            </section>
            <section className="panel">
                <h3 className="panel-title">啟動服務</h3>
                <pre className="log-tail">{`scripts\\research\\open_research_dashboard.cmd   # 研究工作台（本介面，port 8503）
scripts\\research\\open_research_api.cmd         # 只啟動唯讀 API（port 8503）

# 前端開發模式（hot reload）
cd research_web && npm run dev   # http://localhost:5173，/api 代理到 8503`}</pre>
            </section>
        </>
    );
}
