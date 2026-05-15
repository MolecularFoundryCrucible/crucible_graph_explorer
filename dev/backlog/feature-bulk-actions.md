# Feature: Bulk Actions on Project Overview

## Description
Allow users to select multiple samples or datasets on the project overview page and perform batch operations: export metadata, assign tags/keywords, or archive.

## Motivation
Researchers working with large projects often need to perform the same operation on many resources. Individual clicks are tedious.

## UI Sketch
- A checkbox column appears when the user clicks a "Select" button in the toolbar.
- Each list row gets a leading checkbox. Clicking the row header checkbox selects all visible items.
- A floating action bar appears at the bottom of the screen when ≥1 item is selected, showing:
  - Count of selected items
  - Action buttons: Export CSV (metadata), Add keyword, Archive
- Export: generates a CSV client-side from the already-loaded SAMPLES/DATASETS JSON arrays. No API call needed for basic metadata.
- Add keyword: opens a small input popover; sends PATCH to each selected resource.
- Archive: confirmation dialog, then DELETE/archive API call per resource.

## API Endpoints Needed
- `PATCH /samples/{id}` and `PATCH /datasets/{id}` for keyword updates.
- Archive endpoint — check nano-crucible SDK.

## Open Questions
- Is there a batch API endpoint, or would this require N individual requests?
- Should export include scientific metadata (potentially large), or just core fields?
