# User Guide

Status: T08 user documentation, written on 2026-09-28 from the application code (`src/tgbotdocs/application/product.py`, `settings.py`, `documents.py`, `rendering.py`). Button labels and messages are quoted as the code sends them. The behavior described here is covered by the automated tests and a local run with a controlled Bot API session. It has **not yet been checked against real Telegram**; that happens in the final joint end-to-end test. Recognition quality has not been accepted yet. Treat every result as something to check against the document.

The bot reads data from your documents on a local machine and returns the fields you asked for. It uses only the fields you define in your own profiles. It does not translate, calculate or summarize.

## Signing In

1. Open a **private chat** with the bot. In a group the bot only replies "Please use a private chat with this bot." and does nothing else.
2. Send `/start`. The bot replies "Enter the shared password."
3. Send the shared password your operator gave you. The bot deletes your password message after checking it. Deletion is a best effort: Telegram copies elsewhere cannot be guaranteed to disappear.
4. When the password is correct, the menu appears.

If the password is wrong, the bot says "Incorrect password." After 5 wrong attempts within 15 minutes, the bot says "Too many attempts. Try again after the sign-in window expires." Wait for the 15-minute window to pass, then try again.

Until you sign in, the bot downloads nothing and answers only "Send /start to sign in."

## The Menu

After you sign in, a keyboard with four buttons appears:

| Button | What it does |
| --- | --- |
| **Several pages** | Starts collecting one document from several separate messages (see [Several Pages](#several-pages)) |
| **Settings** | Opens your personal profiles (see [Settings: Your Profiles](#settings-your-profiles)) |
| **Cancel** | Stops your current document and deletes its files. With no document it replies "No active document." |
| **Logout** | Signs you out, cancels your current document and discards any open profile draft |

The commands `/cancel`, `/logout` and `/settings` do the same as the buttons. Sending `/start` while you are signed in shows the menu again, together with your document's current status, for example "Document: queued" or "Document: waiting for your profile choice".

## Settings: Your Profiles

A **profile** tells the bot which kind of document it applies to and which fields or lists to extract. Profiles are personal: nobody else can see or use yours.

Open **Settings** to see "Your profiles:" with one button per profile, or "You have no saved profiles." Then:

- **View:** tap a profile's name. The bot shows its name, "Applies to", "Original instruction", every field with its description and type, any "Format check", and "Additional instructions". The buttons are **Edit**, **Delete** and **Back**.
- **Create:** tap **Create profile** and describe your documents in plain text (see [Writing an Instruction](#writing-an-instruction)).
- **Edit:** tap **Edit** on a profile and describe only the changes. Fields you do not mention are kept. An edit must keep one profile. If you ask for more, the bot says "An edit must keep one profile and its identity. Describe changes to that profile only."
- **Delete:** tap **Delete**. The bot shows the profile and asks "Delete this profile?". Tap **Delete permanently** to delete it, or **Cancel draft** to keep it. The bot does not keep old versions of profiles, so a deleted profile cannot be restored.

Nothing is saved until you confirm a **preview**. After you create or edit a profile, the bot shows "Review every profile before saving." with the full text of every draft. Then:

- **Save all** saves every draft in the preview together. The bot replies "Profiles saved."
- **Edit** lets you describe changes to the drafts.
- **Cancel draft** discards them. The bot replies "Draft cancelled. Saved profiles were not changed."

If the bot needs more detail, it asks questions instead of showing a preview. Answer in the same chat. Your answer is added to your earlier instruction; it does not replace it. If the instruction cannot be turned into a profile, the bot says "The instruction could not be compiled. Please simplify it and try again."

An open draft expires after 15 minutes without activity. The bot then says "The profile draft expired. Open Settings to start again."

If storage is briefly unavailable while you save, the bot says "Storage is temporarily unavailable. Nothing is reported saved; retry this preview." Tap **Save all** again. Repeating the same confirmation does not create duplicates.

### Writing an Instruction

Describe in plain text which document types you have and exactly which fields or lists to extract. For example: "Invoices: invoice number, invoice date, supplier name, total amount, and a list of line items with description, quantity and price."

- **Several types in one instruction.** One instruction may describe several document types, up to 10. Each type becomes its own profile, and all of them appear in one preview.
- **Supported:** single fields (text, date, number, yes/no) and flat lists of rows with named columns. The bot may add a format check, for example a calendar date or a checksum.
- **Not supported:** a list inside a list (nested lists) or columns that are themselves records; calculations, such as totals or averages the document does not print; free-form reports; and actions other than extracting data. When the bot finds one of these, it asks how to simplify or split the request instead of silently dropping it. You can extract a value that is already printed on the document, and you may write "Do not calculate any values".

### Settings While a Document Is Active

- While your document is queued or being processed, you can still change profiles. The change applies to later documents; the bot says "This change applies to later documents. The active document keeps its profile snapshot."
- While your document **waits for your answer**, Settings is view-only: "Answer the document first or Cancel it before changing Settings."
- If your document needs an answer while a profile draft is open, the bot says "Your document is waiting for an answer. It continues after you save or cancel the open profile draft."
- **Several pages** cannot start while a profile draft is open: "Finish or cancel the profile draft before collecting several pages."

## Sending a Document

You can have **one active document at a time**. One document can be one file, one Telegram album or a Several pages set. Supported formats are **PNG, JPEG and PDF**, each up to **20 MB** (the Telegram Bot API download limit).

### One File

Send one image or one PDF. Processing starts automatically. A multi-page PDF is one document; its pages are read in order.

If you send another file while a document is active, the bot does not download it and says "A document is active. Wait or Cancel and resend."

### A Telegram Album

An album that you send in one go is collected automatically as one document, in message order. The bot waits for a short quiet moment (2 seconds by default) before it treats the album as complete.

- A Telegram album holds **at most 10 items**.
- Telegram groups **files only with files**, so photos and PDF files cannot be mixed in one album.
- For more than 10 pages, or a mix of photos and files, use **Several pages**.

If a late part of the album arrives before the result is sent, the bot says "A late album page arrived. The earlier pass was stopped; the complete album will be checked again." If a late part arrives after the result was sent, the bot says "The result was for an incomplete album. Resend the complete set using Several pages."

### Several Pages

1. Tap **Several pages**. The bot says "Send all pages as photos or PNG, JPEG and PDF files, then choose Process."
2. Send the pages in order. After each accepted file, the bot reports "Collected N files and M pages. Send more or choose Process."
3. Tap **Process** (or send the text `Process`). If downloads are still running, the bot waits for them first.
4. **Cancel** ends the collection and deletes the files.

If one page fails, for example because the file is too large, the bot tells you why and adds "Other accepted pages are still collected." Tapping Process with no pages gives "No document is present. Send pages before Process."

### Photo or File?

A photo sent as a Telegram **photo** is resized and recompressed by Telegram. The bot uses the largest size Telegram provides. A photo sent as a **file** (document) keeps its original quality. If a result from a photo is not complete, the bot adds "For better quality, resend the document as a file."

### Refusals Before Processing

| Message | Meaning |
| --- | --- |
| "Busy. Please try again later." | The machine is at capacity (8 active documents by default). Nothing was downloaded. |
| "Temporarily unavailable. Please try again later." | The database, the local recognition service or temporary storage is unavailable. Nothing was downloaded. |
| "This file exceeds the 20 MB download limit. Send a smaller original file." | The file is too large for the Telegram Bot API. |
| "Unsupported file. Send a PNG, JPEG or PDF." | Other formats are not accepted. |
| "This PDF is password protected. Send an unprotected copy." | Protected PDFs are not opened. |
| "This file is damaged or cannot be decoded. Please resend the original." | The file could not be read. |
| "This image exceeds the decoded pixel limit. Send a smaller image." | The image is too large to decode safely. |
| "The complete document cannot be processed within the time limit on this machine. Nothing was truncated." | There are too many pages to finish within the processing time. Split the document. |

## When the Bot Needs Your Help

After reading the document, the bot looks for the profile that fits.

- **One profile fits:** extraction continues automatically.
- **The type is unclear:** the bot says "The document type or the matching profile is unclear. Choose the profile for this document, or send a new instruction." Tap one of your profiles, **New instruction** or **Cancel**. A profile you choose is applied, but that does not make unreadable values reliable.
- **No profile fits, or you have none:** the bot says "None of your profiles matches this document." and asks you to describe the document type and the fields to extract. Send the instruction as text, or choose one of your profiles if the bot offers them.

After you describe the document, the bot shows a preview: "Review every profile before saving. Saved profiles are also used for later documents." Tap **Save all**, **Edit** or **Cancel draft**.

- If you saved **one** profile, the bot says "Profile saved. The document continues with it."
- If you saved **several**, the bot says "Profiles saved. Choose the profile for this document."
- **Cancel draft** saves nothing and asks for an instruction again.

While the bot waits for a button, typing text gives "Choose one of the buttons above, or Cancel." If you do not answer within **15 minutes**, the document expires: "The document waited too long for your answer and expired. Please resend it."

Documents may also end without a result:

- "This does not look like a document. Nothing was extracted."
- "The pages seem to belong to different documents. Send each document separately." Several documents in one image count as mixed input.
- "The document could not be read. Send a clearer image or the original file."

## The Result

The result is plain English text:

```text
Result: Partial
Profile: Invoice (chosen by you)
Invoice number: INV-0001
Invoice date: Unreadable
Supplier: Missing
Line items: Partial
Row 1
Description: Paper
Quantity: 2
```

- The first line is **Result: Complete**, **Result: Partial** or **Result: Failed**.
- The **Profile** line names the profile that was used. "(chosen by you)" means you chose it manually.
- Extracted values appear in `monospace`. They are never turned into links or commands. Values keep their original script and are not translated.
- A field that was not extracted shows a status instead of a value:
  - **Missing:** the value is not present in the document.
  - **Unreadable:** the value is present but could not be read reliably.
  - **Unreadable (did not pass the format check):** a value was read, but it failed its format check. The rejected value is never shown.
  - **Ambiguous:** more than one plausible value was found.
- Lists show their status (Complete, Partial, or a reason such as Missing), then numbered rows.
- **Failed** adds either "None of the requested data is present in the document." or "None of the requested data could be reliably extracted."
- A long result is split into messages that begin "Part 1/3 (partial until all parts arrive)". Nothing is truncated. The result is complete only when all parts have arrived.
- If a single value is longer than one Telegram message, no result is sent: "A value is longer than one Telegram message, so the result could not be sent. Nothing was truncated."
- If delivery fails, the bot says "The result could not be delivered completely. Please resend the document." Parts that have already arrived are not sent again.

## Time Limits

- **Processing:** each document has a processing budget, 30 minutes by default. It counts only the machine's work on your document. Waiting for you or for other users' documents does not count. When the budget runs out, the bot says "The document could not be processed within the time limit on this machine. No result was returned."
- **Queue:** "The document waited too long in the queue and expired. Please resend it later."
- **Collection:** a Several pages set or an album that stays incomplete for 15 minutes expires: "The document collection expired. Please resend it."
- **Answers and drafts:** 15 minutes of inactivity, as described above.
- **Local service outage:** "The local recognition service is temporarily unavailable. Please resend the document later."

## Cancel and Logout

**Cancel** stops the current document at any stage and deletes its files. The bot says "Cancelled. Cleanup is running." A message that Telegram has already started sending may still arrive; nothing new is sent after that.

**Logout** also cancels the document and discards any open profile draft. The bot says "Logged out. Send /start to sign in again." Your saved profiles stay.

## When the Bot Restarts

Sign-ins, documents in progress and open drafts exist only in the bot's memory. After a restart:

- Messages sent while the bot was down are not processed. You get one notice: "The bot restarted. Send /start to sign in and resend your document."
- Send `/start`, enter the password again and resend the document.
- Buttons from before the restart answer "Session expired" and do nothing.
- Your saved profiles are still there.

## Privacy Basics

- Documents, prepared pages and results are temporary. They are deleted after the result is delivered, or when the document is cancelled, expires or fails. They are never stored in the database or kept as history, and they are not part of backups.
- The database keeps only your Telegram user ID and your saved profiles: name, applicability, original instruction, fields and guidance. Do not put personal data into an instruction unless you want it stored.
- Processing happens on the operator's local machine, with no cloud recognition service.
- Operators receive only technical alerts without document content. The product has no feature for operators to read your documents or results.
- Ordinary file deletion does not guarantee physical erasure from disks or all system traces, and deleted Telegram messages may still exist in other copies.
