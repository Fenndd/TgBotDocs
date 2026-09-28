# Joint Telegram Test on the Developer's PC

Prepared for the current Windows PC on 2026-09-28. All paths below were checked on this PC; they intentionally differ from the generic clean-machine examples. No real Telegram request has been made by this development run. Start polling and send test messages only together with the developer. This test does not replace the deferred sealed T01c/T07 recognition benchmark or native Linux verification.

## Local Configuration

The private configuration is **`C:\Users\nikit\TgBotDocsData\bot.env`**, outside Git and AppData. Its ACL permits the current Windows owner and SYSTEM. It already contains the application's non-superuser PostgreSQL connection, the verified model/frozen paths and a random sign-in password. `BOT_TOKEN` is blank. The development check configuration `foundation-check.env` contains synthetic credentials for controlled testing and must not be used to connect a real bot.

1. Open `bot.env` locally in a text editor. Do not paste its contents into chat, reports or Git.
2. Fill `BOT_TOKEN=` with the BotFather token. In BotFather, disable adding this bot to groups (`/setjoingroups` → Disable). Keep the token in this external file only.
3. Keep the generated `SHARED_PASSWORD`, or replace it with a random password of at least 16 characters. Read/copy it locally when signing in; do not put it into a command-line argument. A password change takes effect after restarting the bot.
4. Leave `OPERATOR_TELEGRAM_IDS` empty for the initial test. After the operator has started a private chat with the bot, optionally add that numeric user ID and restart. Operator alerts then use Telegram.
5. Preserve `DATA_ROOT=C:\Users\nikit\TgBotDocsData\dev`, the frozen file and `PROCESSING_S=1800`. Do not edit the frozen JSON or replace its runtime/model files. A recognition configuration change requires new calibration.

The PostgreSQL server is already installed at `C:\Users\nikit\TgBotDocsData\postgresql-18.6\pgsql`; its existing cluster listens on `127.0.0.1:55432`. Do not re-initialize the cluster. The current local test uses an ordinary hidden PostgreSQL process, without registering a Windows service or bot task. Boot registration and session-0 CUDA are separate unperformed T08 checks in [INSTALL_WINDOWS](INSTALL_WINDOWS.md).

## Start and Stop

Open PowerShell on this PC. The first two commands start/preserve the existing database and verify the local application; **`check` sends no Telegram requests**. It cleans owned temporary leftovers, applies migrations and briefly starts/stops the frozen GPU runtime. It needs no bot network access but validates the token's format.

```powershell
Set-Location C:\CodeProj\TgBotDocs\TgBotDocs
.\scripts\setup-postgres.ps1 -Action Start -DataRoot C:\Users\nikit\TgBotDocsData
.venv\Scripts\python.exe -m tgbotdocs check --config C:\Users\nikit\TgBotDocsData\bot.env
```

Expected check output: `local_startup_verified`, exit code 0. If it fails, follow [RUNBOOK](RUNBOOK.md); do not delete a whole data directory or start a second process. Detailed configuration is in [CONFIGURATION](CONFIGURATION.md).

When the developer is ready for the joint Telegram test, start the foreground bot:

```powershell
.venv\Scripts\python.exe -m tgbotdocs run --config C:\Users\nikit\TgBotDocsData\bot.env
```

This command **contacts Telegram** and prints `tgbotdocs_starting`. Keep the PowerShell window open. Stop with Ctrl+C; cleanup releases model/parser children and owned job directories. On Windows a Ctrl+C exit may return 0 without printing `tgbotdocs_stopped`. PostgreSQL stays running independently. Run only one bot instance. Technical logs live in `C:\Users\nikit\TgBotDocsData\dev\logs\tgbotdocs.log`; they rotate daily with seven previous files retained. Do not enable verbose dependency/SQL logs.

## Joint Scenarios

Use a private chat with the bot and synthetic documents initially. The user-facing dialogue is English; [USER_GUIDE](USER_GUIDE.md) explains the buttons and outcomes.

1. `/start`, sign in with the local `SHARED_PASSWORD`, then Settings: describe fields for an invoice, review the generated profile and Save. Send one invoice as a file; verify all pages and the requested values in the response.
2. Send the same document as a photo and compare the outcome. A Telegram photo can be compressed; send as a file when original quality matters. Verify the bot can return withheld/partial data honestly.
3. Send a multipage PDF, a Telegram album and a Several pages set closed with Process. Check page order, late album behavior, type clarification and the in-job instruction/preview path for a new type.
4. With a second Telegram account, verify personal profile isolation and one active job per user. Exercise Cancel while waiting and while processing; no new send or retry may start after committed cancellation; a request already in flight can still arrive.
5. Verify waiting expiry and a configured processing-budget refusal using suitable synthetic cases, without changing the frozen recognition budget. Try unsupported/encrypted content, a file above 20 MB and inaccessible/deleted Telegram messages.
6. Stop during a job, restart, sign in again and resend. Profiles persist; authorization and unfinished document tasks do not resume. Check owned temporary cleanup and absence of orphan children.
7. Record the actual Telegram scenarios, results, failures and timings in a testing report. Only after the joint E2E succeeds, prepare/review/seal the one integrated 70-case T01c/T07 benchmark according to [T01_PROCEDURE](../testing/T01_PROCEDURE.md). Recognition quality remains unaccepted until that run passes.

Do not simulate a successful real-Telegram test in the acceptance report. Native Linux and clean-machine Windows boot/service checks remain separate requirements. The external configuration and PostgreSQL backups must never include temporary documents; use [BACKUP_RESTORE](BACKUP_RESTORE.md) for permitted persistent data.
