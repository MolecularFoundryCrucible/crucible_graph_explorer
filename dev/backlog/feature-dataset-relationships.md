# Feature: Dataset Relationship Management

## Description
Allow users to create and remove parent-child relationships between datasets directly from the UI. Currently these links can only be set via the API.

## Motivation
When processing data, researchers often derive child datasets from parents (e.g. a processed spectrum from a raw scan). Being able to link them from the dataset page without API access makes this workflow significantly faster.

## UI Sketch
- On the dataset detail page, in the "Parent Datasets" and "Child Datasets" sections, add:
  - An "Add parent" / "Add child" button that opens a typeahead search for datasets within the same project.
  - A remove (×) button on each existing relationship row.
- Confirmation toast on success; error toast on failure.
- The graph view updates on next load to reflect the new relationship.

## API Endpoints Needed
- `POST /datasets/{id}/links` or similar — check nano-crucible SDK for relationship creation.
- `DELETE /datasets/{id}/links/{target_id}` — for removal.

## Open Questions
- Does the API support bidirectional link creation (setting parent or child from either side)?
- Are there constraints on which datasets can be linked (must be in same project)?
