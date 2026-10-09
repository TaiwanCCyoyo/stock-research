import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

interface DiagnosisViewProps {
    markdown: string;
}

export function DiagnosisView({ markdown }: DiagnosisViewProps) {
    return (
        <section className="panel">
            <div className="markdown-body">
                <ReactMarkdown
                    remarkPlugins={[remarkGfm]}
                    components={{
                        table: ({ children }) => (
                            <div className="table-wrap">
                                <table>{children}</table>
                            </div>
                        ),
                    }}
                >
                    {markdown}
                </ReactMarkdown>
            </div>
        </section>
    );
}
