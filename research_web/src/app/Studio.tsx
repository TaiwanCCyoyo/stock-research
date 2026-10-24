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
import { StudiesPage } from "../features/studies/StudiesPage";
import { ReportViewer } from "../features/report-library/ReportViewer";
import { SharedDataPage } from "../features/shared-data/SharedDataPage";
import { studioRoute, type StudioPage } from "./routes";
import { reportPalette, themeId, THEMES, type ThemeId } from "./themes";
import { PetalLayer } from "./PetalLayer";
import "./studio.css";
import "./themes.css";
import "./shell.css";
import "./ui.css";

const NAV: {
    id: StudioPage;
    label: string;
    icon: string;
    also?: StudioPage[];
}[] = [
    { id: "home", label: "首頁", icon: "M4 11.5 12 5l8 6.5V20h-5v-5H9v5H4z" },
    {
        id: "studies",
        label: "研究",
        icon: "M6 4h9l3 3v13H6zM9 10h6M9 14h6M9 18h4",
        also: ["strategies", "strategy", "compare", "report"],
    },
    {
        id: "market",
        label: "飆股地圖",
        icon: "M8 15a3 3 0 1 0 0-.01M15 9a4 4 0 1 0 0-.01M17 18a2 2 0 1 0 0-.01",
    },
    { id: "data", label: "個股", icon: "M4 19h16M7 16V9M12 16V5M17 16v-5" },
    {
        id: "funds",
        label: "ETF 圖鑑",
        icon: "M5 8h14l-1.5 11h-11zM9 8a3 3 0 0 1 6 0",
    },
];

function readSetting(key: string, fallback: string) {
    try {
        return localStorage.getItem(key) ?? fallback;
    } catch {
        return fallback;
    }
}

function Icon({ d }: { d: string }) {
    return (
        <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d={d} />
        </svg>
    );
}

export default function Studio() {
    const [route, setRoute] = useState(() => studioRoute(location.hash));
    const { page, runId, reportId } = route;
    const [palette, setPalette] = useState<ThemeId>(() =>
        themeId(readSetting("atlas.palette", "forest")),
    );
    const [appearance, setAppearance] = useState(() =>
        readSetting("atlas.appearance", "system"),
    );
    const [ambient, setAmbient] = useState(
        () => readSetting("atlas.ambient", "on") === "on",
    );
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
            localStorage.setItem("atlas.ambient", ambient ? "on" : "off");
        } catch {
            /* Storage may be unavailable in a private window. */
        }
        document.documentElement.style.colorScheme =
            resolvedAppearance === "dark" ? "dark" : "light";
    }, [palette, appearance, ambient, resolvedAppearance]);
    useEffect(() => {
        sendHeartbeat();
        const t = setInterval(sendHeartbeat, 5000);
        return () => clearInterval(t);
    }, []);
    useEffect(() => {
        if (!settings) return;
        const close = (event: KeyboardEvent) => {
            if (event.key === "Escape") setSettings(false);
        };
        window.addEventListener("keydown", close);
        return () => window.removeEventListener("keydown", close);
    }, [settings]);
    const navigate = (p: StudioPage) => {
        location.hash = p;
        setRoute(studioRoute(p));
        window.scrollTo({ top: 0, behavior: "instant" });
    };
    const current = (item: (typeof NAV)[number]) =>
        page === item.id || item.also?.includes(page) ? "page" : undefined;
    const navItems = (className: string) =>
        NAV.map((item) => (
            <a
                key={item.id}
                className={className}
                href={`#${item.id}`}
                aria-current={current(item)}
                onClick={(event) => {
                    event.preventDefault();
                    navigate(item.id);
                }}
            >
                <Icon d={item.icon} />
                <span>{item.label}</span>
            </a>
        ));
    return (
        <div
            className="studio"
            data-palette={palette}
            data-appearance={resolvedAppearance}
        >
            {palette === "sakura" && ambient && (
                <PetalLayer dark={resolvedAppearance === "dark"} />
            )}
            <a className="skip-link" href="#main-content">
                跳到主要內容
            </a>
            <header className="shell-header">
                <a
                    className="shell-brand"
                    href="#home"
                    onClick={(event) => {
                        event.preventDefault();
                        navigate("home");
                    }}
                    aria-label="STOCK 研究室首頁"
                >
                    <span className="shell-mark">S</span>
                    <span>STOCK 研究室</span>
                </a>
                <nav className="shell-nav" aria-label="主選單">
                    {navItems("shell-nav-link")}
                </nav>
                <button
                    className="shell-theme-button"
                    aria-expanded={settings}
                    aria-controls="theme-panel"
                    onClick={() => setSettings((v) => !v)}
                >
                    <span className="shell-theme-dot" />
                    主題
                </button>
            </header>
            {settings && (
                <>
                    <div
                        className="shell-scrim"
                        onClick={() => setSettings(false)}
                    />
                    <section
                        id="theme-panel"
                        className="shell-theme-panel"
                        aria-label="主題設定"
                    >
                        <div className="shell-theme-head">
                            <strong>挑一個你喜歡的樣子</strong>
                            <button
                                className="u-icon-button"
                                onClick={() => setSettings(false)}
                                aria-label="關閉主題設定"
                            >
                                ×
                            </button>
                        </div>
                        <div className="shell-theme-grid">
                            {THEMES.map((theme) => (
                                <button
                                    key={theme.id}
                                    className="shell-theme-choice"
                                    aria-pressed={palette === theme.id}
                                    onClick={() => setPalette(theme.id)}
                                >
                                    <span className="shell-swatch">
                                        {theme.swatch.map((color) => (
                                            <span
                                                key={color}
                                                style={{ background: color }}
                                            />
                                        ))}
                                    </span>
                                    {theme.label}
                                </button>
                            ))}
                        </div>
                        <p className="shell-theme-label">明暗</p>
                        <div className="u-segmented">
                            {[
                                ["system", "隨系統"],
                                ["light", "日光"],
                                ["dark", "夜色"],
                            ].map(([id, label]) => (
                                <button
                                    key={id}
                                    aria-pressed={appearance === id}
                                    onClick={() => setAppearance(id)}
                                >
                                    {label}
                                </button>
                            ))}
                        </div>
                        <p className="shell-theme-label">背景動畫</p>
                        <div className="u-segmented">
                            <button
                                aria-pressed={ambient}
                                onClick={() => setAmbient(true)}
                            >
                                開
                            </button>
                            <button
                                aria-pressed={!ambient}
                                onClick={() => setAmbient(false)}
                            >
                                關
                            </button>
                        </div>
                        <p className="u-muted shell-theme-note">
                            櫻花粉會有花瓣飄落。顏色只是好玩，不會改變任何數字。
                        </p>
                    </section>
                </>
            )}
            <main id="main-content" className="studio-main shell-main">
                {page === "home" && <HomePage />}
                {page === "studies" && <StudiesPage />}
                {page === "strategies" && <StrategyOverviewPage />}
                {page === "strategy" && runId && (
                    <StrategyDetailPage key={runId} runId={runId} />
                )}
                {page === "compare" && <StrategyComparePage />}
                {page === "data" && (
                    <SharedDataPage
                        code={route.code}
                        theme={`${reportPalette(palette)}:${resolvedAppearance}`}
                    />
                )}
                {page === "report" && reportId && (
                    <ReportViewer
                        key={reportId}
                        reportId={reportId}
                        palette={reportPalette(palette)}
                        appearance={resolvedAppearance}
                    />
                )}
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
            <footer className="shell-footer">
                <span>歷史統計，不是買賣訊號。</span>
                <span className="shell-footer-links">
                    <a href="#research">研究者工具</a>
                    <a href="?legacy=1" target="_blank" rel="noreferrer">
                        舊版 K 線工作台 ↗
                    </a>
                </span>
            </footer>
            <nav className="shell-tabbar" aria-label="主選單（手機）">
                {navItems("shell-tab")}
            </nav>
        </div>
    );
}
