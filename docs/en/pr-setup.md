# Enable PR Delivery in a Downstream Project

Stock status (2026-09-20): CI and hosted review already work. GitHub Free supports private-repository Actions with included usage; private-repository branch rulesets require Pro or another supported plan. Do not confuse running CI with enforcing it.

Reset the [Git workflow contract](git-workflow.md) to local-only when adopting this template, then follow this guide to enable delivery deliberately. This guide is for repository owners. It does not grant agents setup, publishing, or administration authority, and copying the template configures none of it.

Stock's current configuration status is documented in [PR review](pr-review.md).

## 1. Choose an identity model

**Shared identity (used upstream; proposed for Stock).** Agent sessions push task branches and open pull requests with the owner's own GitHub credentials, so agent-authored commits are attributed to the owner. Distinguish agent work by branch prefix and commit message, not by identity.

This is the simplest option and needs no App, no private key, and no token helper. Its cost is explicit: **agent and owner share one identity, so there is no enforced separation between roles.** Accept that limitation knowingly, or do not use this model.

**Separate identity.** If your project requires enforced separation — for example, a reviewer whose approval must count toward a required-review rule — you need a distinct identity that development sessions cannot reach. Two tokens for the same user do not create independent reviewers. Audit every authentication route, because Git HTTPS/SSH, `gh`, and agent plugins can each resolve to a different identity, and separate worktrees do not isolate credentials.

## 2. Protect the default branch

Create a ruleset on the default branch that requires a pull request, resolution of every review conversation, and a passing status check for the current revision. Block force pushes and branch deletion, and **leave the bypass list empty** — a bypass actor silently voids every rule below it.

Under the shared-identity model, do not require an approving review: a single identity cannot approve its own pull request, so the rule would deadlock. Conversation resolution plus a required check is a weaker shared-identity control, not independent approval; the author may resolve their own conversations.

Add your CI before selecting required check names, keep the job name stable, and confirm the check actually runs on pull requests.

## 3. Connect review

Enable a hosted review integration for the repository — this template uses the Codex GitHub integration, which reviews each pull request against the root `AGENTS.md` review rules.

Two properties matter when you wire this up:

- Review output is **advisory commentary, not a GitHub approval**, and it merges nothing.
- Review findings create review conversations, so an unresolved finding blocks merging through the conversation-resolution rule rather than through an approval rule.

Nested `AGENTS.md` files scope their rules to their own directory. Repository-wide review rules belong in the root file.

## 4. Record and verify

1. Record the approved repository, base branch, and publishing identity in the current-state bullet of `git-workflow.md`, then enable standing PR delivery there. Record no credentials.
2. Align the agents' runtime permissions with that scope. Changing prose does not remove a runtime confirmation prompt.
3. Push a disposable branch and open a small pull request. Verify that CI runs, that review posts, and that merging is refused while a conversation is unresolved or a check is failing.
4. Verify that a direct push to the default branch is rejected. Use a test repository or an owner-approved probe; a misconfigured production rule could accept the attempted write.

Record the evidence and any remaining gap before relying on the boundary.

## 5. Keep merge authority explicit

Merging is the owner's decision unless you deliberately delegate it. If you automate merging, make the automation re-check the current head rather than trusting an earlier result: a review of commit `ABC` says nothing about commit `DEF`. Treat the absence of review findings as "not reviewed yet" until the review is confirmed complete for the current head.

Never merge with admin privileges, a force push, or a weakened ruleset.

## References

- [GitHub rulesets](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-rulesets/available-rules-for-rulesets)
- [Automatically merging a pull request](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/incorporating-changes-from-a-pull-request/automatically-merging-a-pull-request)
- [Codex GitHub review integration](https://learn.chatgpt.com/docs/third-party/github)
