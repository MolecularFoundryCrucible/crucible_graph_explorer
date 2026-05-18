# Relationship Panel Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat, unstyled right relationship panel on sample/dataset detail pages with a collapsible, visually structured sidebar panel, and narrow the main content area from 860px to 680px reading width.

**Architecture:** Three self-contained tasks — CSS (new panel component classes + content width reduction), then the sample page panel, then the dataset page panel. No Python changes. The collapsible behaviour uses a single `toggleRelGroup(btn)` JS function added inline in each template's existing `<script>` block. The panel uses CSS `max-height` transition for smooth open/close animation, matching the existing `res-section` collapse pattern.

**Tech Stack:** Jinja2 templates, Bootstrap 5 utility classes, plain CSS/JS, IBM Plex Sans/Mono, brand CSS variables (`--cg-accent`, `--cg-accent-mid`, `--cg-hover-bg`, `--cg-link`, `--cg-shadow-sm`).

---

## File Map

| File | Change |
|---|---|
| `static/styles.css` | Add `.rel-panel`, `.rel-group`, `.rel-group-header`, `.rel-group-body`, `.rel-item` classes; reduce `res-section` max-width 860→680px |
| `flask_templates/sample_graph.html` | Replace right panel HTML; reduce 860→680px on flex wrapper, resource card, toolbar; add `toggleRelGroup` JS |
| `flask_templates/dataset.html` | Same as above for dataset-specific relationships |

---

## Task 1: CSS — panel component styles + content width

**Files:**
- Modify: `static/styles.css` — line 190 (`res-section` max-width) + append new classes at end of file

There are no unit tests for CSS. Verification is visual — load any sample or dataset page at ≥1200px viewport.

- [ ] **Step 1: Reduce `res-section` max-width from 860px to 680px**

In `static/styles.css` find this block (around line 187):
```css
.res-section {
    border: 1px solid var(--bs-border-color);
    border-radius: 0.5rem; overflow: hidden;
    margin-bottom: 1rem; max-width: 860px;
    box-shadow: var(--cg-shadow-sm);
    scroll-margin-top: 3.5rem;
}
```

Change `max-width: 860px` to `max-width: 680px`:
```css
.res-section {
    border: 1px solid var(--bs-border-color);
    border-radius: 0.5rem; overflow: hidden;
    margin-bottom: 1rem; max-width: 680px;
    box-shadow: var(--cg-shadow-sm);
    scroll-margin-top: 3.5rem;
}
```

- [ ] **Step 2: Append relationship panel CSS at the end of `static/styles.css`**

```css
/* ── relationship panel (right sidebar, xl+ screens) ───────────── */
.rel-panel {
    min-width: 320px; flex: 1; max-width: 380px;
    background: color-mix(in srgb, var(--cg-accent) 5%, var(--bs-body-bg));
    border: 1px solid var(--bs-border-color);
    border-left: 2px solid color-mix(in srgb, var(--cg-accent-mid) 30%, transparent);
    border-radius: 0.5rem; overflow: hidden;
    box-shadow: var(--cg-shadow-sm);
}
.rel-panel-title {
    display: flex; align-items: center; gap: 0.5rem;
    padding: 0.6rem 0.75rem;
    border-bottom: 1px solid var(--bs-border-color);
    font-size: 0.65rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 0.08em; color: var(--bs-secondary-color);
}
.rel-panel-title > i { color: var(--cg-accent-mid); }
.rel-panel-empty {
    text-align: center; padding: 2rem 1rem;
    font-size: 0.8rem; color: var(--bs-secondary-color);
}
.rel-group { border-bottom: 1px solid var(--bs-border-color); }
.rel-group:last-child { border-bottom: none; }
.rel-group-header {
    display: flex; align-items: center; gap: 0.5rem;
    width: 100%; padding: 0.5rem 0.75rem;
    background: none; border: none; border-left: 3px solid transparent;
    cursor: pointer; text-align: left; font-family: inherit;
    transition: background 0.12s, border-left-color 0.15s;
}
.rel-group-header:hover { background: var(--cg-hover-bg); }
.rel-group-header.open { border-left-color: var(--cg-accent-mid); }
.rel-group-label {
    flex: 1; font-size: 0.65rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--bs-secondary-color);
}
.rel-group-count {
    font-size: 0.72rem; color: var(--bs-secondary-color);
    font-family: 'IBM Plex Mono', monospace;
}
.rel-group-chevron {
    font-size: 0.65rem; color: var(--bs-secondary-color);
    transition: transform 0.2s;
}
.rel-group-header.open .rel-group-chevron { transform: rotate(90deg); }
.rel-group-body {
    overflow: hidden; max-height: 0;
    transition: max-height 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}
.rel-group-body.open { max-height: 800px; }
.rel-item {
    display: flex; align-items: center; gap: 0.5rem;
    padding: 0.38rem 0.75rem 0.38rem 1rem;
    font-size: 0.8rem; text-decoration: none;
    color: var(--bs-body-color);
    border-bottom: 1px solid var(--bs-border-color);
    box-shadow: inset 3px 0 0 transparent;
    transition: background 0.08s, box-shadow 0.1s, color 0.08s;
}
.rel-item:last-child { border-bottom: none; }
.rel-item:hover {
    background: var(--cg-hover-bg); color: var(--cg-link);
    box-shadow: inset 3px 0 0 var(--cg-accent-mid);
}
.rel-item-name { flex: 1; min-width: 0; }
.rel-item-name-text {
    display: block; overflow: hidden;
    text-overflow: ellipsis; white-space: nowrap;
}
.rel-item-sub {
    font-size: 0.7rem; color: var(--bs-secondary-color); white-space: nowrap;
}
```

- [ ] **Step 3: Commit**

```bash
git add static/styles.css
git commit -m "feat: add relationship panel CSS component, narrow res-section to 680px"
```

---

## Task 2: Sample page right panel redesign

**Files:**
- Modify: `flask_templates/sample_graph.html`
  - Lines 47–48: flex wrapper + max-width
  - Line 51: resource card max-width
  - Line 95: toolbar max-width
  - Lines 502–579: entire right panel block

The sample page relationships are: **Parents** (`direct_ancestors`), **Children** (`direct_descendants`), **Datasets** (`s['datasets']`).

- [ ] **Step 1: Reduce max-width from 860px to 680px on three elements**

Change line 48:
```html
<div style="flex: 1; min-width: 0; max-width: 680px;">
```

Change line 51:
```html
<div class="cg-resource-card mb-3" id="sampleCard" style="max-width:680px;">
```

Change line 95:
```html
<div class="d-flex align-items-center gap-1 mb-2" style="max-width:680px;">
```

- [ ] **Step 2: Replace right panel block (currently lines 502–579)**

Find the comment `<!-- ── right panel: relationships (xl+ only)` and replace everything from that comment through `</div>{# end outer flex row #}` with:

```html
<!-- ── right panel: relationships (xl+ only) ─────────────────────────── -->
<div class="rel-panel d-none d-xl-flex flex-column flex-shrink-0">
  <div style="position: sticky; top: 3.25rem; max-height: calc(100vh - 3.5rem); overflow-y: auto;">

    <!-- panel title -->
    <div class="rel-panel-title">
      <i class="bi bi-diagram-3"></i>
      Relationships
      {% set total = (direct_ancestors|length) + (direct_descendants|length) + (s['datasets']|length) %}
      {% if total %}<span class="ms-auto" style="font-family:'IBM Plex Mono',monospace; font-size:0.72rem;">{{ total }}</span>{% endif %}
    </div>

    {% if not direct_ancestors and not direct_descendants and not s['datasets'] %}
    <div class="rel-panel-empty">
      <i class="bi bi-diagram-3 d-block mb-2 opacity-40" style="font-size:1.5rem;"></i>
      No relationships
    </div>
    {% endif %}

    <!-- Parents -->
    {% if direct_ancestors %}
    <div class="rel-group">
      <button class="rel-group-header open" onclick="toggleRelGroup(this)">
        <i class="bi bi-arrow-up-short" style="color:var(--cg-accent-mid);"></i>
        <span class="rel-group-label">Parents</span>
        <span class="rel-group-count">{{ direct_ancestors|length }}</span>
        <i class="bi bi-chevron-right rel-group-chevron"></i>
      </button>
      <div class="rel-group-body open">
        {% for anc in direct_ancestors %}
        <a class="rel-item" href="/{{pid}}/samples/{{anc['unique_id']}}">
          <i class="bi bi-eyedropper" style="font-size:0.7rem; color:var(--cg-accent-mid); flex-shrink:0;"></i>
          <span class="rel-item-name"><span class="rel-item-name-text">{{anc['sample_name']}}</span></span>
        </a>
        {% endfor %}
      </div>
    </div>
    {% endif %}

    <!-- Children -->
    {% if direct_descendants %}
    <div class="rel-group">
      <button class="rel-group-header open" onclick="toggleRelGroup(this)">
        <i class="bi bi-arrow-down-short" style="color:var(--cg-accent-mid);"></i>
        <span class="rel-group-label">Children</span>
        <span class="rel-group-count">{{ direct_descendants|length }}</span>
        <i class="bi bi-chevron-right rel-group-chevron"></i>
      </button>
      <div class="rel-group-body open">
        {% for desc in direct_descendants %}
        <a class="rel-item" href="/{{pid}}/samples/{{desc['unique_id']}}">
          <i class="bi bi-eyedropper" style="font-size:0.7rem; color:var(--cg-accent-mid); flex-shrink:0;"></i>
          <span class="rel-item-name"><span class="rel-item-name-text">{{desc['sample_name']}}</span></span>
        </a>
        {% endfor %}
      </div>
    </div>
    {% endif %}

    <!-- Datasets -->
    {% if s['datasets'] %}
    <div class="rel-group">
      <button class="rel-group-header open" onclick="toggleRelGroup(this)">
        <i class="bi bi-database" style="color:var(--cg-accent-mid); font-size:0.8rem;"></i>
        <span class="rel-group-label">Datasets</span>
        <span class="rel-group-count">{{ s['datasets']|length }}</span>
        <i class="bi bi-chevron-right rel-group-chevron"></i>
      </button>
      <div class="rel-group-body open">
        {% for ds in s['datasets'] %}
        <a class="rel-item" href="/{{pid}}/datasets/{{ds['unique_id']}}">
          <i class="bi bi-database" style="font-size:0.7rem; color:var(--cg-accent-mid); flex-shrink:0;"></i>
          <span class="rel-item-name">
            <span class="rel-item-name-text">{{ds['dataset_name']}}</span>
            {% if ds.get('measurement') %}<span class="rel-item-sub">{{ds['measurement']}}</span>{% endif %}
          </span>
        </a>
        {% endfor %}
      </div>
    </div>
    {% endif %}

  </div>
</div>

</div>{# end outer flex row #}
```

- [ ] **Step 3: Add `toggleRelGroup` to the existing `<script>` block**

Find the closing `});` of the existing `document.addEventListener('DOMContentLoaded', ...)` block (near the end of the template's `<script>` section) and add the function before it, or simply append it anywhere in the `<script>` block:

```javascript
function toggleRelGroup(btn) {
    const body = btn.nextElementSibling;
    const open = btn.classList.toggle('open');
    body.classList.toggle('open', open);
}
```

- [ ] **Step 4: Verify visually**

Run Flask (`flask run --port 8000`), open any sample page at viewport width ≥1200px.

Expected:
- Main content sections are narrower (680px max)
- Right panel is visible, wider than before, with subtle tinted background
- Three groups (Parents, Children, Datasets) each with a header showing count and chevron
- Clicking a header collapses/expands the group with animation
- Hovering a row shows the teal left-flash and link color
- Groups start open (chevron rotated, left accent visible)

At viewport <1200px:
- Right panel hidden, relationship sections visible in main body (they have `d-xl-none` from previous work... wait — verify those sections are present. The `d-xl-none` sections in the main body are `section-datasets`, `section-ancestors`, `section-descendants` which remain for fallback.)

- [ ] **Step 5: Commit**

```bash
git add flask_templates/sample_graph.html
git commit -m "feat: redesign sample page relationship panel — collapsible groups, 680px content width"
```

---

## Task 3: Dataset page right panel redesign

**Files:**
- Modify: `flask_templates/dataset.html`
  - Lines 45–46: flex wrapper
  - Line 49: resource card max-width
  - Line 100: toolbar max-width
  - Lines 576–653: entire right panel block

The dataset page relationships are: **Samples** (`samples`), **Parents** (`parent_datasets`), **Children** (`child_datasets`).

- [ ] **Step 1: Reduce max-width from 860px to 680px on three elements**

Change line 46:
```html
<div style="flex: 1; min-width: 0; max-width: 680px;">
```

Change line 49:
```html
<div class="cg-resource-card mb-3" id="dsCard" style="max-width:680px;">
```

Change line 100:
```html
<div class="d-flex align-items-center gap-1 mb-2" style="max-width:680px;">
```

- [ ] **Step 2: Replace right panel block (currently lines 576–653)**

Find the comment `<!-- ── right panel: relationships (xl+ only)` and replace everything through `</div>{# end outer flex row #}` with:

```html
<!-- ── right panel: relationships (xl+ only) ─────────────────────────── -->
<div class="rel-panel d-none d-xl-flex flex-column flex-shrink-0">
  <div style="position: sticky; top: 3.25rem; max-height: calc(100vh - 3.5rem); overflow-y: auto;">

    <!-- panel title -->
    <div class="rel-panel-title">
      <i class="bi bi-diagram-3"></i>
      Relationships
      {% set total = (samples|length) + (parent_datasets|length) + (child_datasets|length) %}
      {% if total %}<span class="ms-auto" style="font-family:'IBM Plex Mono',monospace; font-size:0.72rem;">{{ total }}</span>{% endif %}
    </div>

    {% if not samples and not parent_datasets and not child_datasets %}
    <div class="rel-panel-empty">
      <i class="bi bi-diagram-3 d-block mb-2 opacity-40" style="font-size:1.5rem;"></i>
      No relationships
    </div>
    {% endif %}

    <!-- Samples -->
    {% if samples %}
    <div class="rel-group">
      <button class="rel-group-header open" onclick="toggleRelGroup(this)">
        <i class="bi bi-eyedropper" style="color:var(--cg-accent-mid); font-size:0.8rem;"></i>
        <span class="rel-group-label">Samples</span>
        <span class="rel-group-count">{{ samples|length }}</span>
        <i class="bi bi-chevron-right rel-group-chevron"></i>
      </button>
      <div class="rel-group-body open">
        {% for sample in samples %}
        <a class="rel-item" href="/{{project_id}}/samples/{{sample['unique_id']}}">
          <i class="bi bi-eyedropper" style="font-size:0.7rem; color:var(--cg-accent-mid); flex-shrink:0;"></i>
          <span class="rel-item-name">
            <span class="rel-item-name-text">{{sample['sample_name']}}</span>
            {% if sample.get('sample_type') %}<span class="rel-item-sub">{{sample['sample_type']}}</span>{% endif %}
          </span>
        </a>
        {% endfor %}
      </div>
    </div>
    {% endif %}

    <!-- Parent datasets -->
    {% if parent_datasets %}
    <div class="rel-group">
      <button class="rel-group-header open" onclick="toggleRelGroup(this)">
        <i class="bi bi-arrow-up-short" style="color:var(--cg-accent-mid);"></i>
        <span class="rel-group-label">Parents</span>
        <span class="rel-group-count">{{ parent_datasets|length }}</span>
        <i class="bi bi-chevron-right rel-group-chevron"></i>
      </button>
      <div class="rel-group-body open">
        {% for pd in parent_datasets %}
        <a class="rel-item" href="/{{project_id}}/datasets/{{pd['unique_id']}}">
          <i class="bi bi-database" style="font-size:0.7rem; color:var(--cg-accent-mid); flex-shrink:0;"></i>
          <span class="rel-item-name">
            <span class="rel-item-name-text">{{pd['dataset_name']}}</span>
            {% if pd.get('measurement') %}<span class="rel-item-sub">{{pd['measurement']}}</span>{% endif %}
          </span>
        </a>
        {% endfor %}
      </div>
    </div>
    {% endif %}

    <!-- Child datasets -->
    {% if child_datasets %}
    <div class="rel-group">
      <button class="rel-group-header open" onclick="toggleRelGroup(this)">
        <i class="bi bi-arrow-down-short" style="color:var(--cg-accent-mid);"></i>
        <span class="rel-group-label">Children</span>
        <span class="rel-group-count">{{ child_datasets|length }}</span>
        <i class="bi bi-chevron-right rel-group-chevron"></i>
      </button>
      <div class="rel-group-body open">
        {% for cd in child_datasets %}
        <a class="rel-item" href="/{{project_id}}/datasets/{{cd['unique_id']}}">
          <i class="bi bi-database" style="font-size:0.7rem; color:var(--cg-accent-mid); flex-shrink:0;"></i>
          <span class="rel-item-name">
            <span class="rel-item-name-text">{{cd['dataset_name']}}</span>
            {% if cd.get('measurement') %}<span class="rel-item-sub">{{cd['measurement']}}</span>{% endif %}
          </span>
        </a>
        {% endfor %}
      </div>
    </div>
    {% endif %}

  </div>
</div>

</div>{# end outer flex row #}
```

- [ ] **Step 3: Add `toggleRelGroup` to the existing `<script>` block**

```javascript
function toggleRelGroup(btn) {
    const body = btn.nextElementSibling;
    const open = btn.classList.toggle('open');
    body.classList.toggle('open', open);
}
```

- [ ] **Step 4: Verify visually**

Open any dataset page at ≥1200px viewport.

Expected:
- Main content narrower (680px)
- Right panel shows: Samples, Parents, Children groups — each collapsible
- Measurement type shown as subtitle on dataset items, sample type on sample items
- Empty state shown if no relationships exist

- [ ] **Step 5: Commit**

```bash
git add flask_templates/dataset.html
git commit -m "feat: redesign dataset page relationship panel — collapsible groups, 680px content width"
```

---

## Self-Review

**Spec coverage:**
- ✅ Panel wider (320px min, flex up to 380px — takes remaining space)
- ✅ Each group independently collapsible with smooth animation
- ✅ Cleaner visual separation (group borders, panel border treatment, tinted bg)
- ✅ Main body narrower (860px → 680px on all three elements: flex wrapper, resource card, toolbar; plus `res-section` in CSS)
- ✅ Consistent relationship sections: sample (Parents/Children/Datasets), dataset (Samples/Parents/Children)
- ✅ Sub-type shown as small text (measurement for datasets, sample_type for samples)
- ✅ Fallback at <xl: existing `d-xl-none` main body sections already handle this

**Placeholder scan:** No placeholders found. All code is complete and concrete.

**Type consistency:** `toggleRelGroup(btn)` referenced identically in Tasks 2 and 3. `direct_ancestors`, `direct_descendants`, `s['datasets']` in Task 2 match variables passed by the Flask `sample_graph` route. `samples`, `parent_datasets`, `child_datasets` in Task 3 match variables passed by the `dataset` route.
