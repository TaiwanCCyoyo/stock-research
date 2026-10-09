import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { researchLinkHref } from "./markdownLinks";

/** Saved report prose is Markdown; render its emphasis without changing its claims. */
export function ResearchMarkdown({
    text,
    preview = false,
}: {
    text: string;
    preview?: boolean;
}) {
    return (
        <div className={`ss-markdown${preview ? " ss-markdown-preview" : ""}`}>
            <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                skipHtml
                components={{
                    a: ({ href, children }) => {
                        const source = researchLinkHref(href);
                        return source ? (
                            <a href={source} target="_blank" rel="noreferrer">
                                {children}
                            </a>
                        ) : (
                            <span title={href}>{children}</span>
                        );
                    },
                }}
            >
                {text}
            </ReactMarkdown>
        </div>
    );
}
