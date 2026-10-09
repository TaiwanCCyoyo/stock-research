---
name: design-notion-pages
description: Create or improve Notion page layouts with clean productivity-dashboard visual design. Use when Codex is asked to design, rewrite, audit, beautify, or generate Notion dashboards, templates, project pages, trackers, knowledge bases, resource hubs, review pages, or Notion-flavored Markdown pages with concrete block-level layout guidance.
---

# Design Notion Pages

## Purpose

Use this skill to produce Notion pages that are beautiful, scannable, maintainable, and useful for daily work. Prefer clean productivity-dashboard design over decorative widget boards or plain Markdown notes.

The output should be a concrete Notion build plan, not generic advice.

## Design Direction

Aim for:

- clean productivity dashboard
- low-saturation colors
- clear page hierarchy
- large visual sections before small details
- card-like callout and gallery areas
- database-centered workflows
- minimal motion and decoration

Avoid:

- long heading-and-bullet documents
- many unrelated colors or icon styles
- decorative widgets without a job
- every section using a different pattern
- databases exposed with all properties by default

## Workflow

1. Identify the page role.
2. Design the first screen.
3. Define the visual system.
4. Build the layout with columns, dividers, callouts, quotes, toggles, and databases.
5. Choose database views by use context.
6. Add motion, widgets, media, and archive areas only where they support the workflow.
7. Output a concrete section-by-section Notion plan.

## 1. Identify The Page Role

Choose the role before arranging blocks. Match structure to use frequency.

- Daily Dashboard: quick entry, today's work, calendar, focus, short reminders.
- Weekly Planner: weekly goals, schedule, review, active tasks, carry-over items.
- Project Page: overview, current status, next actions, task board, notes, decisions, references.
- Knowledge Base: topic map, gallery index, recent notes, important references, archive.
- Tracker: current metric, input area, calendar/list views, trend or review area.
- Resource Hub: quick links, grouped resources, gallery directory, notes, archive.
- Archive Page: search, filtered databases, toggles, old records, low visual intensity.

If the role is unclear, infer it from the user's content and state the assumption briefly.

## 2. Design A Strong First Screen

The first screen should answer:

- Where am I?
- What is this page for?
- What should I do first?
- Where are the main actions?

Recommended top stack:

```text
Cover image
Page icon
Large title
One-sentence usage hint
Three or four horizontal guide cards
Primary database or action area
```

Do not start with a large raw database unless the page is purely operational.

Use cover images sparingly. Prefer calm, low-contrast images or abstract textures that match the palette. Avoid covers that compete with the title or database content.

## 3. Define A Visual System

Keep visual consistency stronger than decoration.

Specify:

- Primary color: page identity.
- Secondary color: supporting sections.
- Alert color: deadlines, risks, blockers.
- Done color: completed or stable state.
- Neutral color: background, dividers, archive, references.

Use no more than four main colors in the same visible screen. Use colors semantically, not randomly.

For work pages, prefer white, light gray, dark gray text, and low-saturation green, blue, beige, pink, or yellow. Avoid neon, rainbow callouts, dark blocks everywhere, or unrelated image styles.

## 4. Use Icons As A Language

Choose one icon style and map icons by meaning. Do not mix emoji, Notion icons, external icons, and animated icons without a reason.

Suggested semantic mapping:

```text
Tasks: check or checkbox icon
Projects: folder or briefcase icon
Focus: pin or target icon
Knowledge: book icon
Calendar: calendar icon
Resources: link icon
Risks: warning icon
Goals: target icon
Planning: compass icon
Archive: box or tray icon
```

When outputting a design, name the icon system and explain repeated usage briefly.

## 5. Build Large Structure Before Small Structure

Use columns before adding decoration.

Default dashboard ratio:

```text
Left column: 65% to 70%
Right column: 30% to 35%
```

Put primary work in the left column. Put supporting information in the right column.

Good right-column content:

- calendar
- small widget
- quick links
- today's reminder
- weekly focus
- reference notes

Avoid placing large task databases, long notes, deeply nested content, or complex boards in the right column.

Recommended build sequence:

```text
1. Main two-column layout
2. Primary database or main content area
3. Side panel
4. Three or four guide cards
5. Callout or quote blocks for emphasis
6. Secondary gallery, reference, and archive areas
```

## 6. Use Notion Blocks Intentionally

Use these blocks as layout tools, not decoration.

### Columns

Use columns to create structure and comparison. Prefer one primary content column plus one supporting column for dashboards. Use three or four equal columns only for guide cards, indexes, or short navigation.

### Divider

Use dividers for page rhythm and major separation:

- after the intro
- between guide cards and work area
- between dashboard and reference sections
- around embedded media
- before archive areas

Avoid dividers under every small heading or inside already clear callouts.

Use normal gray dividers for general separation, colored dividers only for important theme breaks, and thick/custom dividers only for major page-level transitions.

### Callout

Use callouts as cards, soft backgrounds, database containers, warnings, quick navigation, and visual grouping.

For large callout backgrounds:

- use low-saturation background colors
- keep icons minimal or transparent where possible
- remove placeholder text
- avoid strong colors over large areas

### Quote

Use quote blocks for light hierarchy, navigation rows, short principles, compact instructions, and button explanations. Avoid long article-like quote sections.

### Toggle

Use toggles for low-frequency details, old notes, reference lists, and archive sections. Keep the main workflow outside toggles.

### Button

Use buttons for repeated creation actions such as adding a task, project, review, resource, note, or meeting entry. Place buttons near the relevant database view.

### Gallery View

Use gallery views to create visual directories for projects, knowledge maps, resources, templates, topics, life areas, or tools. Make covers consistent and show minimal properties.

## 7. Design Databases As The Core

A beautiful Notion page should remain functional. Prefer one well-designed database with multiple context-specific views over many duplicate databases.

Recommended database roles:

- Tasks
- Projects
- Goals
- Notes
- Resources
- Reviews
- Habits
- Decisions

Choose views by user intent:

```text
List: today tasks, tomorrow tasks, focused action list
Board: project flow, task status, kanban pipeline
Gallery: topic index, project index, knowledge map, visual directory
Calendar: deadlines, schedule, review dates
Timeline: roadmap, milestones, long-term planning
Table: detailed editing, database maintenance, raw data
```

For dashboard views, hide properties that are not needed now.

Task dashboard view should usually show:

```text
Task name
Status
Due date
Priority
```

Project dashboard view should usually show:

```text
Project name
Status
Progress
Next action
Deadline
```

Gallery index view should usually show:

```text
Name
Category
Progress or status
Cover image
```

Hide created time, last edited time, internal tags, long notes, and relation fields unless the current view needs them.

## 8. Add Media, Motion, And Widgets Carefully

Motion should be a small accent, not the main experience.

Acceptable motion:

- one animated icon
- one small animated illustration
- one clock or calendar widget
- one music or focus widget in a side or bottom area

Avoid motion beside the main task list, in every card, in serious planning sections, or anywhere users need sustained focus.

Use widgets only when they serve a role. Good widgets include clock, calendar, progress indicator, weather, and pomodoro. Keep serious productivity pages to one to three widgets.

Place YouTube and other video embeds in side panels, bottom areas, reference sections, or focus music sections. Frame them with dividers when they would otherwise interrupt the page rhythm.

## 9. Keep A Reference And Archive Area

Long-term pages need a low-frequency area so the main dashboard stays clean.

Use toggles or filtered database views for:

- completed items
- old planning notes
- reference links
- deprecated sections
- archived projects
- previous reviews
- unused ideas

Keep archive areas visually quieter than the main work area.

## Output Format

When designing or improving a Notion page, output this structure:

```md
# Page Name

## Visual Style

Describe cover, icon, palette, image style, icon language, and motion/widget rules.

## Layout Structure

Describe the page from top to bottom, including first screen, columns, side panel, secondary sections, and archive.

## Database Views

List each database, each view, view type, visible properties, hidden properties, and purpose.

## Blocks To Use

Specify where to use Columns, Divider, Callout, Quote, Button, Toggle, Gallery View, media, and widgets.

## Maintenance Rule

Explain how to keep the page clean over time.
```

Always include concrete Notion block choices and enough implementation detail that the user can build the page directly.

## Final Quality Gate

Before final output, verify:

- the first screen has a clear hierarchy
- colors are consistent and limited
- icons have semantic meaning
- columns create structure before decoration appears
- dividers create rhythm without clutter
- callouts function as cards, containers, or emphasis
- quotes are short and purposeful
- database views match the user's context
- unnecessary database properties are hidden
- gallery views use consistent covers
- motion and widgets do not distract
- archive/reference content is lower emphasis
- the page will still be useful if decorations are removed
