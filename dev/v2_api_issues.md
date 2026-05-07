# Crucible Graph Explorer — v2 API Compatibility Issues

Audited against crucible-api `v2-dev` branch (2026-05-06).
The app uses `https://crucible.lbl.gov/api/v2` via `nano-crucible` `CrucibleClient`.

---

## Issues

### 1. `DELETE /datasets/{dsid}` returns 501

**Where:** `nano-crucible/crucible/resources/datasets.py` → `datasets.delete()`

v2 hard deletion is intentionally unimplemented. The endpoint now returns `501 Not Implemented`.
Any call to `client.datasets.delete(dsid)` will fail.

**Fix:** Use the deletion request system instead:
```python
client.deletion.create(dsid)
```
The `nano-crucible` `DeletionResource` already wraps `/deletion_requests`.

---

### 2. `POST /datasets/first_thumbnails` — endpoint status unknown

**Where:** `crucible_graph_explorer/routes/graphs.py:68`, `routes/samples.py:218`, `views/projects/proj10k_perovskites.py:91`

This endpoint is called directly via `client._request("POST", "/datasets/first_thumbnails", json=dataset_ids)`.
It is not in any of the reviewed v2 route files — verify it still exists or refactor to
fetch thumbnails per-dataset via `GET /datasets/{dsid}/thumbnails`.

---

### 3. `GET /datasets/{dsid}/thumbnails` — response now includes `id` field

**Where:** Any code reading thumbnail responses.

v2 thumbnail responses now include an `id` field (integer) so thumbnails can be deleted via
`DELETE /datasets/{dsid}/thumbnails/{thumbnail_id}`. If any code destructures the response
expecting a fixed set of fields it should still work, but consuming code should be aware
the new `id` field is available.

---

### 4. `GET /samples` — `include_datasets` is deprecated

**Where:** `nano-crucible/crucible/resources/samples.py` list method.

The `include_datasets` query param is deprecated in v2. Pass `include_links=True` instead.
The API still honours `include_datasets` for compatibility (emits a server-side deprecation warning
and populates both `datasets` and `links`), but it will eventually be removed.

The nano-crucible client already uses `include_links` natively (`samples.list(include_links=True)`),
so no code change is needed as long as callers use that interface.

---

### 5. `entity_graph_cte` / `project_graph` — verify these exist in v2

**Where:** `nano-crucible/crucible/resources/graphs.py`

These graph endpoints (`GET /entity_graph_cte/{entity_id}`, `GET /project_graph/{project_id}`)
are used in the explorer but are not in the reviewed route files for the v2 API.
Confirm they are still present under v2 before deploying.

---

### 6. `scientific_metadata` double-nesting guard in `project_graph.py`

**Where:** `crucible_graph_explorer/utils/project_graph.py:20-24`

There is a guard for the v1 double-nested response (`{"scientific_metadata": {"scientific_metadata": ...}}`).
v2 returns a flat dict. The guard is harmless but can be removed once v1 support is dropped.

---

## What is already correct

- Scientific metadata routes: all calls go through `/resources/{id}/metadata` and
  `/resources/metadata/search` (v2 paths). No old `/datasets/{id}/scientific_metadata` calls remain.
- Auth: `Authorization: Bearer` header is correct.
- Pagination: list calls use `limit`/`offset` and read `total`, `items` from paginated responses.
- `include_links=True` is used on dataset and sample get/list calls (nano-crucible client updated).
- `GET /resources/{id}`, `GET /resources/{id}/links`, `GET /resources/{id}/metadata` — all correct v2 paths.
