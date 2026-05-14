# Frontend Polish & UX Overhaul — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Polish the crucible_graph_explorer UI with a compact resource card header, collapsible sidebar, navigation state preservation, sibling jump, recently-visited strip, show-mine filter, thumbnail lightbox, and improved list pages for Users and Instruments.

**Architecture:** Pure template/JS changes except Task 1 (pass siblings list from Flask routes). No new Python dependencies. All state persisted in `sessionStorage`/`localStorage`. Lightbox lives in `base.html`; all other changes are per-template.

**Tech Stack:** Flask/Jinja2, Bootstrap 5, Bootstrap Icons, vanilla JS, IBM Plex Sans/Mono

---

## Dev server

```bash
cd /home/roncofaber/software/crucible_graph_explorer
uv run flask --app crucible_graph_explore_flask_app run --debug
```

Open http://localhost:5000 in a browser to verify each task.

---

## Task 1: Pass full siblings list to Flask routes

**Files:**
- Modify: `routes/samples.py` (render_template call ~line 258)
- Modify: `routes/datasets.py` (render_template call ~line 84)

- [ ] **Step 1: Add `siblings=siblings` to `routes/samples.py`**

The `siblings` list is already computed at line 248. Add it to `render_template`:

```python
# routes/samples.py — in render_template call, after sibling_count=len(siblings),
siblings=siblings,
```

Full render_template block becomes:
```python
return render_template('sample_graph.html',
                       pc=pc,
                       self_info=self_info,
                       ancestors_info=ancestors_info,
                       descendants_info=descendants_info,
                       direct_ancestors=direct_ancestors,
                       indirect_ancestors=indirect_ancestors,
                       direct_descendants=direct_descendants,
                       indirect_descendants=indirect_descendants,
                       ancestors_path=ancestors_path,
                       descendants_path=descendants_path,
                       client=client,
                       datasets_by_id=pc['datasets_by_id'],
                       prev_sibling=prev_sibling,
                       next_sibling=next_sibling,
                       sibling_index=sibling_idx + 1,
                       sibling_count=len(siblings),
                       siblings=siblings,
                       img_datasets=img_datasets,
                       img_thumbnails=img_thumbnails)
```

- [ ] **Step 2: Add `siblings=ds_siblings` to `routes/datasets.py`**

```python
return render_template("dataset.html",
                       project_id=project_id, pc=pc, ds=ds,
                       child_datasets=child_datasets,
                       parent_datasets=parent_datasets,
                       samples=samples,
                       files=associated_files,
                       download_links=download_links,
                       thumbnails=thumbnails,
                       markdown_html=markdown_html,
                       custom_views=dataset_views.get_views(ds.get('measurement'), project_id, dsid),
                       prev_sibling=prev_sibling,
                       next_sibling=next_sibling,
                       sibling_index=ds_sibling_idx + 1,
                       sibling_count=len(ds_siblings),
                       siblings=ds_siblings)
```

- [ ] **Step 3: Verify**

Start dev server, open any sample page, check no 500 error. The template doesn't use `siblings` yet — this just makes it available.

- [ ] **Step 4: Commit**

```bash
git add routes/samples.py routes/datasets.py
git commit -m "feat: pass full siblings list to sample and dataset templates"
```

---

## Task 2: Navigation state preservation

**Files:**
- Modify: `flask_templates/project_overview.html`

- [ ] **Step 1: Add sessionStorage save when navigating to a resource**

In `project_overview.html`, find the closing `</script>` of the URL state helpers block (after `_writeHash` function, around line 810). Add before it:

```javascript
// Save current hash to sessionStorage when navigating to a resource page
document.addEventListener('click', (e) => {
    const link = e.target.closest('a[href]');
    if (!link) return;
    const href = link.getAttribute('href') || '';
    if (href.includes('/sample-graph/') || href.includes('/dataset/')) {
        sessionStorage.setItem('cg_overview_state_' + PID, location.hash || '#tab=samples');
    }
});
```

- [ ] **Step 2: Restore sessionStorage state on load**

In the init IIFE (around line 869, after the `const sgb = ...` lines), add before the `const hs = _readHash()` line:

```javascript
// Restore saved state if returning from a resource page and URL has no hash
if (!location.hash) {
    const stored = sessionStorage.getItem('cg_overview_state_' + PID);
    if (stored) {
        history.replaceState(null, '', stored);
    }
}
```

- [ ] **Step 3: Verify**

Start dev server → open a project overview → navigate to a sample → press browser Back. The overview should return to the same tab and filter you had.

- [ ] **Step 4: Commit**

```bash
git add flask_templates/project_overview.html
git commit -m "feat: preserve project overview tab/filter state across resource navigation"
```

---

## Task 3: Compact resource card header with sibling jump

**Files:**
- Modify: `flask_templates/sample_graph.html`
- Modify: `flask_templates/dataset.html`

### 3a — sample_graph.html

- [ ] **Step 1: Add CSS for the new compact card**

In `{% block head %}` of `sample_graph.html`, after the existing `<style>` block content, append:

```css
/* ── compact resource card ─────────────────────────────────────────────── */
.cg-resource-card {
    border: 1px solid var(--bs-border-color);
    border-left-width: 5px;
    border-radius: 0.375rem;
    overflow: hidden;
    background: var(--bs-body-bg);
}
.cg-card-identity {
    display: flex; align-items: flex-start; gap: 0.75rem;
    padding: 0.75rem 1rem;
}
.cg-card-avatar {
    width: 2rem; height: 2rem; min-width: 2rem; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.7rem; font-weight: 700; flex-shrink: 0; color: #fff;
}
.cg-card-names { flex: 1; min-width: 0; }
.cg-card-title { font-size: 1.05rem; font-weight: 600; margin: 0 0 0.15rem; line-height: 1.3; overflow-wrap: break-word; }
.cg-card-uuid { font-size: 0.78rem; }
.cg-count-chip {
    display: inline-flex; align-items: center; padding: 2px 8px;
    border-radius: 10px; font-size: 0.72rem; white-space: nowrap;
    border: 1px solid rgba(58,122,135,0.25); background: rgba(58,122,135,0.07); color: var(--cg-link);
}
.cg-card-actions {
    display: flex; align-items: center; gap: 0.4rem; flex-wrap: wrap;
    padding: 0.35rem 0.75rem;
    border-top: 1px solid var(--bs-border-color);
    background: var(--bs-tertiary-bg);
}
/* sibling nav */
.cg-sibling-nav { display: flex; align-items: center; gap: 0.3rem; position: relative; }
.cg-sib-btn {
    display: inline-flex; align-items: center; justify-content: center;
    width: 1.6rem; height: 1.6rem; border-radius: 0.25rem;
    border: 1px solid var(--bs-border-color); background: var(--bs-body-bg);
    color: var(--bs-secondary-color); font-size: 0.75rem; cursor: pointer;
    text-decoration: none; transition: background 0.12s; padding: 0;
}
.cg-sib-btn:hover:not([disabled]) { background: var(--bs-body-bg); color: var(--bs-body-color); }
.cg-sib-btn[disabled] { opacity: 0.4; cursor: default; pointer-events: none; }
.cg-sib-label { font-size: 0.8rem; color: var(--bs-secondary-color); white-space: nowrap; padding: 0 0.2rem; }
.cg-sib-type { font-size: 0.75rem; margin-left: 0.2rem; opacity: 0.7; }
.cg-sib-jump-btn {
    border: 1px solid var(--cg-accent-mid); border-radius: 0.25rem;
    padding: 0.15rem 0.5rem; font-size: 0.78rem; background: var(--bs-body-bg);
    color: var(--cg-link); cursor: pointer; white-space: nowrap; transition: background 0.12s;
}
.cg-sib-jump-btn:hover { background: var(--bs-tertiary-bg); }
.cg-sib-dropdown {
    position: absolute; top: calc(100% + 4px); left: 0; z-index: 600;
    min-width: 200px; max-width: 320px; max-height: 280px; overflow-y: auto;
    background: var(--bs-body-bg); border: 1px solid var(--bs-border-color);
    border-radius: 0.375rem; box-shadow: 0 4px 16px rgba(0,0,0,0.15);
}
.cg-sib-item {
    display: block; padding: 0.4rem 0.75rem; font-size: 0.82rem;
    color: var(--bs-body-color); text-decoration: none;
    border-bottom: 1px solid var(--bs-border-color);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    transition: background 0.08s;
}
.cg-sib-item:last-child { border-bottom: none; }
.cg-sib-item:hover { background: var(--bs-tertiary-bg); }
.cg-sib-item.active { background: rgba(58,122,135,0.08); color: var(--cg-link); font-weight: 600; }
/* action buttons */
.cg-action-btn {
    display: inline-flex; align-items: center; justify-content: center;
    height: 1.7rem; padding: 0 0.5rem; border-radius: 0.25rem;
    border: 1px solid var(--bs-border-color); background: var(--bs-body-bg);
    color: var(--bs-secondary-color); font-size: 0.82rem; text-decoration: none;
    cursor: pointer; transition: background 0.12s, color 0.12s; white-space: nowrap; gap: 0.25rem;
}
.cg-action-btn:hover { color: var(--bs-body-color); }
.cg-action-btn.primary { background: var(--cg-link); border-color: var(--cg-link); color: #fff; }
.cg-action-btn.primary:hover { background: #2e6370; border-color: #2e6370; color: #fff; }
```

- [ ] **Step 2: Replace the header card HTML in sample_graph.html**

Remove everything from line 118 (`<!-- ── sample header card`) through line 222 (end of sibling nav + expand/collapse toolbar div). Replace with:

```html
{{ deletion_banner(s) }}

<!-- ── compact resource card ────────────────────────────────────────────── -->
<div class="cg-resource-card mb-3" id="sampleCard" style="max-width:860px;">

  <!-- Identity strip -->
  <div class="cg-card-identity">
    <div id="sampleAvatar" class="cg-card-avatar"></div>
    <div class="cg-card-names">
      <h1 class="cg-card-title">{{s['sample_name']}}</h1>
      <div class="mfid cg-card-uuid">{{s['unique_id']}}</div>
      {% set kws = s.get('keywords') %}
      {% if kws %}
      <div class="d-flex flex-wrap gap-1 mt-1">
        {% for kw in (kws if kws is sequence and kws is not string else [kws]) %}
        <span class="badge fw-normal border text-body-secondary" style="background:var(--bs-tertiary-bg); font-size:0.7rem;">{{kw}}</span>
        {% endfor %}
      </div>
      {% endif %}
    </div>
    <div class="d-flex flex-wrap gap-1 align-items-start flex-shrink-0">
      {% if s.get('sample_type') %}
      <span class="badge fw-normal border text-body-secondary" style="background:var(--bs-tertiary-bg);">{{s['sample_type']}}</span>
      {% endif %}
      {% if s['datasets'] %}
      <span class="cg-count-chip"><i class="bi bi-database me-1" style="font-size:0.8em;"></i>{{s['datasets']|length}}</span>
      {% endif %}
    </div>
  </div>

  <!-- Action strip -->
  <div class="cg-card-actions">
    <div class="cg-sibling-nav">
      {% if sibling_count > 1 %}
        {% if prev_sibling %}
        <a class="cg-sib-btn" href="/{{pid}}/sample-graph/{{prev_sibling['unique_id']}}" title="{{prev_sibling['sample_name']}}"><i class="bi bi-chevron-left"></i></a>
        {% else %}
        <button class="cg-sib-btn" disabled><i class="bi bi-chevron-left"></i></button>
        {% endif %}
        <span class="cg-sib-label">{{sibling_index}}&thinsp;/&thinsp;{{sibling_count}}{% if s.get('sample_type') %}<span class="cg-sib-type">{{s['sample_type']}}</span>{% endif %}</span>
        {% if next_sibling %}
        <a class="cg-sib-btn" href="/{{pid}}/sample-graph/{{next_sibling['unique_id']}}" title="{{next_sibling['sample_name']}}"><i class="bi bi-chevron-right"></i></a>
        {% else %}
        <button class="cg-sib-btn" disabled><i class="bi bi-chevron-right"></i></button>
        {% endif %}
        <button class="cg-sib-jump-btn" onclick="toggleSibJump(event)">Jump <i class="bi bi-chevron-down" style="font-size:0.7em;"></i></button>
        <div id="sibJumpDropdown" class="cg-sib-dropdown" style="display:none;">
          {% for sib in siblings %}
          <a class="cg-sib-item {% if sib['unique_id'] == s['unique_id'] %}active{% endif %}"
             href="/{{pid}}/sample-graph/{{sib['unique_id']}}">{{sib['sample_name']}}</a>
          {% endfor %}
        </div>
      {% endif %}
    </div>
    <div class="d-flex align-items-center gap-1 ms-auto flex-wrap">
      <div class="d-flex align-items-center gap-1 me-1">
        <button class="cg-action-btn" style="font-size:0.78rem;" onclick="setAllSections(true)"><i class="bi bi-chevron-expand"></i></button>
        <button class="cg-action-btn" style="font-size:0.78rem;" onclick="setAllSections(false)"><i class="bi bi-chevron-contract"></i></button>
      </div>
      <a href="/{{pid}}/search" class="cg-action-btn" title="Search"><i class="bi bi-search"></i></a>
      <a href="/{{pid}}/entity-graph/sample/{{s['unique_id']}}" class="cg-action-btn" title="Entity graph"><i class="bi bi-diagram-3"></i></a>
      <a href="/{{pid}}/samples/{{s['unique_id']}}/upload-photo" class="cg-action-btn" title="Upload photo"><i class="bi bi-camera"></i></a>
      <a href="/{{pid}}/samples/{{s['unique_id']}}/edit" class="cg-action-btn" title="Edit"><i class="bi bi-pencil"></i></a>
      <button class="cg-action-btn" onclick="document.getElementById('qrPopover').style.display=document.getElementById('qrPopover').style.display?'':'block'" title="QR code"><i class="bi bi-qr-code"></i></button>
      <a href="/{{pid}}/chat?about=sample:{{s['unique_id']}}" class="cg-action-btn primary"><i class="bi bi-chat-dots"></i> Chat</a>
    </div>
  </div>

  <!-- QR popover -->
  <div id="qrPopover" style="display:none; padding:0.75rem 1rem; border-top:1px solid var(--bs-border-color);">
    <img src="{{ qrcode(s['unique_id'], box_size=4, border=4) }}" style="border-radius:4px; display:block; margin-bottom:0.4rem;">
    <div class="mfid small text-muted">{{s['unique_id']}}</div>
  </div>
</div>
```

- [ ] **Step 3: Add sibling jump JS and remove old compact header JS**

In the `<script>` block at the bottom of sample_graph.html, remove the `#compactHeader` IntersectionObserver block (the section from `const compactHeader = ...` through the end). Add instead:

```javascript
function toggleSibJump(event) {
    event.stopPropagation();
    const dd = document.getElementById('sibJumpDropdown');
    if (dd) dd.style.display = dd.style.display === 'none' ? '' : 'none';
}
document.addEventListener('click', () => {
    const dd = document.getElementById('sibJumpDropdown');
    if (dd) dd.style.display = 'none';
});
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
        const dd = document.getElementById('sibJumpDropdown');
        if (dd) dd.style.display = 'none';
    }
});
```

Also update the avatar JS (already present near bottom) — change `makeAvatar(document.getElementById('sampleAvatar'), ...)` to target `.cg-card-avatar` (same element id `sampleAvatar` still works, just verify the call is present).

- [ ] **Step 4: Apply same changes to dataset.html**

Repeat Steps 1–3 for `flask_templates/dataset.html`, with these differences:
- Replace `s['sample_name']` → `ds['dataset_name']`
- Replace `s['unique_id']` → `ds['unique_id']`
- Replace `s.get('sample_type')` → `ds.get('measurement')`
- Replace `s['datasets']` count chip with samples count: `{% if samples %}<span class="cg-count-chip"><i class="bi bi-eyedropper me-1"></i>{{samples|length}}</span>{% endif %}`
- Sibling URL: `/{{project_id}}/dataset/{{sib['unique_id']}}`
- Chat link: `href="/{{project_id}}/chat?about=dataset:{{ds['unique_id']}}"`
- Remove the old `prev_sibling`/`next_sibling`/`sibling_count` block that was at the same location

- [ ] **Step 5: Verify**

Start dev server. Open a sample page with siblings — check the compact card, sibling counter, and Jump dropdown. Open a dataset page — same check.

- [ ] **Step 6: Commit**

```bash
git add flask_templates/sample_graph.html flask_templates/dataset.html
git commit -m "feat: compact resource card header with sibling jump dropdown"
```

---

## Task 4: Collapsible sidebar

**Files:**
- Modify: `flask_templates/sample_graph.html`
- Modify: `flask_templates/dataset.html`

- [ ] **Step 1: Add sidebar CSS to sample_graph.html `{% block head %}`**

Append to the `<style>` block:

```css
/* ── collapsible sidebar ────────────────────────────────────────────────── */
.cg-sidebar {
    width: 160px; flex-shrink: 0; position: relative;
    transition: width 0.25s cubic-bezier(0.4,0,0.2,1);
    border-right: 1px solid var(--bs-border-color);
    margin-right: 0.75rem;
}
.cg-sidebar.collapsed { width: 40px; }
.cg-sidebar-toggle {
    position: absolute; right: -10px; top: 5.5rem; z-index: 200;
    width: 20px; height: 20px; border-radius: 50%;
    border: 1px solid var(--bs-border-color); background: var(--bs-body-bg);
    color: var(--bs-secondary-color); cursor: pointer;
    display: flex; align-items: center; justify-content: center;
    font-size: 0.65rem; box-shadow: 0 1px 4px rgba(0,0,0,0.1);
    transition: background 0.15s;
}
.cg-sidebar-toggle:hover { background: var(--bs-tertiary-bg); }
.cg-sidebar-toggle i { transition: transform 0.25s; }
.cg-sidebar.collapsed .cg-sidebar-toggle i { transform: rotate(180deg); }
.cg-sidebar-content {
    position: sticky; top: 5em; max-height: calc(100vh - 5.5em);
    overflow-y: auto; padding: 0.5rem 0; display: flex; flex-direction: column;
    overflow: hidden;
}
.cg-sidebar.collapsed .cg-sidebar-content { visibility: hidden; }
.cg-sidebar-icon-rail {
    position: sticky; top: 5em;
    display: none; flex-direction: column; align-items: center;
    gap: 0.5rem; padding-top: 0.5rem;
}
.cg-sidebar.collapsed .cg-sidebar-icon-rail { display: flex; }
.cg-rail-btn {
    width: 28px; height: 28px; border-radius: 0.25rem;
    display: flex; align-items: center; justify-content: center;
    color: var(--bs-secondary-color); font-size: 0.9rem;
    text-decoration: none; border: none; background: none;
    transition: background 0.12s; cursor: pointer; padding: 0;
}
.cg-rail-btn:hover { background: var(--bs-tertiary-bg); color: var(--bs-body-color); }
```

- [ ] **Step 2: Replace `{% block sidebar %}` in sample_graph.html**

Replace the entire `{% block sidebar %}...{% endblock %}` block with:

```html
{% block sidebar %}
<div id="resourceSidebar" class="cg-sidebar d-none d-md-block">
  <button class="cg-sidebar-toggle" onclick="toggleSidebar()" title="Toggle sidebar">
    <i class="bi bi-chevron-left" id="sidebarToggleIcon"></i>
  </button>

  <div class="cg-sidebar-content" id="sidebarContent">
    <div class="mb-2 px-2">
      <div class="d-flex align-items-center gap-2 mb-1">
        <div id="projectAvatar" style="flex-shrink:0;"></div>
        <span class="fw-semibold small text-body text-truncate">{{pid}}</span>
      </div>
      <a href="javascript:void(0)" onclick="goBackToProject()" class="nav-link py-1 px-1 text-muted small">
        <i class="bi bi-arrow-left me-1"></i>Back to project
      </a>
    </div>
    <hr class="my-1 mx-2">
    <div class="px-2 mb-1" style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--cg-link);">
      <i class="bi bi-eyedropper me-1"></i>This sample
    </div>
    <div class="px-2 mb-2 small fw-semibold text-body" style="font-size:0.8rem; word-break:break-word;">{{s['sample_name']}}</div>
    <hr class="my-1 mx-2">

    {% if s['datasets'] %}
    <div class="px-2 mb-1" style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--bs-secondary-color);">
      <i class="bi bi-database me-1"></i>Datasets ({{s['datasets']|length}})
    </div>
    <ul class="nav flex-column mb-2" style="overflow-y:auto; max-height:30vh;">
      {% for ds in s['datasets'] %}
      <li class="nav-item">
        <a class="nav-link py-1 px-2 text-body" style="font-size:0.8rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" href="/{{pid}}/dataset/{{ds['unique_id']}}">{{ds['dataset_name']}}</a>
      </li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if ancestors_info %}
    <div class="px-2 mb-1" style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--bs-secondary-color);">
      <i class="bi bi-arrow-up-short me-1"></i>Ancestors ({{ancestors_info|length}})
    </div>
    <ul class="nav flex-column mb-2">
      {% for anc in ancestors_info %}
      <li><a class="nav-link py-1 px-2 text-body" style="font-size:0.8rem;" href="/{{pid}}/sample-graph/{{anc['unique_id']}}">{{anc['sample_name']}}</a></li>
      {% endfor %}
    </ul>
    {% endif %}

    {% if descendants_info %}
    <div class="px-2 mb-1" style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--bs-secondary-color);">
      <i class="bi bi-arrow-down-short me-1"></i>Descendants ({{descendants_info|length}})
    </div>
    <ul class="nav flex-column mb-2">
      {% for desc in descendants_info %}
      <li><a class="nav-link py-1 px-2 text-body" style="font-size:0.8rem;" href="/{{pid}}/sample-graph/{{desc['unique_id']}}">{{desc['sample_name']}}</a></li>
      {% endfor %}
    </ul>
    {% endif %}
  </div>

  <!-- Icon rail shown when collapsed -->
  <div class="cg-sidebar-icon-rail" id="sidebarIconRail">
    <div id="projectAvatarRail" style="width:24px;height:24px;border-radius:50%;"></div>
    <button class="cg-rail-btn" onclick="goBackToProject()" title="Back to project"><i class="bi bi-house"></i></button>
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Update `{% block main_col_class %}` in sample_graph.html**

```html
{% block main_col_class %}col-12 col-md{% endblock %}
```

(Bootstrap 5's `col-md` without a number uses `flex: 1 0 0%` — fills remaining space.)

- [ ] **Step 4: Add sidebar JS to sample_graph.html**

In the bottom `<script>` block, add:

```javascript
const _SIDEBAR_KEY = 'cg_sidebar_collapsed';
const _PID = {{ pid | tojson }};

function goBackToProject() {
    const stored = sessionStorage.getItem('cg_overview_state_' + _PID);
    window.location.href = '/' + _PID + '/' + (stored || '');
}

function toggleSidebar() {
    const sb = document.getElementById('resourceSidebar');
    const collapsed = sb.classList.toggle('collapsed');
    localStorage.setItem(_SIDEBAR_KEY, collapsed ? '1' : '');
}

// Restore collapse state
(function() {
    if (localStorage.getItem(_SIDEBAR_KEY)) {
        const sb = document.getElementById('resourceSidebar');
        if (sb) sb.classList.add('collapsed');
    }
    // Render small project avatar in icon rail
    const railAv = document.getElementById('projectAvatarRail');
    if (railAv) makeAvatar(railAv, _PID, '24px', '0.65rem');
})();
```

Also update the existing avatar JS — find `makeAvatar(projAv, ...)` and update:

```javascript
const projAv = document.getElementById('projectAvatar');
if (projAv) makeAvatar(projAv, _PID, '1.5rem', '0.6rem');
```

- [ ] **Step 5: Apply same sidebar to dataset.html**

Repeat Steps 1–4 for `flask_templates/dataset.html`, changing:
- "This sample" label → "This dataset" with `bi-database` icon
- `s['sample_name']` → `ds['dataset_name']`
- `s['datasets']` section → show `samples` list with eyedropper icon
- Add `parent_datasets` and `child_datasets` sections similarly
- `pid` is `project_id` in dataset.html — use `{{ project_id | tojson }}` for `_PID`

- [ ] **Step 6: Verify**

Open sample and dataset pages. The sidebar should be visible by default (~160px). Clicking the toggle button collapses it to a 40px icon rail. Reload — state persists. Back button goes to the project overview at the right tab/filter.

- [ ] **Step 7: Commit**

```bash
git add flask_templates/sample_graph.html flask_templates/dataset.html
git commit -m "feat: collapsible sidebar on resource pages with state-aware back link"
```

---

## Task 5: Recently visited strip + "Show mine" toggle

**Files:**
- Modify: `flask_templates/project_overview.html`

- [ ] **Step 1: Add CSS for recently-visited chips and show-mine button**

In the `<style>` block of `project_overview.html`, append:

```css
/* ── recently visited strip ──────────────────────────────────────────── */
#recentlyVisited {
    display: flex; align-items: center; gap: 0.4rem;
    flex-wrap: nowrap; overflow-x: auto; padding-bottom: 0.25rem;
    scrollbar-width: thin;
}
.cg-recent-chip {
    display: inline-flex; align-items: center; gap: 0.3rem;
    padding: 0.2rem 0.6rem; border-radius: 10px; white-space: nowrap;
    border: 1px solid var(--bs-border-color); background: var(--bs-tertiary-bg);
    color: var(--bs-body-color); font-size: 0.78rem; text-decoration: none;
    max-width: 160px; transition: border-color 0.12s, background 0.12s;
}
.cg-recent-chip span { overflow: hidden; text-overflow: ellipsis; }
.cg-recent-chip:hover { border-color: var(--cg-accent-mid); background: var(--bs-body-bg); color: var(--bs-body-color); }
```

- [ ] **Step 2: Add recently-visited strip HTML**

Find the tab bar section (the sticky tab div with `tab-stat` elements). Immediately after the closing `</div>` of the tab bar, add:

```html
<!-- ── recently visited ─────────────────────────────────────────────── -->
<div id="recentlyVisited" class="mb-2" style="display:none;"></div>
```

- [ ] **Step 3: Add "Show mine" toggle button**

Find the filter input (`<input ... id="filterInput" ...>`). Immediately after it (still inside the toolbar flex container), add:

```html
<button id="showMineToggle" class="btn btn-sm btn-outline-secondary text-nowrap"
        onclick="toggleShowMine()" title="Show only my resources">
    <i class="bi bi-person-check me-1"></i>Mine
</button>
```

- [ ] **Step 4: Add JS for both features**

In the main `<script>` block, after the existing `const PID = ...` line, add:

```javascript
const CURRENT_USER_ORCID = {{ current_user_orcid | tojson }};
let showMineOnly = false;

function toggleShowMine() {
    showMineOnly = !showMineOnly;
    const btn = document.getElementById('showMineToggle');
    btn.classList.toggle('btn-outline-secondary', !showMineOnly);
    btn.classList.toggle('btn-primary', showMineOnly);
    applyFilter();
}

function _esc(s) {
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function renderRecentlyVisited() {
    const container = document.getElementById('recentlyVisited');
    if (!container) return;
    try {
        const all = JSON.parse(localStorage.getItem('cg_recent_resources') || '[]');
        const forProject = all.filter(r => r.projectId === PID).slice(0, 6);
        if (!forProject.length) { container.style.display = 'none'; return; }
        container.style.display = 'flex';
        container.innerHTML =
            '<span style="font-size:0.7rem;font-weight:600;text-transform:uppercase;letter-spacing:0.07em;color:var(--bs-secondary-color);white-space:nowrap;flex-shrink:0;">Recent</span>' +
            forProject.map(r => {
                const icon = r.type === 'sample' ? 'bi-eyedropper' : 'bi-database';
                const url  = r.type === 'sample'
                    ? `/${PID}/sample-graph/${r.id}`
                    : `/${PID}/dataset/${r.id}`;
                return `<a href="${url}" class="cg-recent-chip">
                    <i class="bi ${icon}" style="color:var(--cg-accent-mid);font-size:0.8em;flex-shrink:0;"></i>
                    <span>${_esc(r.name)}</span>
                </a>`;
            }).join('');
    } catch { container.style.display = 'none'; }
}
```

- [ ] **Step 5: Wire show-mine into the existing filter logic**

Find the function that renders each sample/dataset row HTML (the function that builds `.list-row` elements). Add `data-owner-orcid="${esc(item.owner_orcid || '')}"` to the row element.

Then find `applyFilter()` in the template. Inside the section that sets `row.style.display`, add the mine filter check:

```javascript
// Inside applyFilter's row-visibility logic, add:
const matchesMine = !showMineOnly || !CURRENT_USER_ORCID
    || (row.dataset.ownerOrcid === CURRENT_USER_ORCID);
// Include matchesMine in the show condition alongside existing checks
```

- [ ] **Step 6: Call renderRecentlyVisited() in the init IIFE**

At the end of the init IIFE (after the fetch call for overview data), add:

```javascript
renderRecentlyVisited();
```

- [ ] **Step 7: Verify**

Open the project overview. Navigate to a sample/dataset and come back — the recently visited strip should show chips. Click "Mine" — only your resources should appear.

- [ ] **Step 8: Commit**

```bash
git add flask_templates/project_overview.html
git commit -m "feat: recently visited strip and show-mine filter on project overview"
```

---

## Task 6: Thumbnail lightbox

**Files:**
- Modify: `flask_templates/base.html`
- Modify: `flask_templates/sample_graph.html`
- Modify: `flask_templates/dataset.html`

- [ ] **Step 1: Add lightbox HTML + CSS + JS to base.html**

Find `<div id="cg-toast-container" ...>` in `base.html`. Immediately before it, add:

```html
<!-- ── thumbnail lightbox ────────────────────────────────────────────── -->
<div id="cgLightbox" onclick="if(event.target===this)cgLbClose()"
     style="display:none; position:fixed; inset:0; z-index:5000;
            background:rgba(0,0,0,0.88); align-items:center; justify-content:center; gap:1rem;">
    <button onclick="cgLbNav(-1)" style="background:none; border:none; color:rgba(255,255,255,0.7);
            font-size:2.5rem; cursor:pointer; padding:0 0.5rem; line-height:1;
            transition:color 0.12s;" onmouseover="this.style.color='#fff'" onmouseout="this.style.color='rgba(255,255,255,0.7)'">&#8249;</button>
    <div style="text-align:center; max-width:88vw;">
        <img id="cgLbImg" src="" alt="" style="max-width:88vw; max-height:80vh; border-radius:6px; display:block;">
        <div id="cgLbLabel" style="color:rgba(255,255,255,0.75); font-size:0.85rem; margin-top:0.6rem; font-family:'IBM Plex Sans',sans-serif;"></div>
        <div id="cgLbCounter" style="color:rgba(255,255,255,0.4); font-size:0.75rem; margin-top:0.2rem; font-family:'IBM Plex Mono',monospace;"></div>
    </div>
    <button onclick="cgLbNav(1)" style="background:none; border:none; color:rgba(255,255,255,0.7);
            font-size:2.5rem; cursor:pointer; padding:0 0.5rem; line-height:1;
            transition:color 0.12s;" onmouseover="this.style.color='#fff'" onmouseout="this.style.color='rgba(255,255,255,0.7)'">&#8250;</button>
    <button onclick="cgLbClose()" style="position:absolute; top:1rem; right:1.25rem;
            background:none; border:none; color:rgba(255,255,255,0.6); font-size:1.5rem;
            cursor:pointer; line-height:1;">&#x2715;</button>
</div>
```

In the `<script>` block where `cgToast` is defined, add after it:

```javascript
// ── thumbnail lightbox ─────────────────────────────────────────────────
(function() {
    let _lbItems = [];
    let _lbIdx   = 0;
    const _lb    = document.getElementById('cgLightbox');

    window.cgLbOpen = function(items, startIdx) {
        _lbItems = items;
        _lbIdx   = startIdx || 0;
        _lbRender();
        _lb.style.display = 'flex';
        document.body.style.overflow = 'hidden';
    };
    window.cgLbClose = function() {
        _lb.style.display = 'none';
        document.body.style.overflow = '';
    };
    window.cgLbNav = function(dir) {
        _lbIdx = (_lbIdx + dir + _lbItems.length) % _lbItems.length;
        _lbRender();
    };
    window.cgLbOpenSection = function(imgEl) {
        const body = imgEl.closest('.res-section-body') || document.body;
        const all  = Array.from(body.querySelectorAll('[data-lb-src]'));
        const items = all.map(img => ({ src: img.dataset.lbSrc, label: img.dataset.lbLabel || '' }));
        const idx  = all.indexOf(imgEl);
        cgLbOpen(items, Math.max(idx, 0));
    };
    function _lbRender() {
        document.getElementById('cgLbImg').src       = _lbItems[_lbIdx].src;
        document.getElementById('cgLbLabel').textContent   = _lbItems[_lbIdx].label || '';
        document.getElementById('cgLbCounter').textContent =
            _lbItems.length > 1 ? `${_lbIdx + 1} / ${_lbItems.length}` : '';
    }
    document.addEventListener('keydown', e => {
        if (_lb.style.display === 'none') return;
        if (e.key === 'Escape')      cgLbClose();
        if (e.key === 'ArrowLeft')   cgLbNav(-1);
        if (e.key === 'ArrowRight')  cgLbNav(1);
    });
})();
```

- [ ] **Step 2: Wire lightbox into sample_graph.html thumbnails section**

Find the thumbnails `{% for ds in img_datasets %}` block. Replace the `<img>` tag with:

```html
<img src="{{img_thumbnails[dsid]}}"
     data-lb-src="{{img_thumbnails[dsid]}}"
     data-lb-label="{{ds['dataset_name']}}"
     onclick="cgLbOpenSection(this)"
     alt="{{ds['dataset_name']}}"
     style="width:120px;height:120px;object-fit:cover;border-radius:0.375rem;
            border:1px solid var(--bs-border-color);cursor:pointer;
            transition:opacity 0.12s;" onmouseover="this.style.opacity='0.85'" onmouseout="this.style.opacity='1'">
```

- [ ] **Step 3: Wire lightbox into dataset.html thumbnails section**

Find the thumbnails rendering in `dataset.html` (the `{% for thumb_url in thumbnails %}` or similar block). Add `data-lb-src`, `data-lb-label`, and `onclick="cgLbOpenSection(this)"` to each `<img>` tag the same way as Step 2.

- [ ] **Step 4: Verify**

Open a sample page that has thumbnails. Click a thumbnail — lightbox opens. Arrow keys navigate between thumbnails. Escape closes it.

- [ ] **Step 5: Commit**

```bash
git add flask_templates/base.html flask_templates/sample_graph.html flask_templates/dataset.html
git commit -m "feat: thumbnail lightbox with keyboard navigation"
```

---

## Task 7: Users page — sticky search and layout polish

**Files:**
- Modify: `flask_templates/users.html`

- [ ] **Step 1: Make search + controls sticky**

In `users.html`, wrap the existing search/filter controls in a sticky container. Find:
```html
<div class="d-flex align-items-center gap-2 mb-4 flex-wrap">
```
Replace with:
```html
<div class="d-flex align-items-center gap-2 mb-3 flex-wrap"
     style="position:sticky; top:3.2rem; z-index:20; background:var(--bs-body-bg);
            padding:0.5rem 0; margin-top:-0.25rem; border-bottom:1px solid var(--bs-border-color);">
```

- [ ] **Step 2: Add user count badge to the heading**

Find:
```html
<h1 class="fs-4 fw-semibold mb-0">
    <i class="bi bi-people me-2 text-secondary"></i>Users
</h1>
```
Replace with:
```html
<h1 class="fs-4 fw-semibold mb-0">
    <i class="bi bi-people me-2 text-secondary"></i>Users
    <span id="userVisibleCount" class="text-muted fw-normal ms-1" style="font-size:0.85rem;"></span>
</h1>
```

- [ ] **Step 3: Update count display in JS**

In the `applyFilter()` function, after the `totalVisible += visible` line, add:

```javascript
const countEl = document.getElementById('userVisibleCount');
if (countEl) {
    const totalUsers = document.querySelectorAll('.list-row[data-search]').length;
    countEl.textContent = (q || showUnique) ? `${totalVisible} of ${totalUsers}` : `${totalUsers}`;
}
```

- [ ] **Step 4: Call count update on init**

At the end of the `<script>` block, add:

```javascript
// Initial count
(function() {
    const total = document.querySelectorAll('.list-row[data-search]').length;
    const el = document.getElementById('userVisibleCount');
    if (el) el.textContent = total;
})();
```

- [ ] **Step 5: Verify**

Open `/users`. Search bar sticks to top when scrolling. Count updates as you filter.

- [ ] **Step 6: Commit**

```bash
git add flask_templates/users.html
git commit -m "feat: sticky search and user count on users page"
```

---

## Task 8: Instruments page — type-grouped with filter panel

**Files:**
- Modify: `flask_templates/instrument_list.html`

- [ ] **Step 1: Rewrite instrument_list.html**

Replace the entire file content with:

```html
{% extends "base.html" %}
{% block title %}Instruments{% endblock %}

{% block sidebar %}{% endblock %}
{% block main_col_class %}col-12{% endblock %}

{% block breadcrumb %}
    <li class="breadcrumb-item active" aria-current="page">Instruments</li>
{% endblock %}

{% block content %}
<style>
    .inst-layout { display: flex; gap: 1rem; align-items: flex-start; }
    .inst-filter-panel {
        width: 180px; flex-shrink: 0;
        position: sticky; top: 3.5rem; max-height: calc(100vh - 4.5rem); overflow-y: auto;
        border: 1px solid var(--bs-border-color); border-radius: 0.375rem;
        background: var(--bs-tertiary-bg); padding: 0.75rem;
        font-size: 0.82rem;
    }
    .inst-filter-panel h6 { font-size: 0.68rem; font-weight: 700; text-transform: uppercase;
        letter-spacing: 0.07em; color: var(--bs-secondary-color); margin-bottom: 0.4rem; }
    .inst-filter-panel label { display: flex; align-items: center; gap: 0.4rem;
        cursor: pointer; padding: 0.2rem 0; border-radius: 3px; }
    .inst-filter-panel label:hover { background: var(--bs-border-color); }
    .inst-type-count { margin-left: auto; font-size: 0.72rem; color: var(--bs-secondary-color); }
    .inst-main { flex: 1; min-width: 0; }
    .inst-group-header {
        display: flex; align-items: center; gap: 0.5rem;
        padding: 0.5rem 0.75rem; font-size: 0.82rem; font-weight: 600;
        background: var(--bs-tertiary-bg); border: 1px solid var(--bs-border-color);
        border-left-width: 4px; border-radius: 0.375rem 0.375rem 0 0;
        position: sticky; top: 3.5rem; z-index: 5;
    }
    .inst-group-body { border: 1px solid var(--bs-border-color); border-top: none;
        border-radius: 0 0 0.375rem 0.375rem; overflow: hidden; margin-bottom: 0.75rem; }
    /* Mobile: hide filter panel, show chips */
    @media (max-width: 767px) {
        .inst-filter-panel { display: none; }
        .inst-layout { flex-direction: column; }
    }
</style>

<div class="d-flex align-items-center justify-content-between mb-3 flex-wrap gap-2">
    <h1 class="fs-4 fw-semibold mb-0">
        <i class="bi bi-cpu me-2 text-secondary"></i>Instruments
        <span id="instCount" class="text-muted fw-normal ms-1" style="font-size:0.85rem;">{{ instruments | length }}</span>
    </h1>
</div>

<!-- Mobile search -->
<input type="search" class="form-control form-control-sm mb-3 d-md-none" id="filterInputMobile"
       placeholder="Filter…" oninput="applyFilter()">

{% if instruments %}
<div class="inst-layout">

  <!-- Filter panel -->
  <div class="inst-filter-panel d-none d-md-block">
      <input type="search" class="form-control form-control-sm mb-3" id="filterInput"
             placeholder="Search…" oninput="applyFilter()">
      <h6>Type</h6>
      <div id="typeFilters"></div>
  </div>

  <!-- Instrument list grouped by type -->
  <div class="inst-main" id="instMain"></div>

</div>
{% else %}
<p class="text-muted">No instruments found.</p>
{% endif %}

<script>
const INSTRUMENTS = {{ instruments | tojson }};
let activeTypes = new Set();   // empty = all

function getQuery() {
    const d = document.getElementById('filterInput');
    const m = document.getElementById('filterInputMobile');
    return ((d && d.value) || (m && m.value) || '').toLowerCase();
}

// Build type list
(function buildTypeFilters() {
    const counts = {};
    INSTRUMENTS.forEach(i => {
        const t = i.instrument_type || '—';
        counts[t] = (counts[t] || 0) + 1;
    });
    const types = Object.entries(counts).sort((a,b) => b[1]-a[1]);
    const el = document.getElementById('typeFilters');
    if (!el) return;
    types.forEach(([type, count]) => {
        const lbl = document.createElement('label');
        lbl.innerHTML = `<input type="checkbox" value="${esc(type)}" onchange="toggleType(this)">
            <span class="text-truncate" style="flex:1;" title="${esc(type)}">${esc(type)}</span>
            <span class="inst-type-count">${count}</span>`;
        el.appendChild(lbl);
    });
})();

function toggleType(cb) {
    if (cb.checked) activeTypes.add(cb.value);
    else activeTypes.delete(cb.value);
    applyFilter();
}

function esc(s) {
    return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function applyFilter() {
    const q = getQuery();
    const main = document.getElementById('instMain');
    if (!main) return;

    // Group by type
    const groups = {};
    let visibleTotal = 0;

    INSTRUMENTS.forEach(inst => {
        const type = inst.instrument_type || '—';
        if (activeTypes.size && !activeTypes.has(type)) return;
        const searchText = [inst.instrument_name, inst.instrument_type, inst.location, inst.manufacturer, inst.model].join(' ').toLowerCase();
        if (q && !searchText.includes(q)) return;
        if (!groups[type]) groups[type] = [];
        groups[type].push(inst);
        visibleTotal++;
    });

    // Sort types
    const sortedTypes = Object.keys(groups).sort();

    main.innerHTML = sortedTypes.map(type => {
        const items = groups[type];
        const color = hashColor(type);
        const rows = items.map(inst => {
            const url = `/instrument/${esc(inst.unique_id || '')}`;
            const name = esc(inst.instrument_name || inst.unique_id || '');
            const mfr  = [inst.manufacturer, inst.model].filter(Boolean).map(esc).join(' · ');
            const loc  = inst.location ? `<i class="bi bi-geo-alt" style="font-size:0.72rem;"></i> ${esc(inst.location)}` : '';
            return `<a class="list-row" href="${url}"
                        data-search="${esc([inst.instrument_name,inst.instrument_type,inst.location,inst.manufacturer,inst.model].join(' ').toLowerCase())}">
                <i class="bi bi-cpu text-secondary flex-shrink-0" style="font-size:1.05rem;"></i>
                <div style="min-width:0; flex:1;">
                    <div class="fw-medium">${name}</div>
                    <div class="d-flex flex-wrap gap-3 mt-1">
                        ${mfr ? `<span class="text-muted small">${mfr}</span>` : ''}
                        ${loc  ? `<span class="text-muted small">${loc}</span>` : ''}
                    </div>
                </div>
                <span class="mfid small text-nowrap flex-shrink-0">${esc(inst.unique_id || '')}</span>
            </a>`;
        }).join('');
        return `<div class="inst-group-body-wrap">
            <div class="inst-group-header" style="border-left-color:${color};">
                <i class="bi bi-cpu-fill" style="color:${color}; font-size:0.85rem;"></i>
                <span>${esc(type)}</span>
                <span class="badge fw-normal border text-muted ms-auto" style="background:var(--bs-body-bg); font-size:0.72rem;">${items.length}</span>
            </div>
            <div class="inst-group-body">${rows}</div>
        </div>`;
    }).join('');

    // Update count
    const countEl = document.getElementById('instCount');
    if (countEl) {
        countEl.textContent = (q || activeTypes.size) ? `${visibleTotal} of ${INSTRUMENTS.length}` : INSTRUMENTS.length;
    }

    // Show empty state
    if (!sortedTypes.length) {
        main.innerHTML = '<div class="text-center text-muted py-5"><i class="bi bi-cpu fs-2 d-block mb-2 opacity-50"></i>No instruments match your filter.</div>';
    }
}

applyFilter();
</script>

{% endblock %}
```

- [ ] **Step 2: Verify**

Open `/instruments/`. Instruments are grouped by type with colored left borders. Left panel has type checkboxes. Checking a type filters the list. Search input filters within type selection.

- [ ] **Step 3: Commit**

```bash
git add flask_templates/instrument_list.html
git commit -m "feat: instruments page grouped by type with filter panel"
```

---

## Self-Review Checklist

- [x] **Spec §1 Navigation**: Tasks 2, 4 (state preservation, back-link, sibling jump in Task 3)
- [x] **Spec §2 Compact header**: Task 3
- [x] **Spec §3 Collapsible sidebar**: Task 4
- [x] **Spec §4 List pages**: Tasks 7, 8
- [x] **Spec §5 Project overview**: Task 5
- [x] **Spec §6 Lightbox**: Task 6
- [x] **No TBDs or placeholders**: All steps contain real code
- [x] **Type consistency**: `cgLbOpen`/`cgLbNav`/`cgLbClose`/`cgLbOpenSection` used consistently in Tasks 6a-6c; `data-lb-src`/`data-lb-label` attributes consistent
- [x] **`_PID` vs `PID`**: Task 4 uses `_PID` (to avoid collision with overview's `PID`); Task 2 uses `PID` (already defined in overview)
