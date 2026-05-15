# Claude Code instructions for crucible_graph_explorer

## Git

**Never `git push` without explicit user confirmation.** Always ask before pushing.

## Documentation

Before making any frontend or UI changes, read:

- **`dev/STYLE_GUIDELINES.md`** — design tokens, type scale, component patterns, CSS conventions. This is the primary reference for all UI work.
- **`README.md`** — how to run the app locally.

The `dev/` folder contains design docs and feature specs. Keep it up to date when introducing significant changes.

## Key conventions (summary — see STYLE_GUIDELINES.md for full detail)

- **Font sizes**: always use `var(--fs-2xs)` through `var(--fs-2xl)` — never hardcode `rem` values
- **Colors**: use `var(--cg-*)` brand tokens and `var(--bs-*)` Bootstrap tokens — never hardcode hex
- **Icons**: Bootstrap Icons (`bi-*`); `bi-flask` = sample, `bi-database` = dataset, `bi-collection` = project
- **Sidebar**: use `.cg-sidebar-action` and `.cg-sidebar-section` classes; `resource_sidebar()` macro for resource pages
- **Sticky offsets**: always compute from `getBoundingClientRect().height` — never hardcode pixels
- **Clickable rows**: use `navIfNoSelection(event, url)` on `<div class="list-row">`, not `<a>` tags
