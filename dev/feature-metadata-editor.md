# Feature: Inline Scientific Metadata Editor

## Description
The scientific metadata tree on sample and dataset pages is currently read-only. This feature would allow users to edit metadata fields inline without leaving the page.

## Motivation
Researchers often need to correct or enrich metadata after initial upload. Currently this requires using the API directly or a separate tool.

## UI Sketch
- The existing collapsible `scientific_metadata` tree gets an "Edit" button in its section header.
- Clicking enters edit mode: leaf values become inline `<input>` or `<textarea>` fields. Keys remain read-only.
- A small toolbar appears: Save / Cancel / Add field / Remove field.
- On Save, a PATCH/PUT request is sent to the API; success shows a toast.
- Nested structures (dicts, lists) are editable by expanding and editing individual leaves.

## API Endpoints Needed
- `PATCH /samples/{id}` or `PATCH /datasets/{id}` with `{ scientific_metadata: { ... } }` — check nano-crucible SDK for exact method.

## Open Questions
- Does the API support partial metadata updates, or does it require sending the full metadata object?
- How should list-type values (arrays) be edited? Inline JSON string, or add/remove item UI?
- Should there be a JSON raw-edit mode as a fallback for power users?
