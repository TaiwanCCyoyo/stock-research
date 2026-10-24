import { SourceInfo } from "./ui/primitives";
import { snapshotDescription, type SnapshotSource } from "./sourceMetadata";

/** Demo data stays visibly labelled; private provenance is collapsed. */
export function SourceNotice({
    source,
    history = false,
}: {
    source?: SnapshotSource;
    history?: boolean;
}) {
    return (
        <div className="u-source-notice">
            {source?.mode === "public-synthetic" && (
                <p className="u-notice">示範資料，不是真實研究結果。</p>
            )}
            <SourceInfo>{snapshotDescription(source, history)}</SourceInfo>
        </div>
    );
}
