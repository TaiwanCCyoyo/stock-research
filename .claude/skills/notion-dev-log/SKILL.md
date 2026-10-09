---
name: notion-dev-log
description: Write a development log entry to Notion. Use when the user says "write today's dev log", "record what we did", "log today's progress", or after a development session wraps up. Automates the full workflow: reads git log, asks for context, creates a dated sub-page, and updates the daily page.
---

# Skill: Notion Dev Log

Automates writing a development journal entry into the Notion trading strategy workspace.

## Procedure

### Step 1 — Gather Context

Run:

```bash
git log --oneline -15
```

Also use built-in memory context already loaded for this session for project background.

### Step 2 — Ask the User

After reviewing the git log, ask the user in Traditional Chinese what they accomplished,
whether they got stuck anywhere, and what to work on next. Ask if there is anything else to add.

Wait for the user's reply before writing anything to Notion.

### Step 3 — Create the Dev Log Sub-page

Create a sub-page under the trading strategy main page
(`https://app.notion.com/p/2852db6b602580b0b977f9f52699d70d`)
using the Notion MCP `create-pages` tool.

- **Page title:** date in `YYYY/MM/DD` format followed by a space and the Traditional Chinese
  word for "development log" (two characters: log entry heading used consistently in this project)
- **Page icon:** 📔
- **Parent:** page_id `2852db6b602580b0b977f9f52699d70d`

The page body has three sections in Traditional Chinese, in this order:

1. "This session's accomplishments" — one bullet per theme from git log and user input
2. "Technical notes" — problems hit, solutions, things learned; include anything the user was stuck on
3. "Continue next time" — concrete next steps

Writing guidelines:

- Group commits by theme, not one bullet per commit hash
- Distinguish automated agent work from user-driven decisions when relevant
- Keep bullets to one clear sentence each

### Step 4 — Update the Dev Log Index on the Main Page

After the sub-page URL is confirmed, prepend the new entry to the dev log list on the main page.

Use `update_content` (never `replace_content` — the page has inline databases).
Always `fetch` the main page first to get the current list before editing.

Target the section whose heading contains the dev log icon (📔) and the Traditional Chinese
heading for the log section. Add the new `mention-page` link at the top, keeping existing entries below.

### Step 5 — Update the Daily Page (optional)

If meaningful progress was made, also update the daily page
(`https://app.notion.com/p/2852db6b6025801680d2c5c280b09fe1`).

Fetch the page first, then use `update_content` to prepend one line to the highlights section.
The line should start with the computer emoji, followed by "stock project" in Traditional Chinese,
a colon, and a one-line summary of today's main achievement.

## Safety Rules

- Always `fetch` before any `update_content` call
- Never use `replace_content` on the main page (inline databases will break)
- Create the sub-page first; only update the main page after the URL is confirmed
- If a log entry for today already exists, append to it instead of creating a duplicate
