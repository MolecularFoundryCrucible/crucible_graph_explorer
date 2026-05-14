# Resource Page Sidebar Rethink Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reorganise the sidebar layout on sample and dataset detail pages so the left bar is project-only navigation and the right side shows relationship info (ancestors, descendants, linked resources) — appearing inline in the main body on narrow screens and as a sticky right panel at xl+ widths.

**Architecture:** Each resource page wraps its `{% block content %}` body in a `d-flex` row (same pattern already used in `project_overview.html`), putting all existing sections in a `flex:1` div and adding a `d-none d-xl-block` right panel next to it. The left `.cg-sidebar` is stripped to project-navigation-only (avatar, back link, current resource label). On narrow screens the right panel is hidden and the existing collapsible sections in the main body remain the source of relationship info — no data is lost.

**Tech Stack:** Jinja2 / Bootstrap 5 / vanilla JS — no new dependencies. No Flask route changes needed; all required variables (`direct_ancestors`, `direct_descendants`, `s['datasets']`, `samples`, `parent_datasets`, `child_datasets`) are already passed to the templates.

---

## Files Modified

| File | Change |
|------|--------|
| `flask_templates/sample_graph.html` | Slim left sidebar; wrap content in flex row; add xl+ right panel |
| `flask_templates/dataset.html` | Same pattern adapted for dataset relationships |

---

### Task 1: Restructure `sample_graph.html`

**Files:**
- Modify: `flask_templates/sample_graph.html`

#### Step 1 — Slim the left sidebar

- [ ] In `{% block sidebar %}`, inside `.cg-sidebar-content`, remove the three relationship nav blocks — ancestors, descendants, and datasets — leaving only the project header and "This sample" label.

Find and remove this block (ancestors):
```html
    {% if ancestors_info %}
    <div class="px-2 mb-1" style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--bs-secondary-color);">
      <i class="bi bi-arrow-up-short me-1"></i>Ancestors ({{ancestors_info|length}})
    </div>
    <ul class="nav flex-column mb-2">
      {% for anc in ancestors_info %}
      <li class="nav-item">
        <a class="nav-link py-1 px-2 text-body" style="font-size:0.8rem;" href="/{{pid}}/sample-graph/{{anc['unique_id']}}">{{anc['sample_name']}}</a>
      </li>
      {% endfor %}
    </ul>
    {% endif %}
```

Find and remove this block (descendants):
```html
    {% if descendants_info %}
    <div class="px-2 mb-1" style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--bs-secondary-color);">
      <i class="bi bi-arrow-down-short me-1"></i>Descendants ({{descendants_info|length}})
    </div>
    <ul class="nav flex-column mb-2">
      {% for desc in descendants_info %}
      <li class="nav-item">
        <a class="nav-link py-1 px-2 text-body" style="font-size:0.8rem;" href="/{{pid}}/sample-graph/{{desc['unique_id']}}">{{desc['sample_name']}}</a>
      </li>
      {% endfor %}
    </ul>
    {% endif %}
```

Find and remove this block (datasets):
```html
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
```

After removal the `.cg-sidebar-content` div should contain only:
```html
  <div class="cg-sidebar-content" id="sidebarContent">
    <div class="mb-2 px-2">
      <div class="d-flex align-items-center gap-2 mb-1" onclick="goBackToProject()"
           style="cursor:pointer;" title="Back to project">
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
  </div>
```

#### Step 2 — Wrap content in flex row and add right panel

- [ ] In `{% block content %}`, immediately after `{{ deletion_banner(s) }}`, open a flex wrapper div:

```html
<div class="d-flex gap-3 align-items-start">
<div style="flex: 1; min-width: 0;">
```

- [ ] At the very end of `{% block content %}`, before `{% endblock %}`, close the inner div and add the right panel, then close the outer flex wrapper:

```html
</div>{# end flex-1 content column #}

<!-- ── right panel: relationships (xl+ only) ─────────────────────────── -->
<div class="d-none d-xl-block flex-shrink-0" style="width: 200px;">
  <div style="position: sticky; top: 3.25rem; max-height: calc(100vh - 3.5rem); overflow-y: auto;">
    <div class="rounded border overflow-hidden">

      {% if not direct_ancestors and not direct_descendants and not s['datasets'] %}
      <div class="text-center text-muted py-4 px-2" style="font-size:0.8rem;">
        <i class="bi bi-diagram-3 d-block mb-2 opacity-40"></i>No relationships
      </div>
      {% endif %}

      {% if direct_ancestors %}
      <div class="d-flex align-items-center justify-content-between px-3 py-2 border-bottom"
           style="background:var(--bs-tertiary-bg);">
        <span style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.07em; color:var(--bs-secondary-color);">
          <i class="bi bi-arrow-up-short"></i> Parents
        </span>
        <span class="badge fw-normal border text-muted"
              style="background:var(--bs-body-bg); font-size:0.7rem;">{{direct_ancestors|length}}</span>
      </div>
      {% for anc in direct_ancestors %}
      <a class="d-flex align-items-center gap-2 px-3 py-2 border-bottom text-decoration-none text-body"
         style="font-size:0.8rem;{% if loop.last %} border-bottom: none;{% endif %}"
         href="/{{pid}}/sample-graph/{{anc['unique_id']}}">
        <span class="text-truncate">{{anc['sample_name']}}</span>
      </a>
      {% endfor %}
      {% endif %}

      {% if direct_ancestors and (direct_descendants or s['datasets']) %}
      <div class="border-bottom"></div>
      {% endif %}

      {% if direct_descendants %}
      <div class="d-flex align-items-center justify-content-between px-3 py-2 border-bottom"
           style="background:var(--bs-tertiary-bg);">
        <span style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.07em; color:var(--bs-secondary-color);">
          <i class="bi bi-arrow-down-short"></i> Children
        </span>
        <span class="badge fw-normal border text-muted"
              style="background:var(--bs-body-bg); font-size:0.7rem;">{{direct_descendants|length}}</span>
      </div>
      {% for desc in direct_descendants %}
      <a class="d-flex align-items-center gap-2 px-3 py-2 border-bottom text-decoration-none text-body"
         style="font-size:0.8rem;{% if loop.last %} border-bottom: none;{% endif %}"
         href="/{{pid}}/sample-graph/{{desc['unique_id']}}">
        <span class="text-truncate">{{desc['sample_name']}}</span>
      </a>
      {% endfor %}
      {% endif %}

      {% if direct_descendants and s['datasets'] %}
      <div class="border-bottom"></div>
      {% endif %}

      {% if s['datasets'] %}
      <div class="d-flex align-items-center justify-content-between px-3 py-2 border-bottom"
           style="background:var(--bs-tertiary-bg);">
        <span style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.07em; color:var(--bs-secondary-color);">
          <i class="bi bi-database"></i> Datasets
        </span>
        <span class="badge fw-normal border text-muted"
              style="background:var(--bs-body-bg); font-size:0.7rem;">{{s['datasets']|length}}</span>
      </div>
      {% for ds in s['datasets'] %}
      <a class="d-flex align-items-center gap-2 px-3 py-2 border-bottom text-decoration-none text-body"
         style="font-size:0.8rem;{% if loop.last %} border-bottom: none;{% endif %}"
         href="/{{pid}}/dataset/{{ds['unique_id']}}">
        <span class="text-truncate">{{ds['dataset_name']}}</span>
      </a>
      {% endfor %}
      {% endif %}

    </div>
  </div>
</div>

</div>{# end outer flex row #}
```

#### Step 3 — Verify

- [ ] Load a sample page at a wide viewport (≥1200px / xl): confirm right panel appears with direct parents, children, and linked datasets as compact nav links, each section has a count badge, and items are clickable.
- [ ] Resize to <1200px: confirm right panel disappears and the existing collapsible ancestor/descendant/dataset sections in the main body still work.
- [ ] Confirm left sidebar now shows only: project avatar + back link + "This sample" label.
- [ ] Confirm collapsed sidebar still works (icon rail, toggle button).

#### Step 4 — Commit

- [ ] Commit:
```bash
git add flask_templates/sample_graph.html
git commit -m "UX: slim sample sidebar to project-nav; add xl+ right relationship panel"
```

---

### Task 2: Restructure `dataset.html`

**Files:**
- Modify: `flask_templates/dataset.html`

#### Step 1 — Slim the left sidebar

- [ ] In `{% block sidebar %}`, inside `.cg-sidebar-content`, remove the three relationship nav blocks — samples, parent datasets, and child datasets — leaving only the project header and "This dataset" label.

Find and remove this block (samples):
```html
    {% if samples %}
    <div class="px-2 mb-1" style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--bs-secondary-color);">
      <i class="bi bi-eyedropper me-1"></i>Samples ({{samples|length}})
    </div>
    <ul class="nav flex-column mb-2" style="overflow-y:auto; max-height:30vh;">
      {% for sample in samples %}
      <li class="nav-item">
        <a class="nav-link py-1 px-2 text-body" style="font-size:0.8rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;" href="/{{project_id}}/sample-graph/{{sample['unique_id']}}">{{sample['sample_name']}}</a>
      </li>
      {% endfor %}
    </ul>
    {% endif %}
```

Find and remove this block (parent datasets):
```html
    {% if parent_datasets %}
    <div class="px-2 mb-1" style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--bs-secondary-color);">
      <i class="bi bi-arrow-up-short me-1"></i>Parent datasets ({{parent_datasets|length}})
    </div>
    <ul class="nav flex-column mb-2">
      {% for pd in parent_datasets %}
      <li class="nav-item">
        <a class="nav-link py-1 px-2 text-body" style="font-size:0.8rem;" href="/{{project_id}}/dataset/{{pd['unique_id']}}">{{pd['dataset_name']}}</a>
      </li>
      {% endfor %}
    </ul>
    {% endif %}
```

Find and remove this block (child datasets):
```html
    {% if child_datasets %}
    <div class="px-2 mb-1" style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--bs-secondary-color);">
      <i class="bi bi-arrow-down-short me-1"></i>Child datasets ({{child_datasets|length}})
    </div>
    <ul class="nav flex-column mb-2">
      {% for cd in child_datasets %}
      <li class="nav-item">
        <a class="nav-link py-1 px-2 text-body" style="font-size:0.8rem;" href="/{{project_id}}/dataset/{{cd['unique_id']}}">{{cd['dataset_name']}}</a>
      </li>
      {% endfor %}
    </ul>
    {% endif %}
```

After removal `.cg-sidebar-content` should contain only:
```html
  <div class="cg-sidebar-content" id="sidebarContent">
    <div class="mb-2 px-2">
      <div class="d-flex align-items-center gap-2 mb-1" onclick="goBackToProject()"
           style="cursor:pointer;" title="Back to project">
        <div id="projectAvatar" style="flex-shrink:0;"></div>
        <span class="fw-semibold small text-body text-truncate">{{project_id}}</span>
      </div>
      <a href="javascript:void(0)" onclick="goBackToProject()" class="nav-link py-1 px-1 text-muted small">
        <i class="bi bi-arrow-left me-1"></i>Back to project
      </a>
    </div>
    <hr class="my-1 mx-2">
    <div class="px-2 mb-1" style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:var(--cg-link);">
      <i class="bi bi-database me-1"></i>This dataset
    </div>
    <div class="px-2 mb-2 small fw-semibold text-body" style="font-size:0.8rem; word-break:break-word;">{{ds['dataset_name']}}</div>
    <hr class="my-1 mx-2">
  </div>
```

#### Step 2 — Wrap content in flex row and add right panel

- [ ] In `{% block content %}`, immediately after `{{ deletion_banner(ds) }}`, open a flex wrapper div:

```html
<div class="d-flex gap-3 align-items-start">
<div style="flex: 1; min-width: 0;">
```

- [ ] At the very end of `{% block content %}`, before `{% endblock %}`, close the inner div and add the right panel:

```html
</div>{# end flex-1 content column #}

<!-- ── right panel: relationships (xl+ only) ─────────────────────────── -->
<div class="d-none d-xl-block flex-shrink-0" style="width: 200px;">
  <div style="position: sticky; top: 3.25rem; max-height: calc(100vh - 3.5rem); overflow-y: auto;">
    <div class="rounded border overflow-hidden">

      {% if not samples and not parent_datasets and not child_datasets %}
      <div class="text-center text-muted py-4 px-2" style="font-size:0.8rem;">
        <i class="bi bi-diagram-3 d-block mb-2 opacity-40"></i>No relationships
      </div>
      {% endif %}

      {% if samples %}
      <div class="d-flex align-items-center justify-content-between px-3 py-2 border-bottom"
           style="background:var(--bs-tertiary-bg);">
        <span style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.07em; color:var(--bs-secondary-color);">
          <i class="bi bi-eyedropper"></i> Samples
        </span>
        <span class="badge fw-normal border text-muted"
              style="background:var(--bs-body-bg); font-size:0.7rem;">{{samples|length}}</span>
      </div>
      {% for sample in samples %}
      <a class="d-flex align-items-center gap-2 px-3 py-2 border-bottom text-decoration-none text-body"
         style="font-size:0.8rem;{% if loop.last %} border-bottom: none;{% endif %}"
         href="/{{project_id}}/sample-graph/{{sample['unique_id']}}">
        <span class="text-truncate">{{sample['sample_name']}}</span>
      </a>
      {% endfor %}
      {% endif %}

      {% if samples and (parent_datasets or child_datasets) %}
      <div class="border-bottom"></div>
      {% endif %}

      {% if parent_datasets %}
      <div class="d-flex align-items-center justify-content-between px-3 py-2 border-bottom"
           style="background:var(--bs-tertiary-bg);">
        <span style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.07em; color:var(--bs-secondary-color);">
          <i class="bi bi-arrow-up-short"></i> Parents
        </span>
        <span class="badge fw-normal border text-muted"
              style="background:var(--bs-body-bg); font-size:0.7rem;">{{parent_datasets|length}}</span>
      </div>
      {% for pd in parent_datasets %}
      <a class="d-flex align-items-center gap-2 px-3 py-2 border-bottom text-decoration-none text-body"
         style="font-size:0.8rem;{% if loop.last %} border-bottom: none;{% endif %}"
         href="/{{project_id}}/dataset/{{pd['unique_id']}}">
        <span class="text-truncate">{{pd['dataset_name']}}</span>
      </a>
      {% endfor %}
      {% endif %}

      {% if parent_datasets and child_datasets %}
      <div class="border-bottom"></div>
      {% endif %}

      {% if child_datasets %}
      <div class="d-flex align-items-center justify-content-between px-3 py-2 border-bottom"
           style="background:var(--bs-tertiary-bg);">
        <span style="font-size:0.65rem; font-weight:700; text-transform:uppercase; letter-spacing:0.07em; color:var(--bs-secondary-color);">
          <i class="bi bi-arrow-down-short"></i> Children
        </span>
        <span class="badge fw-normal border text-muted"
              style="background:var(--bs-body-bg); font-size:0.7rem;">{{child_datasets|length}}</span>
      </div>
      {% for cd in child_datasets %}
      <a class="d-flex align-items-center gap-2 px-3 py-2 border-bottom text-decoration-none text-body"
         style="font-size:0.8rem;{% if loop.last %} border-bottom: none;{% endif %}"
         href="/{{project_id}}/dataset/{{cd['unique_id']}}">
        <span class="text-truncate">{{cd['dataset_name']}}</span>
      </a>
      {% endfor %}
      {% endif %}

    </div>
  </div>
</div>

</div>{# end outer flex row #}
```

#### Step 3 — Verify

- [ ] Load a dataset page at xl+ width: confirm right panel shows linked samples, parent datasets, child datasets — each with a count badge and working links.
- [ ] Resize to <1200px: right panel hidden, existing collapsible sections (Linked Samples, Parent Datasets, Child Datasets) still work in the main body.
- [ ] Confirm left sidebar now shows only: project avatar + back link + "This dataset" label.
- [ ] Check a dataset with no relationships: right panel shows "No relationships" empty state.

#### Step 4 — Commit

- [ ] Commit:
```bash
git add flask_templates/dataset.html
git commit -m "UX: slim dataset sidebar to project-nav; add xl+ right relationship panel"
```

---

## Self-Review

**Spec coverage:**
- ✅ Left bar = project navigation only (avatar, back link, current resource name)
- ✅ Right bar = relationship info (ancestors/children/datasets for sample; samples/parents/children for dataset)
- ✅ Right bar hidden on narrow screens (`d-none d-xl-block`); main body sections remain as fallback
- ✅ No Flask route changes — all template variables already exist

**Placeholder scan:** None found. All HTML is complete and exact.

**Type consistency:** Variable names match what the Flask routes pass: `direct_ancestors`, `direct_descendants`, `s['datasets']` (sample); `samples`, `parent_datasets`, `child_datasets` (dataset). All confirmed in `routes/samples.py` and `routes/datasets.py`.
