/** Shared API root for the regular client and optional private viewers. */
export function apiUrl(
    path: string,
    base: string = import.meta.env?.VITE_API_BASE ?? "/api",
): string {
    return `${base.replace(/\/+$/, "")}/${path.replace(/^\/+/, "")}`;
}
