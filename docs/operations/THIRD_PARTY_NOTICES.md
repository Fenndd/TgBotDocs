# Third-Party Notices and License Inventory

Status: T08 inventory, compiled on 2026-09-28. **This is an inventory for the delivery review, not legal advice.** It records which third-party artifacts the product uses or ships and the license each one declares. It does not decide whether a particular distribution complies. Before the package or an image is handed over, the environment owner must check each license's conditions against the actual distribution. Redistribution rights are **not** claimed here for any artifact whose terms were not checked.

Sources: Python package versions come from [`uv.lock`](../../uv.lock). The license fields come from the installed distributions' metadata (`importlib.metadata`: `License-Expression`, `License`, license classifiers and `License-File` entries) in the development environment `.venv`, which runs CPython 3.14.5 on Windows x64. The model, runtime and database entries cite their official sources.

## Python Runtime Packages

These are the packages that the application's runtime dependencies (`[project].dependencies` in [`pyproject.toml`](../../pyproject.toml)) pull in through `uv.lock`. The `dev` dependency group (`hypothesis`, `pytest`, `pytest-asyncio`, `reportlab`, `ruff`) and the build backend `hatchling` are **not** shipped and are excluded. Every locked version below matched the installed version.

| Package | Version | Declared license (metadata field) | License files in the distribution |
| --- | --- | --- | --- |
| aiofiles | 25.1.0 | Apache-2.0 (License; classifier Apache Software License) | LICENSE, NOTICE |
| aiogram | 3.31.0 | MIT (License-Expression) | LICENSE |
| aiohappyeyeballs | 2.7.1 | PSF-2.0 (License; classifier Python Software Foundation License) | LICENSE |
| aiohttp | 3.14.3 | Apache-2.0 AND MIT (License) | LICENSE.txt, vendor/llhttp/LICENSE |
| aiosignal | 1.4.0 | Apache 2.0 (License; classifier Apache Software License) | LICENSE |
| alembic | 1.20.0 | MIT (License-Expression) | LICENSE |
| annotated-types | 0.8.0 | MIT (License-Expression) | LICENSE |
| anyio | 4.15.1 | MIT (License-Expression) | LICENSE |
| attrs | 26.1.0 | MIT (License-Expression) | LICENSE |
| certifi | 2026.7.22 | MPL-2.0 (License; classifier MPL 2.0) | LICENSE |
| frozenlist | 1.8.0 | Apache-2.0 (License) | LICENSE |
| h11 | 0.16.0 | MIT (License) | LICENSE.txt |
| httpcore | 1.0.9 | BSD-3-Clause (License-Expression) | LICENSE.md |
| httpx | 0.28.1 | BSD-3-Clause (License; classifier BSD License) | not declared |
| idna | 3.20 | BSD-3-Clause (License-Expression) | LICENSE.md |
| magic-filter | 1.0.12 | MIT (License-Expression) | LICENSE |
| mako | 1.4.3 | MIT (License-Expression) | LICENSE |
| markupsafe | 3.0.3 | BSD-3-Clause (License-Expression) | LICENSE.txt |
| multidict | 6.9.1 | Apache License 2.0 (License) | LICENSE |
| pillow | 12.3.0 | MIT-CMU (License-Expression) | LICENSE (includes notices of bundled libraries, see below) |
| propcache | 0.5.4 | Apache-2.0 (License) | LICENSE, NOTICE |
| psutil | 7.2.2 | BSD-3-Clause (License) | LICENSE |
| psycopg | 3.3.6 | LGPL-3.0-only (License-Expression) | LICENSE.txt |
| psycopg-binary | 3.3.6 | LGPL-3.0-only (License-Expression) | LICENSE.txt (bundled native libraries, see below) |
| pydantic | 2.13.5 | MIT (License-Expression) | LICENSE |
| pydantic-core | 2.46.5 | MIT (License-Expression) | LICENSE |
| pypdfium2 | 5.13.0 | "BSD-3-Clause, Apache-2.0, dependency licenses" (License) | LICENSES/ and BUILD_LICENSES/ (see below) |
| python-dotenv | 1.2.3 | BSD-3-Clause (License) | LICENSE |
| sqlalchemy | 2.1.1 | MIT (License-Expression) | LICENSE, AUTHORS |
| typing-extensions | 4.16.0 | PSF-2.0 (License-Expression) | LICENSE |
| typing-inspection | 0.4.4 | MIT (License-Expression) | LICENSE |
| tzdata | 2026.4 | Apache-2.0 (License) | LICENSE, licenses/LICENSE_APACHE |
| yarl | 1.25.1 | Apache-2.0 (License) | LICENSE, NOTICE |

Notes:

- Every package declared a license; none was "not declared". `httpx` declares its license but lists no `License-File` in its metadata.
- `tzdata` is installed only on Windows (`sys_platform == 'win32'`); `psycopg-binary` only on CPython (`implementation_name != 'pypy'`).
- The metadata was read from the **Windows x64** wheels. Linux wheels of the binary packages (`pillow`, `psycopg-binary`, `pypdfium2`, `pydantic-core`, `aiohttp`, `multidict`, `yarl`, `frozenlist`, `propcache`, `markupsafe`, `psutil`) bundle different native libraries. Their notices must be re-inventoried from the Linux image. That has **not been done**.

### Bundled Native Libraries in Python Wheels

- **pypdfium2 / PDFium.** pypdfium2 itself is Apache-2.0 or BSD-3-Clause; its documentation is CC-BY-4.0. PDFium is under a BSD-style license. The pypdfium2 README says that PDFium's license and the licenses of its dependencies "have to be shipped with binary distributions". The Windows x64 wheel ships them in `pypdfium2-5.13.0.dist-info/licenses/`: `LICENSES/Apache-2.0.txt`, `BSD-3-Clause.txt`, `CC-BY-4.0.txt`, and `data/windows_x64/BUILD_LICENSES/`, which covers abseil (Apache-2.0), AGG 2.3, fast_float (MIT), FreeType (FreeType License), ICU (Unicode License v3), Little CMS, libjpeg-turbo (IJG and BSD-style), OpenJPEG (BSD-2-Clause), libpng, libtiff, LLVM libc (Apache-2.0 with LLVM Exceptions), pdfium-binaries (MIT), PDFium (BSD-style), simdutf (MIT) and zlib. Keep these files with any redistribution.
- **Pillow** bundles image libraries. Its LICENSE file (1,276 lines in 12.3.0) appends the notices of the bundled components, including FreeType, HarfBuzz, libjpeg-turbo, libpng and XZ Utils.
- **psycopg-binary** bundles `libpq` (PostgreSQL License) and OpenSSL 3 (`libssl`, `libcrypto`; Apache-2.0) in `psycopg_binary.libs/`. The wheel's `dist-info` contains only `LICENSE.txt` (LGPL-3.0); **no separate notice files for libpq or OpenSSL are shipped in the wheel**. Add their license texts to a redistributed package.

### psycopg (LGPL-3.0-only): Obligations to Note

psycopg and psycopg-binary are LGPL-3.0-only. The application uses them unmodified as separately installed libraries through the ordinary Python import mechanism. When the package or an image containing them is distributed, the usual LGPL-3.0 conditions have to be checked and met. They include:

- giving prominent notice that the library is used and is covered by the LGPL, and supplying the LGPL-3.0 and GPL-3.0 texts;
- allowing the recipient to replace or modify the library, which the installation into a normal environment from `uv.lock` supports;
- providing, or offering, the corresponding source of the library version shipped. That is the psycopg 3.3.6 source release, and a vendored `libpq` build where applicable;
- not imposing terms that forbid reverse engineering for debugging such modifications.

ADR-0005 recorded asyncpg as a non-LGPL alternative that was not selected.

## Model

| Artifact | Version / pin | License | Source |
| --- | --- | --- | --- |
| Qwen3-VL-4B-Instruct GGUF: `Qwen3VL-4B-Instruct-Q4_K_M.gguf` (SHA-256 `66358cb1…c730a0a`) and `mmproj-Qwen3VL-4B-Instruct-F16.gguf` (SHA-256 `256f3a43…9985331`) | Hugging Face repository `Qwen/Qwen3-VL-4B-Instruct-GGUF`, revision `1cd86afb9a95c410a6038ab3b40d8b578c892266` | Apache-2.0 | The official model card at the pinned revision declares `license: apache-2.0` in its front matter: <https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct-GGUF/blob/1cd86afb9a95c410a6038ab3b40d8b578c892266/README.md> (checked 2026-09-28) |

The pins are recorded in [artifacts.json](../testing/evidence/t01a/artifacts.json) and `src/tgbotdocs/recognition/runtime.py`. The weights are downloaded from the official repository in a separate preparation step. Redistributing them inside a package requires the Apache-2.0 conditions, including the license text and any NOTICE file of the model repository.

## Inference Runtime

| Artifact | Version / pin | License | Notes |
| --- | --- | --- | --- |
| llama.cpp (`llama-server` and `ggml` libraries), Windows archive `llama-b11221-bin-win-cuda-12.4-x64.zip` (SHA-256 `95e15aa4…f6a267d1`) | Release `b11221`, <https://github.com/ggml-org/llama.cpp/releases/tag/b11221> | MIT ("Copyright (c) 2023-2026 The ggml authors"; <https://github.com/ggml-org/llama.cpp/blob/b11221/LICENSE>) | The Windows archive contains **no llama.cpp `LICENSE` file**, so a package must add the MIT text. The archive does ship `LICENSE-LLVM-OpenMP` for the bundled `libomp.dll`; keep it |
| CUDA runtime libraries: `cudart-llama-bin-win-cuda-12.4-x64.zip` (SHA-256 `8c79a9b2…e32ae1d6`), containing `cudart64_12.dll`, `cublas64_12.dll`, `cublasLt64_12.dll`; `ggml-cuda.dll` links against them | Published by llama.cpp next to release `b11221` | NVIDIA CUDA Toolkit EULA (proprietary) | The archive contains **no license or notice file**. The CUDA EULA allows redistribution of certain listed runtime components only under its conditions. **Whether these files may be redistributed in the delivered package has not been checked and is not claimed.** Until it is checked, the safe path is to have the recipient download these files from the official source during installation, as the T01 preparation step does, rather than ship them |
| llama.cpp CUDA container image (Linux) | Official `server-cuda` image, pinned by digest in the Compose file (ADR-0005) | MIT for llama.cpp; the NVIDIA CUDA base image carries NVIDIA's license terms, and its Ubuntu packages carry their own licenses | The image contents, including the CUDA libraries and OS packages, have **not been inventoried**. That needs the pinned digest and a scan of the image (for example, its `/usr/share/doc/*/copyright` files and NVIDIA's container license notices) |

## Database

| Artifact | Version | License | Notes |
| --- | --- | --- | --- |
| PostgreSQL server (Windows) | 18.6, EDB binary ZIP (SHA-256 `1df55002…3b4ead28`, [POSTGRESQL_DEVELOPMENT](POSTGRESQL_DEVELOPMENT.md)) | PostgreSQL License (a permissive BSD/MIT-style license) | `scripts/setup-postgres.ps1` extracts the server license and the command-line-tool notices with the binaries; keep them. The extracted `bin` directory also holds third-party DLLs: OpenSSL 3, ICU 77, zlib, lz4, zstd, libxml2, libiconv and libintl (gettext; LGPL). Only `server_license.txt` and `commandlinetools_3rd_party_licenses.txt` are extracted with them. Whether that file covers all server-side DLLs has not been checked |
| PostgreSQL container image (Linux) | Official `postgres` image, pinned in the Compose file | PostgreSQL License for PostgreSQL; Debian or Alpine package licenses for the base | Not inventoried; see the base-image note below |
| libpq (inside psycopg-binary) | Version bundled in psycopg-binary 3.3.6 | PostgreSQL License | See [Bundled Native Libraries](#bundled-native-libraries-in-python-wheels) |

## Python Interpreter

| Artifact | Version | License | Notes |
| --- | --- | --- | --- |
| CPython | 3.14.5 (the development environment uses the python.org Windows build at `C:\Python314`; uv may install its own build on other machines) | PSF License Version 2 (PSF-2.0), with bundled third-party notices in the distribution's license file (for example OpenSSL 3.0.20, zlib, libffi, SQLite, Tcl/Tk) | The delivered interpreter's own `LICENSE.txt` applies; which build is shipped depends on the installation procedure |

## Container Base Images

ADR-0005 plans the Linux delivery as two images: the application image, built on the official llama.cpp CUDA server image (itself based on an NVIDIA CUDA Ubuntu image) plus a pinned Python runtime and the application, and the official PostgreSQL image. Each image contains an operating-system distribution with many packages under various licenses, including GPL and LGPL packages whose source must be obtainable, and NVIDIA's CUDA components under NVIDIA's terms. **This inventory does not cover their contents.** Before an image is handed over, record the exact digests and generate a package and license listing from each image; do not assume the image may be re-published.

## Application

The application source in this repository (`tgbotdocs`) is the developer's own code. Its license is not declared in `pyproject.toml` and is outside this inventory.

## Open Items

- Add the missing license texts to any redistributed package: llama.cpp MIT, libpq and OpenSSL for psycopg-binary.
- Check the NVIDIA CUDA EULA redistribution conditions before shipping the `cudart` archive files or the CUDA container image.
- Inventory the Linux wheels and both container images once they are built.
- Have the final list reviewed by someone qualified before external delivery.
