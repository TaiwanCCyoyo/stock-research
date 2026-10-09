# Saved opportunity catalog publication

`scripts/rebuild_saved_opportunity_catalog.py` exports compact tables from saved,
verified native results. It never executes the numerical methods. Use a new
physical output directory; existing source artifacts and publications stay in place.

Publication requires Windows mandatory file-sharing guards. Other platforms are
rejected before source reads or output creation. Advisory POSIX locks cannot stop
writers that do not participate in that locking protocol. Existing catalog readers
and their authentication contracts retain their existing platform support.

During publication, the exporter holds native Windows handles that deny writes,
deletes and writable mappings to every pinned artifact. Ancestor directory guards
deny renaming or deleting the protected namespace. Reparse points are rejected;
use physical files and directories. File IDs and hashes must match the declared
identities. A filesystem that cannot supply the required guards or file IDs fails
publication rather than weakening these checks.

Hashing opens one temporary Python/CRT reader at a time, avoiding the descriptor
limit of a reader per artifact. Native guard handles still require resources
proportional to artifact count. If acquisition fails, all acquired handles are
released and no final manifest is published. The regression fixture covers 17,000
distinct artifacts with a limit of 32 simultaneous Python/CRT streams.

The exporter prepares and fsyncs the manifest in a private `.publication`
directory, authenticates its expected bytes, and creates the final name through
an exclusive atomic hard link. Guards remain held through final validation.
On failure, a native metadata anchor keeps the prepared object and file ID alive
after the strong read guards close. Retraction opens the final link with DELETE
access, verifies its native identity against the anchor and marks that link for
deletion through the same handle. A competing replacement is preserved; no
pathname deletion follows an identity check. The prepared alias and partial
evidence remain. If access or sharing restrictions prevent rollback, the original
exception carries a note identifying incomplete rollback; the exporter never
falls back to an unguarded deletion. Windows can defer removal while compatible
external metadata handles to that link remain open.

Success retains the staging alias as publication evidence. The exporter does not
delete that path after releasing its guards, because another writer could have
replaced the directory entry.

Guards end when the transaction finishes. Future external edits remain subject to
reader authentication. Historical input, native-result, method and published
manifest identities are not rewritten by this mechanism. Git metadata archives
remain an incomplete backup of the larger local research dataset.
