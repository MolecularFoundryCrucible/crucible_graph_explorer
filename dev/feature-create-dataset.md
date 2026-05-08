# Feature: Web Form to Create Datasets

## Description
A web form allowing users to create new datasets within a project, without needing direct API access. Currently datasets can only be created via the nano-crucible API or CLI.

## Motivation
Non-technical collaborators who have web access but not API credentials cannot add datasets. A guided form lowers the barrier significantly.

## UI Sketch
- Accessible from the project overview page via a "+ New Dataset" button in the Datasets tab toolbar.
- Multi-step form:
  1. **Basic info**: dataset name, measurement type (typeahead from existing values in project), description
  2. **Relationships**: link to parent sample(s) (typeahead), link to parent dataset(s)
  3. **Metadata**: optional scientific metadata entry as key-value pairs (simple flat form, not a full JSON editor)
  4. **Review + Create**: summary before submitting
- On success: navigate to the new dataset page and show a toast.

## API Endpoints Needed
- `POST /datasets` — check nano-crucible SDK for `datasets.create()`.
- `POST /datasets/{id}/links` — to attach sample and parent dataset relationships.

## Open Questions
- File upload: should the form support attaching files at creation time, or is that a separate step?
- Which fields are required vs. optional in the API?
- Should instrument be selectable from the form?
