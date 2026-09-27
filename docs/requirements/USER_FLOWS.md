# User Scenarios

Status: first-version scenarios based on agreed decisions; revised on 2026-09-27 after the independent review. Sources: S-05–S-13 in [SOURCES.md](SOURCES.md); transitions and timers: [STATE_MACHINE](../architecture/STATE_MACHINE.md); technical values: [OPERATIONS](../operations/OPERATIONS.md).

## Sign-In

In a private chat, /start requests a password. Before the correct password is entered, uploads, settings, and results are unavailable. A file is not downloaded before sign-in. An incorrect password is not written to the log and does not trigger inference. The bot deletes the message containing the password after checking it; repeated failures pause password entry for a while.

After sign-in, the following actions are shown: send a document, Several pages, Settings, Cancel, and Logout. Content, password prompts, and results are not sent to groups; the bot explains that a private chat must be used.

## One File

An image or PDF starts the scenario automatically. The bot reports receipt and processing status. An unsupported file or one unavailable through the Bot API receives a clear response. Password-protected and damaged PDFs are not cracked or executed in the first version: the bot asks the user to send an accessible, valid file.

An image sent as a Telegram photo arrives resized and recompressed by Telegram; the bot uses the largest available size. Sending the image as a file keeps the original quality. When a value in a compressed photo is unreadable, the result suggests resending the document as a file.

When the bot is at capacity, it answers Busy before downloading anything. A set that cannot be processed within the processing time limit on this machine is refused before recognition with an explicit explanation; there is no fixed page limit, and nothing is silently truncated. Documents of different users take turns on the GPU, so a short document is not held up by a long one.

If a separate new file arrives while a document is already active, it is not downloaded and does not replace the active document: the bot offers to wait for the result or Cancel and resend. Exceptions are the active Several pages mode and a part of the current album. Multiple documents in one image are treated as mixed input; they must be sent separately.

## Multiple Files

Several pages opens collection. The user sends images/PDFs; the bot shows the number of files/pages, Process completes collection, and Cancel cancels it. Process with no files reports that there is no document. One job is one logical document.

A Telegram album is automatically collected by chat/user/media-group ID; the order is by message ID. A Telegram album holds at most 10 items, and files are grouped only with files, so a mix of photos and PDFs or more than 10 photos goes through Several pages. The media_group_id field itself does not indicate how many future messages there will be. The project rule for completion is a short quiet window; delayed parts must not silently become a different document. Before the result is committed, a new fragment of the same album cancels the previous pass and requires the whole set to be collected; after the response, the bot marks the result as incomplete and offers to resend the set through Several pages. The exact window is set by operational parameters.

## Selecting Instructions

If one profile applies, extraction continues using its saved version. If several apply, the bot shows candidates and asks the user to choose. The user can choose another personal profile or cancel. If the type/profile is missing, the bot asks the user to describe the document and required fields.

A new instruction is turned into a preview: name, applicability, fields, validators, and guidance. One instruction may describe several document types; each type becomes its own profile, and all of them appear in one preview. Save stores them together and continues with the current upload: a single new profile is applied to it directly; if several were created, the user chooses the one for this document. Edit changes the drafts; Cancel saves nothing. If the job ends while the preview is open, for example after Cancel or a late album part, the drafts are discarded; profiles can also be created from Settings when no document is active.

## Profile Management

Settings lets a user view, create, edit, and delete only their own profiles. Saving a change always has a preview; deletion requires an explicit user action in the interface. An outdated preview does not overwrite a newer version.

Profiles can be changed while a document is queued or being processed, but not while the bot waits for the user's answer about it. The document keeps the profiles as they were when its matching started; a change applies to later documents, and the bot says so when saving. If the document needs an answer while a profile draft is open, the bot says the document is waiting and asks its question after the draft is saved or cancelled. Several pages starts only after an open draft is closed.

## Result

The English message shows only requested data and the statuses of unresolved fields. Values appear as monospace text, so they are never turned into links or commands. Original names/numbers preserve their script: the English interface does not mean document values are translated. A long result is split into numbered messages with partial status until delivery of all parts is confirmed; silent truncation is not allowed.

If not a single value could be extracted, the bot reports failure and the reason, when established; when every requested field is absent from the document, the reason says that none of the requested data is present. If the type is unclear, user confirmation allows the profile to be applied, but does not make unreadable values reliable.

## Cancellation, Failure, and Restart

Cancel and /logout stop collection/queue/processing and initiate cleanup. After cancellation is committed, new submissions, parts, and retries are prohibited; a late model result is discarded. A Telegram send that has already started may complete and is not promised to be recalled; if confirmation is lost, its delivery is considered uncertain. If the local model does not stop processing, its request must finish or the runtime must be restarted before the next job.

After an emergency restart, previous documents are not restored. Any remaining files are deleted before new files are accepted. Messages sent while the bot was down are not processed; each affected user receives one notice to sign in and resend. Profiles are available after signing in again. An outdated button responds “Session expired,” does not download the document again, and does not change another user's or a new job.

If temporary files cannot be deleted, the bot stops accepting new documents and tells users that it is temporarily unavailable until the files are removed.
