/** Studio-owned tokens read from the computed theme root. */
export const STUDIO_THEME_TOKEN_NAMES = [
    "--paper",
    "--surface",
    "--surface-2",
    "--ink",
    "--muted",
    "--line",
    "--chip",
    "--accent",
    "--accent-soft",
    "--positive",
    "--gain",
    "--loss",
    "--cell-light",
    "--cell-mid",
    "--cell-deep",
    "--cell-warm",
    "--membrane",
    "--highlight",
    "--card-border",
    "--on-accent",
    "--warn",
] as const;

/** Every root-level color token declared by report-kit v1. */
export const REPORT_KIT_COLOR_TOKEN_NAMES = [
    "--gain",
    "--gain-soft",
    "--loss",
    "--loss-soft",
    "--paper",
    "--surface",
    "--surface-2",
    "--ink",
    "--muted",
    "--faint",
    "--line",
    "--line-strong",
    "--accent",
    "--accent-soft",
    "--warn",
    "--warn-soft",
    "--cell-light",
    "--cell-mid",
    "--cell-deep",
    "--compare",
    "--compare-soft",
] as const;

/** Studio tokens plus derived report-kit colors; only these can be injected. */
export const REPORT_THEME_TOKEN_NAMES = [
    ...STUDIO_THEME_TOKEN_NAMES,
    "--gain-soft",
    "--loss-soft",
    "--faint",
    "--line-strong",
    "--warn-soft",
    "--compare",
    "--compare-soft",
] as const;

export type ReportThemeTokenName = (typeof REPORT_THEME_TOKEN_NAMES)[number];
export type ReportThemeTokens = Partial<Record<ReportThemeTokenName, string>>;
export type ReportFrameThemeState = "loading" | "ready" | "fallback";

const REQUIRED_STUDIO_TOKENS: readonly (typeof STUDIO_THEME_TOKEN_NAMES)[number][] =
    [
        "--paper",
        "--surface",
        "--ink",
        "--muted",
        "--line",
        "--accent",
        "--accent-soft",
        "--warn",
    ];

const DERIVED_REPORT_TOKENS: Pick<
    ReportThemeTokens,
    | "--gain-soft"
    | "--loss-soft"
    | "--faint"
    | "--line-strong"
    | "--warn-soft"
    | "--compare"
    | "--compare-soft"
> = {
    "--gain-soft": "color-mix(in srgb, var(--gain) 14%, transparent)",
    "--loss-soft": "color-mix(in srgb, var(--loss) 14%, transparent)",
    "--faint": "color-mix(in srgb, var(--muted) 70%, var(--surface))",
    "--line-strong": "color-mix(in srgb, var(--line) 60%, var(--ink))",
    "--warn-soft": "color-mix(in srgb, var(--warn) 14%, var(--surface))",
    // Muted remains visually separate from accent in all Studio themes and
    // preserves the report kit's comparison role without a palette lookup.
    "--compare": "var(--muted)",
    "--compare-soft": "color-mix(in srgb, var(--compare) 18%, transparent)",
};

function safeCssValue(value: string): string | null {
    const normalized = value.trim();
    if (
        !normalized ||
        normalized.length > 256 ||
        /[;{}\u0000-\u001f]/.test(normalized)
    )
        return null;
    return normalized;
}

/** Copy only named semantic theme values from a computed-style reader. */
export function readReportThemeTokens(
    readValue: (name: string) => string,
): ReportThemeTokens | null {
    const tokens: ReportThemeTokens = {};
    for (const name of STUDIO_THEME_TOKEN_NAMES) {
        const value = safeCssValue(readValue(name));
        if (value) tokens[name] = value;
    }
    if (!REQUIRED_STUDIO_TOKENS.every((name) => tokens[name])) return null;
    return { ...tokens, ...DERIVED_REPORT_TOKENS };
}

export function applyReportThemeTokens(
    style: Pick<CSSStyleDeclaration, "setProperty">,
    tokens: ReportThemeTokens,
): void {
    for (const name of REPORT_THEME_TOKEN_NAMES) {
        const value = tokens[name];
        if (value) style.setProperty(name, value);
    }
}

export function reportThemeMessage(
    appearance: string,
    tokens: ReportThemeTokens,
) {
    return {
        type: "rk:theme",
        // report-kit v1 keeps a supported standalone fallback; host tokens carry
        // the selected Studio palette without maintaining report palette branches.
        palette: "forest",
        appearance,
        tokens,
    } as const;
}

/** Keep wrong-theme first paint hidden, but expose the built-in fallback on error. */
export function reportFrameThemeView(state: ReportFrameThemeState) {
    return {
        hidden: state === "loading",
        showFallback: state === "fallback",
    } as const;
}
