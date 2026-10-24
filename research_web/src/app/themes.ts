export const THEMES = [
    {
        id: "forest",
        label: "霧林綠",
        swatch: ["#f2f5f1", "#2c6753", "#a9c9af", "#0f1814"],
    },
    {
        id: "ocean",
        label: "海霧藍",
        swatch: ["#eff4f8", "#2a6385", "#a8ccd2", "#0b1520"],
    },
    {
        id: "sakura",
        label: "櫻花粉",
        swatch: ["#fdf2f5", "#d2507f", "#f7b6cc", "#1b0f15"],
    },
    {
        id: "plum",
        label: "星夜紫",
        swatch: ["#f5f3fa", "#6b4fb8", "#c6b6e6", "#0f0c1c"],
    },
    {
        id: "sand",
        label: "暖沙金",
        swatch: ["#f8f4ec", "#8a6424", "#d7c29e", "#16120b"],
    },
    {
        id: "soda",
        label: "檸檬汽水",
        swatch: ["#f6faea", "#4d8a0e", "#d2ec8e", "#10140a"],
    },
    {
        id: "sunset",
        label: "夕陽橘",
        swatch: ["#fff4ec", "#c4500c", "#f8bd94", "#1a0f09"],
    },
    {
        id: "ink",
        label: "墨色極簡",
        swatch: ["#f6f6f4", "#262626", "#c8c8c4", "#0e0e0e"],
    },
] as const;

export type ThemeId = (typeof THEMES)[number]["id"];

export function themeId(value: string | null): ThemeId {
    return THEMES.some((theme) => theme.id === value)
        ? (value as ThemeId)
        : "forest";
}

/** Published web reports pin report-kit v1, which knows only four palettes. */
const REPORT_PALETTE: Record<ThemeId, "forest" | "ocean" | "plum" | "sand"> = {
    forest: "forest",
    ocean: "ocean",
    plum: "plum",
    sand: "sand",
    sakura: "plum",
    soda: "forest",
    sunset: "sand",
    ink: "forest",
};
export function reportPalette(theme: ThemeId) {
    return REPORT_PALETTE[theme];
}
