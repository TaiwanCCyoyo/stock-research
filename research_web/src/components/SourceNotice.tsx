import { snapshotDescription, type SnapshotSource } from "./sourceMetadata";

export function SourceNotice({
    source,
    history = false,
}: {
    source?: SnapshotSource;
    history?: boolean;
}) {
    return (
        <p
            className="ss-muted"
            title={source ? `${source.schema} · ${source.version}` : undefined}
        >
            {snapshotDescription(source, history)}
        </p>
    );
}
