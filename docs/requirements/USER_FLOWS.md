# User Scenarios

Status: first-version scenarios based on agreed decisions. Sources: S-05–S-09 in [SOURCES.md](SOURCES.md); technical values: [OPERATIONS](../operations/OPERATIONS.md).

## Sign-In

In a private chat, /start requests a password. Before the correct password is entered, uploads, settings, and results are unavailable. A file is not downloaded before sign-in. An incorrect password is not written to the log and does not trigger inference.

After sign-in, the following actions are shown: send a document, Several pages, Settings, Cancel, and Logout. Content, password prompts, and results are not sent to groups; the bot explains that a private chat must be used.

## One File

An image or PDF starts the scenario automatically. The bot reports receipt and processing status. An unsupported file or one unavailable through the Bot API receives a clear response. Password-protected and damaged PDFs are not cracked or executed in the first version: the bot asks the user to send an accessible, valid file.

If a separate new file arrives while a document is already active, it is not downloaded and does not replace the active document: the bot offers to wait for the result or Cancel and resend. Exceptions are the active Several pages mode and a part of the current album. Multiple documents in one image are treated as mixed input; they must be sent separately.

## Multiple Files

Several pages opens collection. The user sends images/PDFs; the bot shows the number of files/pages, Process completes collection, and Cancel cancels it. Process with no files reports that there is no document. One job is one logical document.

A Telegram album is automatically collected by chat/user/media-group ID; the order is by message ID. The media_group_id field itself does not indicate how many future messages there will be. The project rule for completion is a short quiet window; delayed parts must not silently become a different document. Before the result is committed, a new fragment of the same album cancels the previous pass and requires the whole set to be collected; after the response, the bot marks the result as incomplete and offers to resend the set through Several pages. The exact window is set by operational parameters.

## Selecting Instructions

If one profile applies, extraction continues using its saved version. If several apply, the bot shows candidates and asks the user to choose. The user can choose another personal profile or cancel. If the type/profile is missing, the bot asks the user to describe the document and required fields.

A new instruction is turned into a preview: name, applicability, fields, guidance. Save stores it and continues with the still-current upload; Edit changes the draft; Cancel saves nothing. If the temporary document has already been deleted, the profile can be saved, but the file must be sent again for processing.

## Profile Management

Settings lets a user view, create, edit, and delete only their own profiles. Saving a change always has a preview; deletion requires an explicit user action in the interface. An outdated simultaneous edit does not overwrite a newer version.

A temporary job uses a snapshot of the confirmed profile; editing settings in the middle of recognition does not change the request already in progress.

## Result

The English message shows only requested data and the statuses of unresolved fields. Original names/numbers preserve their script: the English interface does not mean document values are translated. A long result is split into messages with ordering and partial status until delivery of all parts is confirmed; silent truncation is not allowed.

If not a single field could be extracted, the bot reports failure and the reason, when established. If the type is unclear, user confirmation allows the profile to be applied, but does not make unreadable values reliable.

## Cancellation, Failure, and Restart

Cancel and /logout stop collection/queue/processing and initiate cleanup. After cancellation is committed, new submissions, parts, and retries are prohibited; a late model result is discarded. A Telegram send that has already started may complete and is not promised to be recalled; if confirmation is lost, its delivery is considered uncertain. If the local model does not stop processing, its request must finish or the runtime must be restarted before the next job.

After an emergency restart, previous documents are not restored. Any remaining files are deleted before new files are accepted. Profiles are available after signing in again. An outdated button responds “Session expired,” does not download the document again, and does not change another user's or a new job.
