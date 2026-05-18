# Associated Files Rework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the eager bulk download-link fetch at page load with a per-file on-demand model, surface ingestion status in the UI, and merge the redundant "Files" + "Download Links" sections into one unified section.

**Architecture:** The server stops pre-signing all URLs at page load. A new Flask endpoint `GET /<project_id>/datasets/<dsid>/files/<file_id>/download_link` proxies the single-file signing API and is called by JavaScript only when the user clicks a download button. The `dataset.html` Files section shows each file's ingestion status (`storage_path` present = downloadable, `null` = pending) and renders a per-row button that fetches the signed URL on demand and opens it.

**Tech Stack:** Flask (Python), Jinja2, Bootstrap 5 + Bootstrap Icons, vanilla JS `fetch()`, `crucible` SDK (`client.files.get_download_link(mfid)` / `client.datasets.get_associated_files(dsid)`)

---

## Why these changes

| Problem | Root cause | Fix |
|---|---|---|
| All signed URLs fetched at page load | `get_download_links()` called in parallel with page data | Remove bulk fetch; add per-file endpoint |
| MDNote markdown broken | Key was `"{dsid}/{basename}"` (old GCS path); new API keys by MFID | Use `client.files.get_download_link(file['mfid'])` |
| `mdnote_edit` same bug | Same path-key pattern | Same fix |
| No ingestion status shown | UI has no awareness of `storage_path` | Check `storage_path` per file; show Pending badge |
| Two redundant sections | "Files" + "Download Links" are the same data | Merge into one unified "Files" section |

---

## File Map

| File | Change |
|---|---|
| `routes/datasets.py` | Remove `_get_links`/`f_links`/`download_links`; fix MDNote rendering; fix `mdnote_edit`; add `file_download_link` endpoint |
| `flask_templates/dataset.html` | Merge Files + Download Links sections; per-file download buttons with JS |

---

### Task 1: Remove bulk download-link fetch and fix MDNote rendering

**Files:**
- Modify: `routes/datasets.py`

- [ ] **Step 1: Remove `_get_links`, `f_links`, and `download_links` from `dataset()`**

Replace the `_get_links` helper, its use in the `ThreadPoolExecutor`, and its result:

```python
# REMOVE these lines entirely:

def _get_links():
    try:
        return client.datasets.get_download_links(dsid)
    except Exception as err:
        logger.warning("Failed to get download links for %s: %s", dsid, err)
        return {}

# In the ThreadPoolExecutor block, REMOVE:
f_links    = ex.submit(_get_links)

# In the results block, REMOVE:
download_links   = _safe(f_links,    'download_links',   {})
```

Also remove the `import requests` line if it becomes unused (check below before removing).

- [ ] **Step 2: Fix MDNote markdown rendering to use per-file `get_download_link`**

Replace the existing MDNote block (lines ~73–85) with:

```python
markdown_html = None
if ds.get('measurement') == 'MDNote':
    md_file = next((f for f in associated_files if f['filename'].endswith('.md')), None)
    if md_file and md_file.get('storage_path'):
        try:
            url = client.files.get_download_link(md_file['mfid'])
            response = requests.get(url)
            if response.status_code == 200:
                markdown_html = render_markdown(response.text, project_id)
        except Exception as err:
            logger.warning("Failed to render markdown for %s: %s", dsid, err)
```

Key changes: guard on `storage_path` (skip if not yet ingested), use `client.files.get_download_link(mfid)` (returns URL string directly).

- [ ] **Step 3: Remove `download_links` from `render_template` call**

In the `render_template(...)` call, remove:

```python
download_links=download_links,
```

- [ ] **Step 4: Verify `import requests` is still needed**

`requests` is still used in the MDNote rendering block (`requests.get(url)`), so the import stays.

- [ ] **Step 5: Run the app and open a dataset page to confirm it still loads**

```bash
flask run --debug 2>&1 | head -30
```

Expected: no `AttributeError`, page renders, MDNote content appears if applicable.

- [ ] **Step 6: Commit**

```bash
git add routes/datasets.py
git commit -m "feat: remove eager bulk download-link fetch; fix MDNote to use per-file signing"
```

---

### Task 2: Fix `mdnote_edit` route

**Files:**
- Modify: `routes/datasets.py` (the `mdnote_edit` function)

- [ ] **Step 1: Replace GET path's `get_download_links` call with per-file `get_download_link`**

Find the GET branch of `mdnote_edit` (around line 147) and replace:

```python
# OLD — fetches all links + uses GCS path key:
associated_files = client.datasets.get_associated_files(dsid)
try:
    download_links = client.datasets.get_download_links(dsid)
except Exception as err:
    logger.warning("Failed to get download links for %s: %s", dsid, err)
    download_links = {}
md_content = ''
for file in associated_files:
    if file['filename'].endswith('.md'):
        md_basename  = os.path.basename(file['filename'])
        download_key = f"{ds['unique_id']}/{md_basename}"
        if download_key in download_links:
            response = requests.get(download_links[download_key])
            if response.status_code == 200:
                md_content = response.text
        break
```

With:

```python
# NEW — single file, keyed by mfid:
associated_files = client.datasets.get_associated_files(dsid)
md_content = ''
for file in associated_files:
    if file['filename'].endswith('.md'):
        if file.get('storage_path'):
            try:
                url = client.files.get_download_link(file['mfid'])
                response = requests.get(url)
                if response.status_code == 200:
                    md_content = response.text
            except Exception as err:
                logger.warning("Failed to fetch md content for %s: %s", dsid, err)
        break
```

- [ ] **Step 2: Commit**

```bash
git add routes/datasets.py
git commit -m "fix: mdnote_edit GET uses per-file download link keyed by mfid"
```

---

### Task 3: Add per-file download link API endpoint

**Files:**
- Modify: `routes/datasets.py`

- [ ] **Step 1: Add the new route after `mdnote_edit`**

Add before `return bp`:

```python
@bp.route("/<project_id>/datasets/<dsid>/files/<file_id>/download_link")
@auth.oidc_auth('orcid')
def file_download_link(project_id, dsid, file_id):
    client = flask.current_app.crucible_client
    if not is_user_in_project(project_id):
        abort(403)
    try:
        url = client.files.get_download_link(file_id)
        return jsonify({'url': url})
    except Exception as err:
        status = getattr(getattr(err, 'response', None), 'status_code', None)
        if status == 404:
            abort(404)
        logger.warning("download_link error for file %s: %s", file_id, err)
        abort(502)
```

- [ ] **Step 2: Confirm the route is reachable**

```bash
# With the dev server running, manually hit (with auth cookie) or trace with:
flask routes | grep download_link
```

Expected output includes: `datasets.file_download_link  GET  /<project_id>/datasets/<dsid>/files/<file_id>/download_link`

- [ ] **Step 3: Commit**

```bash
git add routes/datasets.py
git commit -m "feat: add per-file download_link endpoint for on-demand signing"
```

---

### Task 4: Rework `dataset.html` — unified Files section

**Files:**
- Modify: `flask_templates/dataset.html`

- [ ] **Step 1: Replace the "Files" section with a unified version**

Find and replace the entire `section-files` block (currently ~lines 326–353):

```html
<!-- ── files — collapsed by default ──────────────────────────────────── -->
{% if files %}
<div class="res-section" id="section-files">
    <div class="res-section-header" onclick="toggleSection(this)">
        <i class="bi bi-paperclip text-muted"></i>
        <span>Files</span>
        <span class="badge fw-normal border text-muted" style="background:var(--bs-tertiary-bg); font-size:0.75rem;">
            {{files|length}}
        </span>
        <i class="bi bi-chevron-right res-section-chevron"></i>
    </div>
    <div class="res-section-body" style="display:none;">
        {% for file in files %}
        {% set basename = file['filename'].split('/')|last %}
        <div class="list-row" style="padding:0; gap:0; flex-wrap:nowrap;">
            <div style="flex:1; min-width:0; overflow:hidden; display:flex; align-items:center; padding:0.5rem 1rem; gap:0.5rem;">
                {% if file.get('storage_path') %}
                <i class="bi bi-file-earmark text-muted flex-shrink-0" style="font-size:0.9rem;"></i>
                {% else %}
                <i class="bi bi-hourglass-split text-muted flex-shrink-0" style="font-size:0.9rem;"></i>
                {% endif %}
                <span class="text-truncate" title="{{basename}}">{{basename}}</span>
            </div>
            <span class="text-muted small text-nowrap px-2 border-start d-flex align-items-center" style="flex-shrink:0;">
                {{file['size'] | humanize_size}}
            </span>
            {% if file.get('storage_path') %}
            <button class="btn btn-sm btn-outline-secondary border-0 border-start rounded-0 px-3"
                    style="flex-shrink:0; height:100%; border-radius:0 !important;"
                    onclick="downloadFile(event, '{{file['mfid']}}', '{{basename}}')"
                    title="Download {{basename}}">
                <i class="bi bi-download"></i>
            </button>
            {% else %}
            <span class="badge fw-normal border text-muted d-flex align-items-center px-2 mx-2"
                  style="background:var(--bs-tertiary-bg); font-size:0.7rem; flex-shrink:0;">
                Pending
            </span>
            {% endif %}
        </div>
        {% endfor %}
    </div>
</div>
{% endif %}
```

- [ ] **Step 2: Remove the old "Download Links" section entirely**

Find and delete the entire `section-downloads` block (currently ~lines 355–375):

```html
<!-- ── download links — collapsed by default ─────────────────────────── -->
{% if download_links %}
<div class="res-section" id="section-downloads">
    ...
</div>
{% endif %}
```

Delete this block completely.

- [ ] **Step 3: Add the `downloadFile` JS function to the inline `<script>` block**

In the existing `<script>` block (non-module, near bottom of the template), add:

```javascript
async function downloadFile(event, mfid, filename) {
    const btn = event.currentTarget;
    const icon = btn.querySelector('i');
    btn.disabled = true;
    icon.className = 'bi bi-hourglass-split';
    try {
        const resp = await fetch(
            '/{{project_id}}/datasets/{{ds["unique_id"]}}/files/' + mfid + '/download_link'
        );
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        const { url } = await resp.json();
        window.open(url, '_blank', 'noopener');
    } catch (err) {
        alert('Could not get download link: ' + err.message);
    } finally {
        btn.disabled = false;
        icon.className = 'bi bi-download';
    }
}
```

- [ ] **Step 4: Remove `download_links` variable reference from `details-advanced` if present**

Search the template for any remaining `download_links` reference and remove it. (There shouldn't be any after Step 2, but verify.)

```bash
grep -n "download_links" flask_templates/dataset.html
```

Expected: no output.

- [ ] **Step 5: Open a dataset page with files in the browser and verify**

- Files section shows filenames (basename only), sizes
- Ingested files show download button; un-ingested show "Pending" badge
- Clicking download briefly shows hourglass, then opens signed URL in new tab

- [ ] **Step 6: Commit**

```bash
git add flask_templates/dataset.html
git commit -m "feat: merge Files+Downloads into unified section with per-file on-demand download"
```

---

## Self-Review

**Spec coverage:**

| Requirement | Task |
|---|---|
| Don't sign URLs at card load time | Task 1 (remove bulk fetch) |
| Use mfid as key, not filename or GCS path | Tasks 1 + 2 (get_download_link by mfid) |
| Check storage_path before showing download button | Task 4 (ingestion status per row) |
| Generate signed URL on demand (button click) | Tasks 3 + 4 |
| Merge file list + download into one UX | Task 4 |
| Fix mdnote_edit | Task 2 |

**Placeholder scan:** All steps contain exact code. No TBDs.

**Type consistency:** `client.files.get_download_link(mfid)` returns `str` in Tasks 1+2; same call in Task 3's endpoint returns `{'url': str}` JSON — consistent with what Task 4's JS expects.
