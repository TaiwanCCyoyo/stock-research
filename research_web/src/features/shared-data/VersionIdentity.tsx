import { compactVersionLabel } from "./model";

export function VersionIdentity({ version }: { version: string }) {
    const label = compactVersionLabel(version);
    if (label === version) return <span>版本：{version}</span>;
    return (
        <details>
            <summary>版本：{label}（展開完整識別）</summary>
            <p>
                完整版本：<code>{version}</code>
            </p>
        </details>
    );
}
