"""Internal parser worker. stdin carries private paths; stdout is metadata only.

Do not invoke on documents outside an application-owned retained job directory.
No document text, input names or exception messages are emitted by this worker.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import shutil
import stat
import sys
import warnings
from contextlib import closing

from PIL import Image, ImageOps
import pypdfium2 as pdfium


class Refusal(Exception):
    pass


def safe_path(path, directory=False):
    candidate = Path(os.path.abspath(path))
    for node in (candidate, *candidate.parents):
        info = node.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise Refusal("invalid_path")
    mode = candidate.stat().st_mode
    if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
        raise Refusal("invalid_path")
    return candidate.resolve()


def kind_of(path):
    with path.open("rb") as stream:
        prefix = stream.read(1024)
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if prefix.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if b"%PDF-" in prefix:
        return "pdf"
    raise Refusal("unsupported_format")


def image_size(image, limits):
    width, height = image.size
    check_pixels(width, height, limits)
    if image.getexif().get(274) in (5, 6, 7, 8):
        width, height = height, width
    return width, height


def check_pixels(width, height, limits):
    if width <= 0 or height <= 0:
        raise Refusal("damaged_input")
    if width * height > limits["max_pixels"] or width * height > Image.MAX_IMAGE_PIXELS:
        raise Refusal("pixel_limit")


def open_pdf(path):
    try:
        document = pdfium.PdfDocument(path)
    except pdfium.PdfiumError as error:
        # PDFium's fixed error enum distinguishes password requirements.
        if getattr(error, "err_code", None) == pdfium.raw.FPDF_ERR_PASSWORD:
            raise Refusal("encrypted_pdf") from None
        raise Refusal("damaged_input") from None
    if pdfium.raw.FPDF_GetSecurityHandlerRevision(document) >= 0:
        document.close()
        raise Refusal("encrypted_pdf")
    return document


def pdf_size(page):
    width, height = page.get_size()
    if not all(math.isfinite(x) and x > 0 for x in (width, height)):
        raise Refusal("damaged_input")
    return width, height


def inspect(files, limits):
    pages = []
    for file_index, path in enumerate(files):
        kind = kind_of(path)
        if kind == "pdf":
            with open_pdf(path) as document:
                if not len(document):
                    raise Refusal("damaged_input")
                for index in range(len(document)):
                    with closing(document[index]) as page:
                        width, height = pdf_size(page)
                    pages.append({"page_id": len(pages) + 1, "file_index": file_index,
                                  "file_page_index": index, "kind": kind, "width": width, "height": height})
        else:
            with Image.open(path) as image:
                if image.format not in ("PNG", "JPEG"):
                    raise Refusal("unsupported_format")
                width, height = image_size(image, limits)
            with Image.open(path) as image:
                image.verify()
            pages.append({"page_id": len(pages) + 1, "file_index": file_index,
                          "file_page_index": 0, "kind": kind, "width": width, "height": height})
    return {"pages": pages}


def usage(root):
    total = 0
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            path = Path(directory) / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                raise Refusal("invalid_path")
            if stat.S_ISREG(info.st_mode):
                total += info.st_size
    return total


def capacity(root, required, limits):
    if usage(root) + required > limits["quota_bytes"]:
        raise Refusal("storage_limit")
    if shutil.disk_usage(root).free - required < limits["free_reserve_bytes"]:
        raise Refusal("storage_limit")


def render(request, files, root, owned, limits):
    plans = []
    for info in request["pages"]:
        index = info["file_index"]
        if type(index) is not int or not 0 <= index < len(files):
            raise Refusal("invalid_request")
        path = files[index]
        kind = kind_of(path)
        if kind != info["kind"]:
            raise Refusal("damaged_input")
        if kind == "pdf":
            with open_pdf(path) as document, closing(document[info["file_page_index"]]) as page:
                width, height = pdf_size(page)
            scale = request["dpi"] / 72
            if request["max_long_side"]:
                scale = min(scale, request["max_long_side"] / max(width, height))
            # PDFium allocates ceil(point_dimension * scale) pixels.
            output = (math.ceil(width * scale), math.ceil(height * scale))
        else:
            with Image.open(path) as image:
                width, height = image_size(image, limits)
            scale = min(1, request["max_long_side"] / max(width, height)) if request["max_long_side"] else 1
            output = (max(1, round(width * scale)), max(1, round(height * scale)))
        if width != info["width"] or height != info["height"]:
            raise Refusal("damaged_input")
        check_pixels(*output, limits)
        plans.append((info, path, kind, scale, output))
    # Conservative PNG reservation, including compression/header overhead.
    remaining = sum(width * height * 5 + 65536 for _, _, _, _, (width, height) in plans)
    capacity(root, remaining, limits)
    results = []
    for info, path, kind, scale, output in plans:
        capacity(root, remaining, limits)
        target = owned / f"page-{info['page_id']}.png"
        if kind == "pdf":
            with open_pdf(path) as document, closing(document[info["file_page_index"]]) as page:
                bitmap = page.render(scale=scale)
                try:
                    image = bitmap.to_pil()
                    try:
                        if image.size != output:
                            raise Refusal("damaged_input")
                        image.save(target, format="PNG")
                    finally:
                        image.close()
                finally:
                    bitmap.close()
        else:
            with Image.open(path) as source:
                image_size(source, limits)
                oriented = ImageOps.exif_transpose(source)
                try:
                    converted = oriented.convert("RGB")
                    try:
                        if converted.size != output:
                            resized = converted.resize(output, Image.Resampling.LANCZOS)
                            converted.close()
                            converted = resized
                        converted.save(target, format="PNG")
                    finally:
                        converted.close()
                finally:
                    oriented.close()
        remaining -= output[0] * output[1] * 5 + 65536
        capacity(root, remaining, limits)
        results.append({"page_id": info["page_id"], "width": output[0], "height": output[1]})
    return {"pages": results}


def main():
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    try:
        request = json.load(sys.stdin)
        root = safe_path(request["scratch"], directory=True)
        owned = safe_path(request["owned"], directory=True)
        if owned.parent != root or not owned.name.startswith("prep-"):
            raise Refusal("invalid_path")
        files = tuple(safe_path(path) for path in request["files"])
        limits = request["limits"]
        if request["operation"] == "inspect":
            result = inspect(files, limits)
        elif request["operation"] == "render":
            result = render(request, files, root, owned, limits)
        else:
            raise Refusal("invalid_request")
    except Refusal as error:
        result = {"error": error.args[0]}
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        result = {"error": "pixel_limit"}
    except Exception:
        result = {"error": "damaged_input"}
    print(json.dumps(result), flush=True)
    return 1 if "error" in result else 0


if __name__ == "__main__":
    sys.exit(main())
