import { useEffect, useState } from "react";
import { MarketPage } from "../features/market/MarketPage";
import { OpportunityPage } from "../features/opportunities/OpportunityPage";
import { FullHistoryPage } from "../features/full-history/FullHistoryPage";
import { ResearchLibraryPage } from "../features/research/ResearchLibraryPage";
import { FundsPage } from "../features/funds/FundsPage";
import { WaveLabPage } from "../features/wave-lab/WaveLabPage";
import { sendHeartbeat } from "../api/client";
import { HomePage } from "../features/home/HomePage";
import { StrategyOverviewPage } from "../features/strategies/StrategyOverviewPage";
import { StrategyDetailPage } from "../features/strategies/StrategyDetailPage";
import { StrategyComparePage } from "../features/strategies/StrategyComparePage";
import { ResearchHistoryPage } from "../features/research-history/ResearchHistoryPage";
import { studioRoute, type StudioPage } from "./routes";
import "./studio.css";

export default function Studio() {
    const [route, setRoute] = useState(() => studioRoute(location.hash));
    const { page, runId } = route;
    const [palette, setPalette] = useState(() => {
        try {
            return localStorage.getItem("atlas.palette") ?? "forest";
        } catch {
            return "forest";
        }
    });
    const [appearance, setAppearance] = useState(() => {
        try {
            return localStorage.getItem("atlas.appearance") ?? "system";
        } catch {
            return "system";
        }
    });
    const [settings, setSettings] = useState(false);
    const [systemDark, setSystemDark] = useState(
        () => matchMedia("(prefers-color-scheme: dark)").matches,
    );
    const resolvedAppearance =
        appearance === "system" ? (systemDark ? "dark" : "light") : appearance;
    useEffect(() => {
        const query = matchMedia("(prefers-color-scheme: dark)");
        const update = () => setSystemDark(query.matches);
        query.addEventListener("change", update);
        return () => query.removeEventListener("change", update);
    }, []);
    useEffect(() => {
        const change = () => setRoute(studioRoute(location.hash));
        window.addEventListener("hashchange", change);
        return () => window.removeEventListener("hashchange", change);
    }, []);
    useEffect(() => {
        try {
            localStorage.setItem("atlas.palette", palette);
            localStorage.setItem("atlas.appearance", appearance);
        } catch {
            /* Storage may be unavailable in a private window. */
        }
        document.documentElement.style.colorScheme =
            resolvedAppearance === "dark" ? "dark" : "light";
    }, [palette, appearance, resolvedAppearance]);
    useEffect(() => {
        sendHeartbeat();
        const t = setInterval(sendHeartbeat, 5000);
        return () => clearInterval(t);
    }, []);
    const navigate = (p: StudioPage) => {
        location.hash = p;
        setRoute(studioRoute(p));
        window.scrollTo({ top: 0, behavior: "instant" });
    };
    return (
        <div
            className="studio"
            data-palette={palette}
            data-appearance={resolvedAppearance}
        >
            <a className="skip-link" href="#main-content">
                跳到主要內容
            </a>
            <header className="studio-header">
                <button
                    className="brand"
                    onClick={() => navigate("home")}
                    aria-label="研究與發現首頁"
                >
                    <span className="brand-mark">S</span>
                    <span>
                        STOCK <i>/</i> <small>研究與發現</small>
                    </span>
                </button>
                <nav aria-label="主選單">
                    {(
                        [
                            { id: "home", label: "首頁" },
                            { id: "market", label: "飆股地圖" },
                            { id: "strategies", label: "策略" },
                            { id: "compare", label: "比較" },
                            { id: "history", label: "研究歷程" },
                            { id: "funds", label: "ETF 圖鑑" },
                        ] as const
                    ).map((n) => (
                        <button
                            key={n.id}
                            aria-current={
                                page === n.id ||
                                (n.id === "strategies" && page === "strategy")
                                    ? "page"
                                    : undefined
                            }
                            onClick={() => navigate(n.id)}
                        >
                            {n.label}
                        </button>
                    ))}
                </nav>
                <div className="header-actions">
                    <button
                        className="theme-button"
                        aria-expanded={settings}
                        onClick={() => setSettings((v) => !v)}
                    >
                        <span className="palette-dot" />
                        視覺風格
                    </button>
                    <span className="profile-mark" aria-hidden="true">
                        S
                    </span>
                </div>
            </header>
            {settings && (
                <section className="theme-panel" aria-label="視覺風格設定">
                    <div>
                        <strong>讓這張地圖，成為你的風景。</strong>
                        <p>主色與明暗不改變資料或大小規則。</p>
                    </div>
                    <div className="palette-choices">
                        {[
                            { id: "forest", label: "霧林綠" },
                            { id: "ocean", label: "海霧藍" },
                            { id: "plum", label: "暮山紫" },
                            { id: "sand", label: "暖沙金" },
                        ].map((p) => (
                            <button
                                key={p.id}
                                data-choice={p.id}
                                aria-pressed={palette === p.id}
                                onClick={() => setPalette(p.id)}
                            >
                                <span />
                                {p.label}
                            </button>
                        ))}
                    </div>
                    <div className="segmented">
                        <button
                            aria-pressed={appearance === "system"}
                            onClick={() => setAppearance("system")}
                        >
                            隨系統
                        </button>
                        <button
                            aria-pressed={appearance === "light"}
                            onClick={() => setAppearance("light")}
                        >
                            日光
                        </button>
                        <button
                            aria-pressed={appearance === "dark"}
                            onClick={() => setAppearance("dark")}
                        >
                            夜色
                        </button>
                    </div>
                    <button
                        className="icon-button"
                        onClick={() => setSettings(false)}
                        aria-label="關閉視覺設定"
                    >
                        ×
                    </button>
                </section>
            )}
            <main id="main-content" className="studio-main">
                {page === "home" && <HomePage />}
                {page === "strategies" && <StrategyOverviewPage />}
                {page === "strategy" && runId && (
                    <StrategyDetailPage key={runId} runId={runId} />
                )}
                {page === "compare" && <StrategyComparePage />}
                {page === "history" && <ResearchHistoryPage />}
                <div hidden={page !== "market"}>
                    <FullHistoryPage active={page === "market"} />
                </div>
                {page === "market-preview" && <OpportunityPage active />}
                {page === "market-legacy" && (
                    <div>
                        <p className="op-notice">
                            舊版固定窗口視圖，選股定義與新的歷史波段目錄不同。
                        </p>
                        <MarketPage
                            active={page === "market-legacy"}
                            onResearch={() => navigate("research")}
                        />
                    </div>
                )}
                {page === "research" && <ResearchLibraryPage />}
                {page === "funds" && <FundsPage />}
                {page === "wave-lab" && <WaveLabPage />}
            </main>
            <footer className="studio-footer">
                <span className="footer-brand">
                    STOCK <i> / </i> 看見機會，也看見證據。
                </span>
                <a href="?legacy=1" target="_blank" rel="noreferrer">
                    原有 K 線工作台 ↗
                </a>
                <span>歷史觀察不等於當時可知的買賣訊號</span>
                <a href="#research">研究者工具</a>
            </footer>
        </div>
    );
}
