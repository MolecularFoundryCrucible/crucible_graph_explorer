# Bug: Note Creation Hides Partial Relationship Failures

## Status

Deferred. Do not change the note workflow as part of the current sample and dataset creation work.

## Current Behavior

Notes are created as datasets with `measurement="MDNote"`. The note panel submits the title and requested relationships to the dataset creation endpoint, then redirects to the Markdown editor after any successful HTTP response.

The dataset creation endpoint can return `partial: true` when the note dataset was created but one or more requested relationships failed. The note submission code does not inspect that field, so it discards the warnings and retry payload before opening the editor.

## User Impact

The note exists and can be edited, but requested sample or dataset relationships may be missing without any visible warning. Retrying normal note creation would risk creating a duplicate note dataset.

## Recommended Behavior

- Store the created note ID, canonical URL, and failed relationships when the response is partial.
- Keep the note panel open and state clearly that the note was created but some relationships failed.
- Change the primary action to `Retry Relationships` and call the existing dataset creation resume path with `resume_id` and only the failed links.
- Provide a separate `Edit Note Now` link so relationship failure does not block content editing.
- Navigate automatically to the Markdown editor after relationship retry succeeds.
- Never create a second note during retry.

## Existing Support

No backend change is currently required. The dataset creation endpoint already returns structured partial-success warnings and supports retrying failed relationships through `resume_id`.

## Tests Needed

- Partial note creation remains on the panel and displays the created note.
- Retry submits the existing note ID and only failed relationships.
- Successful retry opens the Markdown editor.
- `Edit Note Now` opens the existing note without retrying relationships.
- Repeated retry attempts never call core dataset creation again.
