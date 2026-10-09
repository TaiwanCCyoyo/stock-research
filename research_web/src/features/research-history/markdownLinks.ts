/** Report-relative files have no website route; only complete HTTPS sources are navigable. */
export function researchLinkHref(href: string | undefined): string | null {
    if (!href || !/^https:\/\//i.test(href)) return null;
    try {
        const url = new URL(href);
        return url.protocol === "https:" && url.hostname ? url.href : null;
    } catch {
        return null;
    }
}
