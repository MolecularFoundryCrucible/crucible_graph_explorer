# Crucible Graph Explorer — Style Guidelines

This document captures the design system, component patterns, and conventions used
across the Crucible web application. Follow these guidelines when building new pages
or modifying existing ones.

---

## 1. Technology Stack

| Layer | Tool | Version |
|---|---|---|
| CSS framework | Bootstrap | 5.3 (CDN) |
| Icon library | Bootstrap Icons | 1.11 (CDN) |
| JavaScript | Vanilla ES6+ | (no bundler) |
| Templating | Jinja2 / Flask | — |
| Fonts | System stack (Bootstrap default) | — |

Bootstrap Icons are currently loaded per-template. Ideally, move the CDN link to
`base.html` so all pages have access.

---

## 2. Layout & Grid

### Base Template (`base.html`)

The base template provides three key blocks for layout control:

```html
{% block sidebar %}   <!-- defaults to col-sm-3 TOC sidebar -->
{% block main_col_class %}  <!-- defaults to "col-sm-9" -->
{% block content %}   <!-- main page content -->
```

**Override pattern for full-width pages** (e.g., dashboard):
```html
{% block sidebar %}{% endblock %}
{% block main_col_class %}col-12{% endblock %}
```

**Override pattern for narrow sidebar** (e.g., project overview):
```html
<!-- sidebar block: col-md-2 pe-0 d-none d-md-block -->
<!-- main_col_class: col-12 col-md-10 -->
```

### Page Width

- Never let content span the full viewport width on large monitors.
- Use `col-md-10`, `col-lg-9`, or `max-width` constraints for readability.
- Dashboard and overview pages use a right-side content area that max-widths naturally.

### Sidebar Navigation

- Sidebars are hidden on mobile with `d-none d-md-block`.
- Sidebar links navigate AND switch state (tab, scroll target, etc.) via JS.
- Both content categories (e.g., Samples AND Datasets) are always visible in the sidebar
  simultaneously — clicking one switches the active tab before scrolling.

---

## 3. Color System

### Avatar / Accent Palette

All color-coding of project IDs, resource type headings, and card borders uses a
shared 10-color palette. The same `hashColor()` function is used in every template:

```javascript
const PALETTE = [
    '#4e79a7','#f28e2b','#e15759','#76b7b2',
    '#59a14f','#edc948','#b07aa1','#ff9da7',
    '#9c755f','#bab0ac'
];

function hashColor(str) {
    let h = 0;
    for (let c of String(str)) h = (h * 31 + c.charCodeAt(0)) & 0xfffffff;
    return PALETTE[h % PALETTE.length];
}
```

**Rules:**
- Avatar circles: background = `hashColor(project_id)`; text = white.
- Card / header left border: `border-left: 4px solid hashColor(project_id)`.
- Group headers: `border-left: 4px solid hashColor(type_name)`.
- Do NOT use arbitrary hex colors — always go through `hashColor()` or Bootstrap tokens.

### Bootstrap Semantic Tokens

Prefer CSS variables from Bootstrap over hardcoded values:

| Intent | Token |
|---|---|
| Primary accent | `var(--bs-primary)` |
| Subtle background | `var(--bs-tertiary-bg)` |
| Border | `var(--bs-border-color)` |
| Muted text | `var(--bs-secondary-color)` |
| Body background | `var(--bs-body-bg)` |

---

## 4. Typography & Text

- Titles: `<h4>` or `<h5>` with `fw-semibold`.
- IDs / UUIDs: wrapped in `<span class="mfid">` — monospace, `color: #80858a`.
  Defined in `base.html` globally.
- Always show full UUIDs — never truncate with `text-overflow: ellipsis` for identifiers
  the user may want to copy.
- Metadata inline labels: `text-muted small` or via `metaBadge()` pattern (see §6).

---

## 5. Navigation & Breadcrumb

- Every page must extend `base.html` and provide a `{% block breadcrumb %}` with
  the correct chain of links (Home → Project → Resource).
- The breadcrumb nav is `sticky-top` — all sticky child elements compute their
  `top` offset dynamically:
  ```javascript
  const navH = document.querySelector('nav[aria-label="breadcrumb"]').getBoundingClientRect().height;
  el.style.top = navH + 'px';
  ```
- Never hardcode pixel offsets for sticky elements.

---

## 6. Component Patterns

### 6.1 Metadata Badges

For showing org, lead, type, or other key-value metadata inline:

```javascript
function metaBadge(icon, text) {
    return `<span class="badge fw-normal border text-body-secondary me-1"
                  style="background:var(--bs-tertiary-bg)">
                <i class="bi ${icon} me-1"></i>${text}
            </span>`;
}
```

CSS class: `badge fw-normal border text-body-secondary`
Background: `var(--bs-tertiary-bg)` (not a Bootstrap badge color — stays neutral).

### 6.2 Action Buttons

Two standard CTA styles used throughout:

| Action | Classes |
|---|---|
| Search | `btn btn-sm btn-outline-secondary` + `bi-search` icon |
| Chat (LLM) | `btn btn-sm btn-outline-primary` + `bi-chat-dots` icon |
| Archive | `btn btn-sm btn-outline-secondary` + `bi-archive` icon |
| Star | `btn btn-sm btn-outline-warning` + `bi-star` / `bi-star-fill` |

Always include an icon before the label text: `<i class="bi bi-search me-1"></i>Search`.

### 6.3 Text-Selectable Clickable Rows

**Critical pattern:** Never use `<a>` tags for list rows where the text inside must
be selectable (e.g., UUIDs). The browser navigates before selection can be checked.

**Correct pattern:**
```html
<div class="list-row" onmouseup="navIfNoSelection(event, '{{ url }}')">
    <!-- row content -->
</div>
```

```javascript
function navIfNoSelection(event, url) {
    if (window.getSelection().toString()) return;    // user is selecting text
    if (event.target.closest('a, button')) return;  // user clicked a link/button inside
    window.location.href = url;
}
```

Apply `cursor: pointer` on `.list-row`. Never use `onclick` on `<a>` for this purpose.

### 6.4 Collapsible Groups

```html
<div class="group-header d-flex align-items-center p-2"
     style="border-left: 4px solid {{ color }}; border-radius: 0.375rem 0.375rem 0 0;"
     onclick="toggleGroup(this)">
    <i class="bi bi-chevron-right me-2 group-chevron" style="transition:transform .2s"></i>
    <span>Type Name</span>
    <span class="badge ms-auto">N</span>
</div>
<div class="collapse-body"><!-- items --></div>
```

```javascript
function toggleGroup(header) {
    const body = header.nextElementSibling;
    const chevron = header.querySelector('.group-chevron');
    const open = body.style.display !== 'none';
    body.style.display = open ? 'none' : '';
    chevron.style.transform = open ? '' : 'rotate(90deg)';
}
```

Groups start **collapsed** by default (`display:none` on `collapse-body`).

### 6.5 Avatar Circles

```html
<div style="width:3rem;height:3rem;border-radius:50%;
            background:{{ color }};color:white;
            display:flex;align-items:center;justify-content:center;
            font-weight:700;font-size:1rem;flex-shrink:0;">
    {{ initials }}
</div>
```

Initials: split the project ID on `_` and `-`, take first letter of each part (max 2).

### 6.6 Tab Switcher

Active tab: `border-bottom: 4px solid var(--bs-primary)`, full opacity.
Inactive tab: `border-bottom: 4px solid transparent`, `opacity: 0.55`.

Tab bar is sticky (see §5 for offset computation). Two halves of a `d-flex` container,
each half has `cursor:pointer` and a `tab-stat` class:

```css
.tab-stat { flex: 1; text-align: center; padding: 0.6rem 1rem; cursor: pointer; }
.tab-stat.active { background: var(--bs-body-bg) !important; border-bottom: 4px solid var(--bs-primary); }
.tab-stat.inactive { background: var(--bs-tertiary-bg) !important; opacity: 0.55; }
```

### 6.7 Back-to-Top Button

Fixed to bottom-right corner, circular, hidden until user scrolls 300px:

```html
<button id="backToTop" onclick="window.scrollTo({top:0,behavior:'smooth'})"
        class="btn btn-primary rounded-circle shadow"
        style="position:fixed;bottom:1.5rem;right:1.5rem;width:3rem;height:3rem;
               display:none;align-items:center;justify-content:center;z-index:1050;">
    <i class="bi bi-arrow-up"></i>
</button>
```

```javascript
window.addEventListener('scroll', () => {
    document.getElementById('backToTop').style.display =
        window.scrollY > 300 ? 'flex' : 'none';
});
```

### 6.8 Empty States

When a list or section has no content:

```html
<div class="text-center text-muted py-5">
    <i class="bi bi-inbox fs-1 d-block mb-2"></i>
    No items found.
</div>
```

Choose a semantically relevant icon (`bi-inbox`, `bi-search`, `bi-folder`, etc.).

---

## 7. Icons Reference

Use **Bootstrap Icons** (`bi-*` classes). Standard icons used in this project:

| Concept | Icon class |
|---|---|
| Search | `bi-search` |
| LLM Chat | `bi-chat-dots` |
| Users / People | `bi-people` |
| Organization | `bi-building` |
| Project Lead | `bi-person` |
| Star (empty) | `bi-star` |
| Star (filled) | `bi-star-fill` |
| Archive | `bi-archive` |
| Back to top | `bi-arrow-up` |
| Collapse/expand chevron | `bi-chevron-right` (rotated 90° when open) |
| Sample | `bi-droplet` |
| Dataset | `bi-table` |
| Measurement type | `bi-tag` |
| Graph / network | `bi-diagram-3` |
| Notebook | `bi-journal-code` |
| Edit | `bi-pencil` |
| Empty / no results | `bi-inbox` |

Always pair icons with text except in icon-only buttons (which need `aria-label`).

---

## 8. Mobile Responsiveness

### Principles
- Default layout should work on 375px+ screens without horizontal scroll.
- Sidebars are hidden on mobile: `d-none d-md-block`.
- Desktop-only toolbar controls (sort, layout): `d-none d-md-flex`.
- Auto-fallback to card layout when viewport < 768px:
  ```javascript
  function effectiveLayout() {
      return window.innerWidth < 768 ? 'cards' : currentLayout;
  }
  ```
- Attach a debounced resize listener to re-render layout on orientation change.

### Breakpoint Reference

| Class suffix | Screen |
|---|---|
| (none) | All screens |
| `sm` | ≥ 576px |
| `md` | ≥ 768px |
| `lg` | ≥ 992px |

### Known Mobile Issues to Address
- `dataset.html`: deprecated `card-columns` → replace with `row row-cols-1 row-cols-md-2`
- Graph pages (`sample_graph.html`, `entity_graph.html`): fixed `600px`/`700px` graph height
  → use `min-height: 60vh` or `height: calc(100vh - 12rem)`
- `users.html`: table overflows → wrap in `<div class="table-responsive">`
- `chat.html`: `100vh` breaks with mobile virtual keyboard → use `100dvh`

---

## 9. JavaScript Conventions

- No frameworks or build tools — vanilla ES6 only.
- `localStorage` keys are prefixed with `crucible-` (e.g., `crucible-layout`, `crucible-starred`).
- All JS is inline in `<script>` tags at the bottom of each template's body block.
- Shared utility functions (`navIfNoSelection`, `hashColor`, `toggleGroup`) are
  duplicated per-template — consider extracting to a shared `static/crucible.js` in the future.
- DOM queries for sticky offset use `getBoundingClientRect()` not hardcoded values.

---

## 10. Page Structure Template

A new page should follow this skeleton:

```html
{% extends "base.html" %}

{% block head %}
{{ super() }}
<!-- Add Bootstrap Icons if not in base.html yet -->
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css">
<style>
    /* Page-specific styles only */
</style>
{% endblock %}

{% block title %}Page Title{% endblock %}

{% block breadcrumb %}
<li class="breadcrumb-item"><a href="/projects">Projects</a></li>
<li class="breadcrumb-item active">Current Page</li>
{% endblock %}

{% block sidebar %}
<!-- Override if you need a custom sidebar or want to hide it -->
<div class="col-md-2 pe-0 d-none d-md-block">
    <!-- sidebar nav -->
</div>
{% endblock %}

{% block main_col_class %}col-12 col-md-10{% endblock %}

{% block content %}
<!-- Main page content -->

<!-- Back-to-top button -->
<button id="backToTop" ...>
    <i class="bi bi-arrow-up"></i>
</button>
{% endblock %}

{% block footer %}
<script>
    // Page-specific JS
    // navIfNoSelection, hashColor, etc. if needed
</script>
{% endblock %}
```

---

## 11. Do's and Don'ts

### Do
- Use `navIfNoSelection` on all clickable rows.
- Compute sticky offsets dynamically from the breadcrumb nav height.
- Use `hashColor()` for all color assignments tied to entity IDs.
- Show full UUIDs — never truncate identifiers the user needs to copy.
- Start collapsible sections collapsed by default.
- Show both sidebar categories simultaneously (don't hide inactive ones).
- Add `<title>` via `{% block title %}` on every page.
- Use `metaBadge()` / equivalent for metadata chips.

### Don't
- Don't use `<a>` tags for rows that contain selectable text.
- Don't hardcode pixel offsets for sticky elements.
- Don't use arbitrary hex colors — go through `PALETTE`/`hashColor()`.
- Don't hide content categories in the sidebar based on the active tab.
- Don't use deprecated Bootstrap 4 classes (`card-columns`, `text-left`, etc.).
- Don't use `onclick` on `<a>` to intercept navigation (use `onmouseup` + `<div>`).
- Don't use fixed `height` on graph/chart containers — use `min-height` or `vh` units.
- Don't use `100vh` for full-screen layouts — use `100dvh` for mobile keyboard compatibility.
