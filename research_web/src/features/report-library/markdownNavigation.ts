interface MarkdownNode {
    type: string;
    tagName?: string;
    value?: string;
    properties?: Record<string, unknown>;
    children?: MarkdownNode[];
}

function text(node: MarkdownNode): string {
    return node.value ?? node.children?.map(text).join("") ?? "";
}

/** Unicode headings retain readable fragments; repeats use -1, -2, etc.
 * Existing suffixed headings also reserve their IDs, preventing collisions. */
export function headingSlug(value: string): string {
    return value
        .trim()
        .toLowerCase()
        .replace(/[^\p{L}\p{N}\p{M}_\s-]/gu, "")
        .replace(/\s/g, "-");
}

export function markdownHeadingIds({ prefix }: { prefix: string }) {
    return (tree: MarkdownNode) => {
        const used = new Set<string>();
        function visit(node: MarkdownNode) {
            if (node.tagName && /^h[1-6]$/.test(node.tagName)) {
                const base = headingSlug(text(node));
                let slug = base;
                let suffix = 0;
                while (used.has(slug)) slug = `${base}-${++suffix}`;
                used.add(slug);
                node.properties = {
                    ...node.properties,
                    id: `${prefix}${slug}`,
                    tabIndex: -1,
                };
            }
            node.children?.forEach(visit);
        }
        visit(tree);
    };
}

export function markdownFragmentId(
    href: string | undefined,
    prefix: string,
): string | null {
    if (!href?.startsWith("#") || href.length > 4096) return null;
    try {
        const fragment = decodeURIComponent(href.slice(1));
        if (
            !fragment ||
            Array.from(fragment).some(
                (character) =>
                    character.charCodeAt(0) < 32 ||
                    character.charCodeAt(0) === 127,
            )
        )
            return null;
        return `${prefix}${fragment}`;
    } catch {
        return null;
    }
}

/** Does not write location/hash: report routing and its return filters survive. */
export function scrollMarkdownFragment(
    href: string | undefined,
    prefix: string,
    find: (id: string) => {
        scrollIntoView(): void;
        focus(options: { preventScroll: boolean }): void;
    } | null,
): boolean {
    const id = markdownFragmentId(href, prefix);
    const target = id ? find(id) : null;
    if (!target) return false;
    target.scrollIntoView();
    target.focus({ preventScroll: true });
    return true;
}

export function imageUnavailableLabel(alt: string | undefined): string {
    return `${alt ? `圖像：${alt}` : "原文圖像"}（目前閱讀器不顯示圖片；閱讀版與來源原文皆僅顯示文字）`;
}
