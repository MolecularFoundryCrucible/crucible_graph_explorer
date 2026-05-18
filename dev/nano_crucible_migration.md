# nano-crucible Client Migration Notes

Audited against nano-crucible `dev` branch (2026-05-07).
All deprecated flat-API methods below still exist on `CrucibleClient` as shims,
so nothing crashes *unless noted*. Migrate to silence deprecation warnings and
access newer parameters.

---

## Crashes (fix immediately)

### `client.upload_dataset_file()` — broken shim

**Where:** `routes/datasets.py:120`

`client.upload_dataset_file(dsid, path)` delegates to `client.datasets.upload_file()`
which no longer exists. This will raise `AttributeError` at runtime.

**Fix:** Use `add_file_to_dataset()` which handles upload + ingestion in one call:
```python
# Old (broken)
client.upload_dataset_file(dsid, file_path)
client.request_ingestion(dsid, file_to_upload=filename, ingestion_class=ingestor)

# New
client.datasets.add_file_to_dataset(dsid, file_path, ingestion_class=ingestor,
                                     wait_for_ingestion_response=True)
```

---

## Deprecation warnings (migrate when convenient)

### `BaseDataset` model name

**Where:**
- `routes/samples.py:121` — `from crucible.models import BaseDataset`
- `views/instruments/hip_microscope.py:13` — same import
- `views/instruments/als_bl12012.py:16` — same import

`BaseDataset` still works via a `__getattr__` alias — it returns `Dataset` — but
emits a `DeprecationWarning`.

**Fix:** `from crucible.models import Dataset`

---

### Flat-API methods on `CrucibleClient`

The following calls still work but are deprecated shims. They also miss newer
parameters (`include_links`, etc.) available on the resource-level APIs.

| Old call | New equivalent |
|---|---|
| `client.get_dataset(dsid, include_metadata=True)` | `client.datasets.get(dsid, include_metadata=True, include_links=True)` |
| `client.list_datasets(project_id=pid)` | `client.datasets.list(project_id=pid)` |
| `client.list_samples(dataset_id=did)` | `client.samples.list(dataset_id=did)` |
| `client.get_sample(sid)` | `client.samples.get(sid, include_links=True)` |
| `client.add_sample_to_dataset(dsid, sid)` | `client.datasets.add_sample(dsid, sid)` |
| `client.list_projects(orcid=o)` | `client.projects.list(orcid=o)` |
| `client.get_project_users(pid)` | `client.projects.list_users(pid)` |
| `client.list_instruments()` | `client.instruments.list()` |
| `client.get_instrument(name)` | `client.instruments.get(instrument_name=name)` |
| `client.get_dataset_download_links(dsid)` | `client.datasets.get_download_links(dsid)` |
| `client.get_thumbnails(dsid)` | `client.datasets.get_thumbnails(dsid)` |
| `client.get_associated_files(dsid)` | `client.datasets.get_associated_files(dsid)` |
| `client.request_ingestion(dsid, ...)` | `client.datasets.request_ingestion(dsid, ...)` |
| `client.link_datasets(pid, cid)` | `client.datasets.link_parent_child(pid, cid)` |
| `client.list_children_of_dataset(dsid)` | `client.datasets.list_children(dsid)` |
| `client.list_parents_of_dataset(dsid)` | `client.datasets.list_parents(dsid)` |

**Affected files:** `routes/datasets.py`, `routes/projects.py`, `routes/users.py`,
`routes/search.py`, `routes/instruments.py`, `routes/chat.py`, `utils/cache.py`,
`utils/project_graph.py`, `views/instruments/hip_microscope.py`,
`views/instruments/als_bl12012.py`

---

## New features available (optional)

### `include_links` on get and list

Both `datasets.get()` and `samples.get()` now accept `include_links=True`,
embedding parent/child/associated links directly in the response — no second API
call needed. Same for `datasets.list()` and `samples.list()`.

```python
ds = client.datasets.get(dsid, include_links=True, include_metadata=True)
ds['links']  # [{"unique_id": ..., "resource_type": ..., "relationship": ...}]
```

### `client.search_scientific_metadata(q)`

Scientific metadata search is now cross-resource (datasets and samples).
Previously `client.datasets.search_scientific_metadata(q)` — that still works
but the canonical call is now:

```python
results = client.search_scientific_metadata("XRD silicon", limit=25)
# each result: {"unique_id": "<MFID>", "scientific_metadata": {...}}
```

### `get/add/update_scientific_metadata` on samples

These methods now live on `BaseResource` and work on both datasets and samples:

```python
client.samples.get_scientific_metadata(sid)
client.samples.add_scientific_metadata(sid, {"key": "value"})
client.samples.update_scientific_metadata(sid, {"key": "value"}, overwrite=False)
```
