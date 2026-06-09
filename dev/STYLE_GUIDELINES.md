# Crucible Graph Explorer — Style Guidelines

Design system, component patterns, and coding conventions for the Crucible web application.
Follow this document when building new pages or modifying existing ones.

---

## 1. Technology Stack

| Layer | Tool |
|---|---|
| CSS framework | Bootstrap 5.3 (CDN) |
| Icon library | Bootstrap Icons 1.13 (CDN, in `base.html`) |
| JavaScript | Vanilla ES6+, no bundler |
| Templating | Jinja2 / Flask |
| Fonts | IBM Plex Sans (400, 500, 600, 700) + IBM Plex Mono (400, 500) via Google Fonts |

Bootstrap Icons and fonts are loaded in `base.html` — do not add CDN links in individual templates.

---

## 2. Design Tokens (CSS Custom Properties)

All tokens are defined in `:root` in `static/styles.css`. Always use these instead of hardcoded values.

### Brand Colors

```css
--cg-accent:      #a8c4cd   /* light teal — dark-mode primary accent */
--cg-accent-mid:  #3a7a87   /* mid teal — icons, active states, borders */
--cg-navy:        #031e2d   /* deep navy — dark navbar background */
--cg-navy-soft:   #07304a   /* softer navy — dropdowns, hover states */
--cg-link:        #3a7a87   /* link color (overrides Bootstrap) */
--cg-link-hover:  #031e2d
--cg-hover-bg:    rgba(58,122,135,0.08)  /* hover background for rows/buttons */
```

### Type Scale

**Never hardcode `font-size` values.** Use these variables exclusively:

```css
--fs-2xs: 0.65rem;   /* 10.4px — uppercase section labels (always add letter-spacing) */
--fs-xs:  0.72rem;   /* 11.5px — badges, ID chips, count labels, metadata secondary */
--fs-sm:  0.8rem;    /* 12.8px — UI chrome: sidebar links, tooltips, toasts, button labels */
--fs-md:  0.875rem;  /* 14px   — body/content default (list rows, meta fields, descriptions) */
--fs-lg:  1rem;      /* 16px   — card titles, primary UI elements, wordmark */
--fs-xl:  1.25rem;   /* 20px   — tab labels, section headings */
--fs-2xl: 1.5rem;    /* 24px   — page-level headings */
```

Values above `--fs-2xl` (display sizes, hero text) are hardcoded per-use and are exceptional.

**Usage rules:**
- `--fs-2xs` always requires `text-transform: uppercase` and `letter-spacing: 0.07em+`
- `--fs-xs` and below are for supporting text only — never primary content
- `--fs-md` is the baseline; most content should live here or above
- Use Bootstrap's `small` class only when semantic (`<small>`) — prefer the scale for presentation

### Shadows

```css
--cg-shadow-sm: 0 1px 3px rgba(0,0,0,0.06), 0 0 0 1px rgba(0,0,0,0.04)
--cg-shadow-md: 0 4px 12px rgba(0,0,0,0.08), 0 1px 3px rgba(0,0,0,0.05)
```

---

## 3. Typography

- **Body font**: IBM Plex Sans — set on `body` in `styles.css`
- **Monospace**: IBM Plex Mono — applied via `.mfid`, `code`, `pre`, `kbd`, `samp`
- **Available weights**: Sans: 400, 500, 600, 700 · Mono: 400, 500
- Do not use `font-weight: 800` or `font-weight: 900` — not loaded

### ID / UUID display

Wrap all UUIDs, IDs, and identifier strings in `.mfid`:
```html
<span class="mfid">ds-abc123</span>
```
This applies IBM Plex Mono and secondary color automatically. **Never truncate identifiers** with `text-overflow: ellipsis` — users need to copy them.

---

## 4. Color System

### Theme-aware tokens

Always prefer Bootstrap semantic tokens over hardcoded colors:

| Intent | Token |
|---|---|
| Body background | `var(--bs-body-bg)` |
| Subtle/alternate background | `var(--bs-tertiary-bg)` |
| Border | `var(--bs-border-color)` |
| Muted text | `var(--bs-secondary-color)` |
| Hover background | `var(--cg-hover-bg)` |

### Per-entity color (hashColor)

All color-coding of projects, types, group headers, and user avatars uses a single hash function defined globally in `base.html`:

```javascript
function hashColor(str) {
    // HSL-based: hue spans full spectrum, saturation 45-74% (never gray),
    // lightness 28-42% (always dark enough for white text).
    let h = 0;
    for (let i = 0; i < str.length; i++) h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
    const u = h >>> 0;
    const hue = u % 360;
    const sat = 45 + ((u >>> 9)  % 30);  // 45–74%
    const lit = 28 + ((u >>> 18) % 15);  // 28–42%
    const s = sat / 100, l = lit / 100;
    const c = (1 - Math.abs(2*l - 1)) * s;
    const x = c * (1 - Math.abs((hue / 60) % 2 - 1));
    const m = l - c / 2;
    const [ri, gi, bi] =
        hue < 60  ? [c,x,0] : hue < 120 ? [x,c,0] : hue < 180 ? [0,c,x] :
        hue < 240 ? [0,x,c] : hue < 300 ? [x,0,c] : [c,0,x];
    return '#' + [ri+m, gi+m, bi+m].map(v => Math.round(v*255).toString(16).padStart(2,'0')).join('');
}
```

Produces a unique hex color per input string. Using HSL guarantees saturation ≥ 45% (never gray or washed-out) and lightness ≤ 42% (always dark enough for white text). The full hue spectrum is used so every input gets a clearly distinct color.

**Rules:**
- Card / header left border: `el.style.borderLeftColor = hashColor(pid)`
- Group headers: `header.style.borderLeftColor = hashColor(typeName)`
- User avatar background: `hashColor(orcid_or_name)`
- Do NOT hardcode hex colors for entity-derived coloring — always use `hashColor()`
- Do NOT use or re-introduce the old `PALETTE` array — it has been removed

---

## 5. Layout & Sidebar

### Base layout blocks

```html
{% block sidebar %}       <!-- .cg-sidebar component or empty -->
{% block main_col_class %}  <!-- defaults to "col-12" -->
{% block content %}
```

### Sidebar architecture

All pages use the `.cg-sidebar` component (defined in `styles.css`):
- Width: 260px expanded, 40px collapsed
- Collapse state persisted to `localStorage('cg_sidebar_collapsed')`
- Collapse toggle: `.cg-sidebar-toggle` button with `toggleSidebar()` (defined in `macros.html`)
- Collapsed state shows `.cg-sidebar-icon-rail` with icon-only buttons

**Three sidebar zones (top to bottom):**
1. **Navigation** — `.cg-sidebar-action` links (Dashboard, Back to project)
2. **Actions** — `.cg-sidebar-section` + `.cg-sidebar-action` links (Edit, Upload, custom views)
3. **Content** — `.cg-sidebar-section` with filter, nav lists, etc. (project overview only)

### Sidebar CSS classes

```css
.cg-sidebar-action   /* flex row: icon + label, hover highlight, cursor pointer */
.cg-sidebar-section  /* zone separator: border-top + padding */
.cg-sidebar-link     /* nav list item: smaller, rounded hover */
.cg-sidebar-back     /* combines with .cg-sidebar-action for the project back strip */
```

### Resource sidebar macro

Use `resource_sidebar(pid, resource_label, resource_icon, resource_title, resource_id=None, actions=[])` from `macros.html`:

```jinja
{% set sidebar_actions = [
    {'label': 'Edit sample', 'url': '/pid/samples/id/edit', 'icon': 'bi-pencil'},
] %}
{{ resource_sidebar(pid, 'sample', 'bi-flask', s['sample_name'], actions=sidebar_actions) }}
```

The macro automatically includes: Dashboard link, project back link, collapsed rail, and `toggleSidebar()`.

### Sticky offset pattern

The top navbar is `3rem` tall and `sticky-top`. Any child element that also needs to be sticky must compute its `top` offset dynamically:

```javascript
const navH = document.querySelector('nav[aria-label="breadcrumb"]').getBoundingClientRect().height;
el.style.top = navH + 'px';
```

**Never hardcode pixel offsets.** When scrolling to an anchor that's below sticky elements, use:
```javascript
const stickyH = navbar.getBoundingClientRect().height + tabBar.getBoundingClientRect().height + 8;
window.scrollTo({ top: el.getBoundingClientRect().top + window.scrollY - stickyH, behavior: 'smooth' });
```

---

## 6. Component Patterns

### 6.1 Resource header card

Every sample/dataset detail page has a header card with a colored left border:

```html
<div class="cg-resource-card mb-3" id="dsCard">
  {{ resource_card_identity(ds['dataset_name'], ds['unique_id'], icon='bi-database',
                            keywords=ds.get('keywords'), type_badge=ds.get('measurement')) }}
</div>
```

```javascript
document.getElementById('dsCard').style.borderLeftColor = hashColor(res_type || res_name);
```

No avatar circles — use a Bootstrap Icon (`bi-flask`, `bi-database`, `bi-collection`) at `font-size: var(--fs-2xl)`.

### 6.2 Resource sections (`res-section`)

Primary pattern for collapsible content on detail pages. Start primary sections expanded, secondary sections collapsed:

```html
<div class="res-section" id="section-details">
    <div class="res-section-header" onclick="toggleSection(this)">
        <i class="bi bi-card-list text-muted"></i>
        <span>Details</span>
        <i class="bi bi-chevron-right res-section-chevron" style="transform:rotate(90deg);"></i>
    </div>
    <div class="res-section-body"><!-- content --></div>
</div>
```

For collapsed-by-default: omit `style="transform:rotate(90deg)"` from chevron and add `style="display:none"` to body.

### 6.3 List rows

Clickable rows where text must be selectable (UUIDs, names):

```html
<div class="list-row" onmouseup="navIfNoSelection(event, '{{ base }}/pid/samples/id')">
    <span class="fw-medium">Sample name</span>
    <span class="mfid small ms-auto">unique-id</span>
</div>
```

Never use `<a>` for rows containing selectable text. `navIfNoSelection` is defined in `base.html`.

### 6.4 Metadata rows

```html
<div class="meta-row">
    <span class="meta-key">Field</span>
    <span class="text-break">value</span>
</div>
```

Use the `mrow()` / `mrow_link()` macros from `macros.html` — they handle None values gracefully.

### 6.5 Badges and count chips

```html
<span class="badge fw-normal border text-muted" style="background:var(--bs-tertiary-bg); font-size:var(--fs-xs);">12</span>
```

```html
<span class="cg-count-chip">4 items</span>
```

### 6.6 Action buttons (project card)

| Action | Element |
|---|---|
| Search | `<a href="/pid/search" class="action-link flex-fill py-2 border-end text-secondary">` |
| Chat | `<a href="/pid/chat" class="action-link flex-fill py-2 text-primary">` |

### 6.7 Empty states

```html
<div class="text-center text-muted py-5">
    <i class="bi bi-search fs-2 d-block mb-2 opacity-50"></i>
    No items match your filter.
</div>
```

### 6.8 Toasts

Use `cgToast(message, icon, duration)` defined in `base.html`:
```javascript
cgToast('Saved', 'bi-check-circle');
cgToast('Error uploading file', 'bi-exclamation-circle', 4000);
```

### 6.9 Collapsible groups (project overview)

Groups render via `buildGroupEl()` in `project_overview.html`. They use animated max-height transitions (not `display:none` toggling). Left border color from `hashColor(groupKey)`.

### 6.10 Projects dropdown

The top-left chevron dropdown reads from `localStorage('cg_all_projects')`. This key is written by `project_overview.html` on every load. Fall back to `localStorage('cg_recent_projects')` when not yet populated.

---

## 7. Icons

Use **Bootstrap Icons** (`bi-*`). Standard assignments:

| Concept | Icon |
|---|---|
| Project | `bi-collection` |
| Sample | `bi-flask` |
| Dataset | `bi-database` |
| Dashboard / home | `bi-house` |
| Search | `bi-search` |
| Chat / LLM | `bi-chat-dots` |
| Edit | `bi-pencil` |
| Upload photo | `bi-camera` |
| Download / files | `bi-download` |
| Graph / network | `bi-diagram-3` |
| User / profile | `bi-person-circle` |
| Users list | `bi-people` |
| Organization | `bi-building` |
| Back navigation | `bi-arrow-right` (points right, used in sidebar back strip) |
| Collapse chevron | `bi-chevron-right` (rotated 90° = open) |
| Expand/collapse all | `bi-chevron-expand` / `bi-chevron-contract` |
| Back to top | `bi-arrow-up` |

Always pair icons with text except in icon-only buttons (which require `title` attributes).

---

## 8. Dark / Light Theme

The app supports both themes via Bootstrap's `data-bs-theme` attribute. Theme is stored in `localStorage('theme')`. All styling must work in both modes.

**Rules:**
- Use CSS tokens (`var(--bs-body-bg)`, `var(--cg-hover-bg)`, etc.) — never hardcode `#fff` or `#000` for backgrounds/text
- Light-mode overrides for navbar-specific components live in `styles.css` under `[data-bs-theme="light"] .cg-*`
- The navbar is dark (`--cg-navy`) in dark mode, teal (`--cg-accent`) in light mode — both intentional

---

## 9. JavaScript Conventions

- Vanilla ES6 only. No frameworks.
- `localStorage` keys: `cg_*` prefix (e.g., `cg_sidebar_collapsed`, `cg_recent_projects`)
- Shared utilities (`hashColor`, `makeAvatar`, `cgToast`, `navIfNoSelection`, `toggleSection`, etc.) are defined in `base.html` and available globally
- Page-specific JS lives in `<script>` blocks at the bottom of each template's `{% block content %}`
- Use `getBoundingClientRect()` for all sticky offset calculations — never hardcode pixels

### 9.1 URL construction (deployment prefix)

The app is served behind a reverse proxy under a deployment prefix (e.g. `/explore`).
Every **internal** URL must carry that prefix or it 404s in production. One rule per context:

- **Jinja templates** → `{{ base }}/...` (or `base ~ '/...'`). `base` is `request.script_root`, injected globally.
- **JavaScript** → `cgUrl('/...')`. Defined in `base.html`; prepends `window.SCRIPT_ROOT`.
- **Server-side payloads** (JSON `url` fields, redirects) → prefix with `flask.request.script_root`.

```js
fetch(cgUrl(`/${projectId}/api/samples?q=${q}`));   // ✓
window.location.href = cgUrl(`/${pid}/datasets/${id}`); // ✓
fetch(`/${projectId}/api/samples`);                  // ✗ drops prefix → 404
```

External URLs (CDNs, signed GCS download links) are absolute and must **not** be prefixed.

Run `dev/lint_urls.sh` to catch prefix-less client URLs before committing.

---

## 10. Do's and Don'ts

### Do
- Use `var(--fs-*)` for every `font-size` — no exceptions
- Use `var(--cg-*)` and `var(--bs-*)` tokens for colors
- Use `navIfNoSelection` on all clickable rows with selectable content
- Compute sticky offsets dynamically from `getBoundingClientRect().height`
- Use `hashColor()` for all color assignments tied to entity IDs or type names
- Show full UUIDs — users copy them
- Use `.cg-sidebar-action` / `.cg-sidebar-section` for sidebar content
- Use `cgToast()` for user feedback (copy, save, error)
- Build internal URLs with `cgUrl()` in JS and `{{ base }}` in Jinja (see §9.1)

### Don't
- Don't hardcode `font-size` values — use the type scale
- Don't hardcode pixel offsets for sticky elements
- Don't hardcode `#fff` / `#000` or arbitrary hex colors for UI elements
- Don't use `<a>` tags for rows that contain selectable text
- Don't add avatar circle divs (replaced with Bootstrap Icons)
- Don't use `em` units for font-size in UI elements (use `rem` for predictability)
- Don't use Bootstrap 4 deprecated classes (`card-columns`, `text-left`, `float-left`)
- Don't use `onclick` on `<a>` to intercept navigation — use `onmouseup` + `<div>`
- Don't use `100vh` for full-screen layouts — use `100dvh` for mobile keyboard compatibility
- Don't load Bootstrap Icons or Google Fonts in individual templates — already in `base.html`
- Don't build internal URLs from bare `/...` literals in JS — they drop the deployment prefix and 404 (use `cgUrl()`)
