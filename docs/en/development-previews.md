# Dashboard development previews

The Dashboard's **開發預覽** button lists explicitly registered development
checkouts. Selecting a project opens its page in a separate tab. The normal
desktop shortcut continues to use the primary checkout; it never points at a
temporary worktree.

## Ownership and data

Each preview uses the frontend and API from the same registered worktree. Both
read the primary checkout's configured external data through the existing
resolvers. Reports and study cards come from the selected branch's `tasks/`;
their differences from main are intentional. Shared data is never copied or
linked into a worktree. Opening a preview does not run research or acquire data.

Registration is local machine state under the primary checkout's ignored
`.tmp/development-previews/`, not tracked project configuration. A stable project
ID survives changes of worktree location. Register the new location explicitly;
never guess a replacement from a similar directory name. The service validates
Git membership and the registered branch again when opening an entry.

## Session workflow

Prepare the worktree's normal dependencies, then use the CLI from a checkout
containing preview support. Run `python -m scripts.development_preview --help`
for the supported arguments. Register a meaningful title, stable ID, worktree,
optional PR number and a local hash route such as `#report/<task-id>`.

```powershell
python -m scripts.development_preview register --id report-editor --title "研究報告修改" --route "#studies" --worktree "D:/Project/stock-research/.worktrees/<task>"
python -m scripts.development_preview list
python -m scripts.development_preview open --id report-editor
python -m scripts.development_preview retire --id report-editor
```

The `open` CLI is also available for first-use verification before the new
Dashboard entry reaches main. A registration needs no PR number until one exists.

Use the Dashboard button to open the registered project. A GET of the list never
starts a process. Only the explicit open action may start its standard launcher.
The launcher uses development mode, separate loopback ports, and the same data
configuration. It must identify the frontend and API before presenting a ready
link. Older branches missing preview identity support must be updated through
the normal branch workflow; do not weaken the identity check to accept them.

Keep failure messages visible and retain the normal Dashboard tab. A missing
directory, changed branch, occupied port or mismatched service is a failed
preview, not permission to terminate a process or silently switch data modes.
Paths, process identity and configuration details belong in diagnostics rather
than the main reader interface.

**返回正式版** checks the primary Dashboard before navigating in the same tab.
If it is stopped, the explicit button action starts the primary checkout's
standard production launcher in a hidden window, using primary configuration
afresh. The page waits for verified readiness; cancellation stops waiting only,
and a failure leaves the preview available for retry. Read-only status polling
never launches a process. Unknown occupied ports are not taken over.

Readiness requires `dashboard-config.v2`: the mode, producer root, shared root,
research catalog root and private presentation paths all contribute to the
configuration identity. The standard launcher fixes the effective roots in its
child environment at startup. Changing primary configuration from A to B cannot
make a still-running A service appear ready for B. Older services without this
identity require an update and restart; the return action leaves them untouched
and displays an update hint. Merge and normal primary update must precede the
final end-to-end acceptance with the new identity.

Both preview and primary launches use a short-lived helper that exits before
the action returns. Their launchers have independent lifetimes: closing one
launcher must not terminate the other through Windows process-tree cleanup.
The existing desktop heartbeat still stops an unused service normally; this
feature adds no scheduler or permanently running background service.

After verified owner merge, retire the registration. Retirement affects the
preview listing only; it does not delete a worktree, data or another session's
processes. Follow the existing Git/worktree cleanup contract separately. Do not
register unrelated worktrees merely because they appear in Git's inventory.

## Acceptance

Check that a new entry can be listed, opened, reused and reported as unavailable
after a path or identity mismatch. Check startup failure and retry without a
second launch. Verify that development and main select the same canonical data
roots, while reports and API study cards select the intended branch. Verify the
page, report index and service identity together; a responding port alone is
insufficient. A browser rendering check remains distinct from HTTP and component
tests. No successful automated check implies that the owner has merged or
deployed this feature into main.

Exercise returning while main is stopped as well as already running. Confirm
that readiness uses primary identities and production release/report versions,
and that closing the initiating launcher leaves the destination usable. A
working return URL alone does not verify this lifecycle.

## Initial delivery (2026-10-31)

This session owns `.worktrees/development-preview` on
`codex/development-preview`, based on `origin/main` at `8cafbb648bce`.
The local `preview-entry` registration is retained for owner trial. A second
`preview-launch-check` registration was used to verify browser startup and then
retired; its tab was closed so the standard idle lifecycle can stop its services.
No existing main or port-15177 process was replaced.

Browser acceptance used Edge: the header opens the panel, a stopped registration
transitions through startup to a ready link, the link opens a separate tab, and
the preview shows its return-to-main link. Desktop and 390-pixel viewport captures
are retained locally in primary `.tmp/development-preview-desktop.jpg` and
`.tmp/development-preview-mobile.jpg`. Initially only the return URL was checked;
the stopped-main follow-up below supersedes that limited check. The trial uses
main's existing report/card content, not unmerged PR113.

The return-button follow-up started with both primary ports stopped. Edge
showed the cancellable waiting state, then navigated the same tab to port 5177.
The primary production web/API identified the primary checkout and configured
data; the status endpoint verified its release and report index as ready. The
hidden launcher was running after its short-lived parent had exited. Existing
preview and unrelated services were not terminated for this check. The waiting
capture is `.tmp/development-return-main-waiting.jpg`. Primary source and the
desktop shortcut were unchanged; its standard launcher built its existing main
source when opening it normally.

This successful navigation was observed before the final full-root identity
requirement. The existing primary service is deliberately retained on its old
source and must now be reported as needing an update. Synthetic tests cover
every A-to-B root change and rejection of a missing identity version. Final
live navigation with `dashboard-config.v2` remains pending owner merge and
normal primary update; this PR does not update primary code for its own test.

The four earlier strength-flags worktrees remain: mission/code are retained for
historical citations; execution is retained pending the presentation handoff;
presentation holds open PR113. None was removed or modified by this feature.
