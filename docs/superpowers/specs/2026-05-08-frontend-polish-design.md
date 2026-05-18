# Frontend Polish & UX Overhaul — Design Spec
_Date: 2026-05-08_

## Context

The crucible_graph_explorer Flask app is functional but the UI feels barebones and navigation on resource pages is clunky. This spec covers a focused overhaul of UX flows, UI polish, and list-page layouts. Scope is Approach B (resource pages + list pages + navigation) with selected features from Approach C cherry-picked in (lightbox) and the remainder deferred to `dev/`.

---

## 1. Navigation & State Preservation

### Problem
Navigating from the project overview to a sample/dataset and pressing Back reloads the full project overview, losing the active tab, filter query, and scroll position.

### Solution: sessionStorage state restore
- When the project overview page is about to unload (via `beforeunload` or link click), write the current URL hash state to `sessionStorage` keyed by `cg_overview_state_<project_id>`.
- On load, if a stored state exists for this project, restore it silently via `history.replaceState` before rendering.
- The URL hash already encodes tab + filter (`#tab=samples&q=filter`), so reading/writing it is the only change needed.

### Solution: Sibling jump dropdown
- Flask routes for `sample_graph()` and `dataset()` already compute `prev_sibling`, `next_sibling`, `sibling_index`, `sibling_count`. They need to additionally pass the full `siblings` list (IDs + names only, no extra API calls — already in `pc['samples_by_id']`).
- The compact header strip shows `‹ 4/12 Silicon ›` with a **Jump ▾** button. Clicking opens a small absolutely-positioned dropdown listing all siblings with the current one highlighted. Click any to navigate.
- Dropdown closes on outside click or Escape.

### Solution: Smart back-link
- The sidebar's "← Back to project" link appends the stored hash state as a fragment so the overview reopens exactly where the user left off.
- When the sidebar is collapsed, the icon rail shows a small home icon (bi-house) that serves the same purpose.

---

## 2. Resource Detail Card — Compact Header

Replace the current large header card (avatar + metadata + QR + action footer) with a compact, sticky design that gives maximum vertical space to the content sections.

### Structure (top to bottom)

**Identity strip** (always visible, ~56px tall):
- Left: avatar circle (28px), resource name (bold, truncate), UUID (monospace, muted, truncated)
- Right: type/measurement badge, dataset/sample count chip
- Left border accent: hashColor(type) as before

**Action strip** (~36px tall, below identity):
- Left: `‹` prev · `4 / 12 Silicon` · `›` next · **Jump ▾** dropdown
- Right: icon buttons — Search, Graph, Camera (photo upload), Edit, and a filled **Chat** button
- QR: small icon button (bi-qr-code) in the action strip opens a popover; no longer shown inline
- Border-bottom separates from content sections

### Compact sticky header on scroll
The existing `#compactHeader` already handles showing a sticky bar when the main card scrolls away. With the new compact design, the main card IS the compact header — no secondary sticky bar needed. Remove the scroll-observer logic.

### Badge/keyword display
Keywords remain as small badges below the name in the identity strip, wrapping to a second line if needed.

---

## 3. Sidebar — Slim Collapsible

### Structure
- Width: `160px` (down from Bootstrap `col-md-2` ≈ `~200px`)
- Collapsible: a `›`/`‹` toggle button on the right edge collapses it to `32px` (icon rail only)
- State persisted in `localStorage` under key `cg_sidebar_collapsed`
- Hidden on mobile (< md) as before

### Content (top to bottom)
1. **Project identity**: avatar (20px) + project ID, truncated. Clicking navigates to project.
2. **Back link**: "← Back to project" with state-preserved URL (see §1).
3. **Divider**
4. **"This sample/dataset"**: label + resource name in bold.
5. **Divider**
6. **Linked resources** (scrollable): flat nav links for directly linked datasets (from sample page) or linked samples (from dataset page). Shows name only, truncated. Count in section label.
7. **Ancestors** (if any): same flat list pattern.
8. **Descendants** (if any): same flat list pattern.

### Collapsed state (icon rail)
Shows only: project avatar icon, collapse toggle. Hovering shows a tooltip with the item label.

---

## 4. List Pages

### Users page
**Layout**: grouped list, grouped by institution/organization.
- Sticky search/filter input at top.
- Each group has a sticky section header showing institution name + member count.
- Each row: avatar (36px) · full name · ORCID (monospace, muted) · project count badge.
- Filter chips for quick institution selection (if > 2 institutions present).
- The list is bounded (only users sharing a project with the current user), so no pagination needed.
- _Note_: grouping requires an institution/organization field on the user object. Verify this exists in the `nano-crucible` user model before implementing; if absent, fall back to alphabetical grouping by first letter.

### Instruments page
**Layout**: split — filter panel (left, 180px) + list (right).
- Filter panel: search input + checkboxes grouped by facility/type. Counts shown per filter.
- List: same row structure as Users (avatar · name · facility · dataset count).
- On mobile: filter panel collapses into a top drawer toggled by a "Filters" button.
- The list is global (all instruments in the system), so the filter panel is genuinely needed.

---

## 5. Project Overview Enhancements

### Recently visited strip
- Shown below the tab bar, above the sample/dataset list.
- Horizontal scroll of up to 5 recently visited resources within this project.
- Each chip: type icon · resource name (truncated) · small UUID.
- Populated from `localStorage` via the existing `cgTrackResource()` mechanism — purely client-side, zero API cost.
- Hidden when no resources have been visited yet in this project.

### "Show mine" filter toggle
- A toggle button next to the existing filter input: `👤 Mine`.
- Filters the rendered list to only rows where `owner_orcid === current_user_orcid`.
- `current_user_orcid` is already available in the Jinja context as `{{ current_user_orcid }}` — embed it as a JS variable.
- State stored in `sessionStorage` alongside the tab/filter state.

---

## 6. Thumbnail Lightbox

Applies to the Thumbnails section on both sample and dataset pages.

### Behavior
- Clicking any thumbnail opens a fullscreen overlay lightbox.
- Overlay: dark semi-transparent backdrop, centered image (max 90vw × 90vh), dataset name below.
- Navigation: `‹` / `›` buttons (or left/right arrow keys) cycle through all thumbnails in the section.
- Close: Escape key or clicking outside the image.

### Implementation
- Pure CSS + vanilla JS, no new library dependencies.
- A single `<div id="cgLightbox">` added to `base.html` (or per-template if simpler).
- The Thumbnails section renders `data-lightbox-src` and `data-lightbox-label` on each `<img>` — the lightbox JS reads these attributes.

---

## 7. dev/ Deferred Features

The following features are documented in `dev/` as implementation stubs for future work. They are **not** in scope for this cycle.

| File | Feature |
|---|---|
| `dev/feature-metadata-editor.md` | Inline scientific metadata editor (tree is currently view-only) |
| `dev/feature-advanced-search.md` | Date/owner/measurement/instrument filters on search and list pages |
| `dev/feature-dataset-relationships.md` | Create/remove parent-child dataset links from the UI |
| `dev/feature-bulk-actions.md` | Multi-select + bulk archive/export on project overview |
| `dev/feature-create-dataset.md` | Web form to create datasets (API-only today) |

---

## Files Affected

| File | Change |
|---|---|
| `flask_templates/base.html` | Lightbox overlay div + JS; sidebar collapse logic |
| `flask_templates/sample_graph.html` | New compact header; sidebar slim redesign; recently visited strip |
| `flask_templates/dataset.html` | New compact header; sidebar slim redesign |
| `flask_templates/project_overview.html` | Recently visited strip; "show mine" toggle; back-state restore |
| `flask_templates/users.html` | Grouped list layout |
| `flask_templates/instrument_list.html` | Split filter panel + list layout |
| `routes/samples.py` | Pass full `siblings` list to template |
| `routes/datasets.py` | Pass full `siblings` list to template |
| `dev/feature-*.md` | 5 new stub files |

---

## Out of Scope

- Backend API changes beyond passing the full siblings list
- Scientific metadata editing
- New dataset creation form
- Any changes to graph pages (entity_graph, project_graph)
- Performance/caching improvements (addressed separately)
