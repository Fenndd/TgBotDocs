# T08 Local Packaging and Final Product Review

Date: 2026-09-28. Final source reviewed and checked: `8a67ec6` on `main`. **Local Windows product preparation is complete for the developer's joint Telegram test. Full T08 platform/acceptance is not complete.** No real Telegram request, push, deployment, sealed benchmark or native Linux verification was performed. The developer's deferred acceptance sequence remains unchanged (S-14, ED-016).

## Product and Frozen Identity

T02–T07 local implementation provides external configuration, PostgreSQL migrations and personal ownership, private sign-in, previewed profiles, file/photo/album/Several pages collection, frozen local recognition, in-job type/profile dialogue, English scalar/list output, partial results, cancellation, cumulative processing budget, expiry, restart cleanup, dependency health and content-free operator events. Earlier staged evidence is in the [T04](T04_PROGRESS_REPORT.md), [T05](T05_PROGRESS_REPORT.md), [T06](T06_PROGRESS_REPORT.md) and [T07](T07_LOCAL_REPORT.md) reports.

The reviewed T01b configuration remains byte-for-byte frozen at `C:\Users\nikit\TgBotDocsData\dev\frozen\frozen-t01b.json`, SHA-256 `dd1d01a0e8ff878a60b7b4bf61b6bcb20939cd5bd5695bed4eaa79a55ea633f6`. Recognition source, prompts, dependency pins, model and runtime artifacts were not changed by T08 remediation. The [T01b calibration report](T01B_CALIBRATION_REPORT.md) retains risk–coverage, selected point and per-page admission times. It is tuning evidence, not independent quality acceptance.

A relocated executable is allowed only with the frozen executable's exact hash. A different hash is refused with `runtime_executable_differs_from_frozen_recalibrate`; merely supplying `RUNTIME_EXECUTABLE` and a new hash does not authorize a recognition change. Linux calibration/platform acceptance is deferred for the developer (ED-017).

## Delivered Local Preparation

| Component | Result | Actual verification and boundary |
| --- | --- | --- |
| Windows bot startup | Task Scheduler directly owns Python with `run --restart-on-failure`; startup/run failures retry after 60 seconds inside the same process, after cleanup | Unit regressions for retry, normal stop and cancellation; task definition dry run. Actual registration/boot/S4U/session-0 CUDA remains unperformed |
| Windows task removal | Stop the directly owned action and wait for it to leave Running; timeout refuses unregister | Read-only review and syntax checks. Actual elevated stop remains unperformed |
| Windows private directories | Dedicated disjoint app/Python/config/data ACL plans; SYSTEM/Administrators full control, concrete enabled local bot user RX/R/M respectively; broad groups and reparse paths refused | Eight native PS5.1 packaging regressions, dry ACL plan leaves existing SDDL unchanged. Elevated ACL application/effective account access remains unperformed |
| Windows PostgreSQL | Pinned 18.6 native tools and existing loopback cluster; protected ACL plans for the two owned trees, plus service-identity guard before removal | Read-only native ACL/identity regressions and actual cluster dry plan; real PostgreSQL application/backup checks. Elevated ACL application, parent traversal/effective NETWORK SERVICE access, service registration/boot are unperformed |
| Permitted backups | Exactly users, current profiles and Alembic version; private new archives; restore only into a fresh app-owned database; current/live targets refused | Real PG18.6 under PS7.6.5 and Windows PS5.1: config/legacy credentials, Backup/Verify/fresh Restore, refusals and fault-injected cleanup. Native Linux procedure remains unperformed |
| Linux Compose | Required complete base/app image references; production override removes build; local tags require opt-in; dedicated temporary mount, read-only inputs, internal DB and no published ports | Actual Docker CLI29.8.1 / Compose5.5.1 config and guard checks, Bash syntax, init-script mock and hadolint2.15.1. No daemon, image build, native GPU or initialized DB was run |
| Linux database privileges | First-volume script separates the bootstrap administrator from a non-superuser application role; existing volumes are not silently converted | Script mock/static inspection only; native execution pending |
| Operator and user documents | [Windows](../operations/INSTALL_WINDOWS.md), [Linux](../operations/INSTALL_LINUX.md), [configuration](../operations/CONFIGURATION.md), [runbook](../operations/RUNBOOK.md), [user guide](../operations/USER_GUIDE.md), [backup](../operations/BACKUP_RESTORE.md), [notices](../operations/THIRD_PARTY_NOTICES.md), [exact PC steps](../operations/LOCAL_PC_JOINT_TEST.md) | Internal links and source comparison. Real-Telegram dialogue/platform procedures remain pending |

Linux static checks used public reference fixtures to exercise configuration; those fixtures are not accepted image digests. The pinned b11221 upstream CUDA image and the production application's manifest digest have not been established/built. Do not substitute a nearby build, a local image ID or an invented digest. Native platform evidence and a new calibration are prerequisites for using a distinct Linux runtime. Licenses/notices describe checked metadata and unresolved redistribution terms; no bundled redistribution claim is made.

## Independent Final Review and Remediation

Requested model/effort: GPT-6 Astra/high for coupled product transitions/privacy/lifecycle; GPT-6 Sol/high for independent Windows packaging. Bounded implementation/doc workers used the project routing policy. Tool requests record these settings; no separate runtime attestation was provided. Reviewers did not edit repository files, start real Telegram, use GPU, register tasks/services or apply ACLs.

| Finding | Fix | Evidence |
| --- | --- | --- |
| P1: dependency WARNING/ERROR and traceback could persist tokens/document text | File-handler positive allowlist accepts only structured technical event shapes; rejects dependency/root records, arbitrary text, traceback and stack information | Synthetic dependency token/document markers persisted before the fix; independent repeat and regression confirm they no longer persist while permitted events remain |
| P2: queued Settings preview could send after logout/replaced session | Check exact session identity and revision at FIFO dispatch, withdraw with `SendSkipped` | Independent blocked-send reproduction and regression confirm old profile preview is withdrawn |
| P1: quota I/O failure killed user actor, stalled later messages and could hang close | Convert `OSError` from capacity accounting into controlled `LifecycleError("storage_limit")` before creating a job | Regression leaves no partial job; independent product probe processes later `/start` and closes within two seconds |
| P2: ACL script accepted Users/Authenticated Users group SIDs | Require one enabled local `Win32_UserAccount` before preparing grants | Two group-refusal regressions; independent source review confirms closure |
| P1: PostgreSQL binaries/cluster retained broad inherited permissions | Replace permissions on the two fixed trees with protected DACLs; keep shared parents and external credentials untouched; refuse reparse points | Read-only PS5.1 ACL-plan regressions and actual 3,003-entry development-cluster plan; no permissions applied |
| P2: PostgreSQL Unregister could target another installation with the same service name | Verify canonical executable/cluster/name and NETWORK SERVICE identity before any stop, removal or ACL mutation; fail closed on foreign/ambiguous arguments | Independent source reproduction; synthetic identity regressions, with no service changes |
| Startup/docs inaccuracies | Describe startup event as local initialization before polling; preserve already-started-send cancellation boundary; Process closes Several pages; safe temporary quarantine and permitted fresh-target backup procedure | Reviewer/source comparison and local links |

The PostgreSQL service-identity parser was compared with the [pinned PostgreSQL18.6 `pgwin32_CommandLine` implementation](https://raw.githubusercontent.com/postgres/postgres/REL_18_6/src/bin/pg_ctl/pg_ctl.c), which constructs the Windows service executable, `runservice`, name, cluster and option arguments. Unregistration itself identifies a service by name, so the wrapper must verify installation identity first.

No additional confirmed source blocker was found in the bounded whole-product pass after these fixes. Reviewed seams include authentication, owner predicates, profile preview, collection/late albums, GPU queue/budget, generation/cancellation, delivery, temporary ownership/cleanup and packaging. This review is evidence of the inspected paths, not a universal absence-of-defects claim. A generic actor error-recovery state was not added: the verified fix addresses the observed filesystem failure without introducing unverified partial-transition recovery.

## Current Executed Checks

From `C:\CodeProj\TgBotDocs\TgBotDocs` with TEMP/TMP outside AppData:

```powershell
$env:TEMP='C:\Users\nikit\TgBotDocsData\test-temp'
$env:TMP=$env:TEMP
$env:TGBOTDOCS_TEST_DATABASE_CREDENTIALS='C:\Users\nikit\TgBotDocsData\postgresql-dev-credentials.json'
.venv\Scripts\python.exe -m pytest -q --basetemp=C:/Users/nikit/TgBotDocsData/pytest-final-product
.venv\Scripts\python.exe -m ruff check src tests migrations scripts
```

Final results on committed source `8a67ec6`: **538 passed, 1 skipped in 183.30 s**; Ruff passed. The skipped opt-in runtime check does not imply native GPU/Linux acceptance; separate actual frozen-GPU checks are below. Focused product remediation: 43 tests passed; Windows packaging: 38 tests passed in 23.66 s, including 30 PostgreSQL ACL/identity cases. Both PS5.1/PS7 parsing and the worker's PS7 identity/dry-run fixtures passed. All 415 local Markdown targets resolve. No recognition dependencies were upgraded. `git diff --check` passed.

`python -m tgbotdocs check --config C:\Users\nikit\TgBotDocsData\foundation-check.env` returned `local_startup_verified` against the real frozen CUDA runtime and PostgreSQL, without Telegram calls.

Controlled actual-model product check at 10:12:30 UTC completed in 38.3 s with **zero Telegram network requests**: Settings profile preview/save, synthetic invoice file 8.9 s / photo 7.1 s with exact requested invoice values, second type awaiting instruction→preview→Save→complete result 11.8 s, exact synthetic total. Zero job directories/reservations left; synthetic profiles deleted. Final post-remediation rerun at **15:05:11 UTC** passed in **41.7 s**: file 9.7 s / photo 7.7 s / second type 12.1 s; same exact synthetic requested values and states; zero Telegram requests, zero job directories/reservations, synthetic profiles removed. A fresh export of committed `d0e45f5` reproduced 34 locked production packages with Python 3.14.5 / uv 0.12.19, no dev dependencies, all 24 application-module imports and frozen identity matching. Its real CUDA/PostgreSQL no-Telegram startup returned `local_startup_verified`. Export metadata: `C:\Users\nikit\TgBotDocsData\packaging-checks\committed-d0e45f5-57fb5e008cf746ffb1fb8cb1a1fd6426\result.json`. This reuses the host interpreter/cache and is not clean-machine or native Linux acceptance. These synthetic functional results do not accept recognition quality.

Parent Backup/Verify on the actual local database created `C:\Users\nikit\TgBotDocsData\backups\profiles-local-check-20260928T150035Z.dump` (5,972 bytes, SHA-256 `fe92da0eaed286688b21d956041799c7c761e34f40f2d1b1b54bdc9867e561d9`). Restored table set and checksums matched (1 Alembic row / 0 profile rows / 2 user rows); owned scratch DB was dropped. The source was not replaced and no existing rows were removed. Worker scratch refusal/restore/cleanup evidence is outside Git at `C:\Users\nikit\TgBotDocsData\test-temp\t08-backup-b86104e69b564877899e290187912e7b\result.json`; all its owned DBs and fixture credentials/dumps were removed. Archives must be trusted; object listing checks are not an audit of arbitrary embedded SQL.

Final actual resilience check at **15:08:39 UTC** passed in **40.0 s**, again with zero Telegram requests: baseline exact synthetic value 8.3 s; runtime crash produced an explicit error; a new job after recovery returned the exact value 10.5 s; database-unavailable/available events were logged. Zero job directories/reservations remained; operator messages were content-free; log checks found no document value, password or token. Sampled peak bot RSS 245 MiB, runtime RSS 3,047 MiB and whole-device GPU memory 5,153 MiB. This confirms inspected local resilience/privacy/resource paths, not recognition quality or an unknown SLA.

## Required Deferred Acceptance

- Joint real-Telegram E2E with the developer: token/BotFather setup, real transport and dialogue, photo/file/album/multipage/partial/cancel/timeout/restart/isolation checks. Follow [the exact PC steps](../operations/LOCAL_PC_JOINT_TEST.md); the bot is not running autonomously.
- Then prepare/review/seal/run **one** integrated 70-case T01c/T07 benchmark. Recognition quality remains **not accepted**.
- Windows clean-machine elevated permissions, service/task registration, boot, dedicated-account/session-0 CUDA and actual forced-stop/recovery checks.
- Native Linux x86-64/NVIDIA, base/application manifest references, build/calibration/startup/migrations/roles/GPU/cleanup/backup checks. **Native Linux verification: not performed.** The native host/platform procedure is a deferred developer decision; this Windows PC's static CLI checks do not satisfy it.
- Customer machine/workload/SLA, external publication/delivery and deployment remain separate decisions. No such action was performed.
