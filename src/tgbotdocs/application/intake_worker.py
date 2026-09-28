"""Supervised intake parser: full image decode, PDF index, metadata-only stdout."""

from contextlib import closing
import json
import sys
import warnings

from PIL import Image

from tgbotdocs.recognition.preparation_worker import (
    Refusal, image_size, kind_of, open_pdf, pdf_size, safe_path,
)


def inspect(request):
    root = safe_path(request["root"], directory=True)
    path = safe_path(request["path"])
    if path.parent != root:
        raise Refusal("invalid_path")
    limits = {"max_pixels": request["max_pixels"]}
    kind = kind_of(path)
    page_time, budget = request["page_times"][kind], request["budget_s"]
    pages = []
    if kind == "pdf":
        with open_pdf(path) as document:
            count = len(document)
            if count <= 0:
                raise Refusal("damaged_input")
            # A whole-file refusal from a measured time bound, never a prefix.
            if count * page_time > budget:
                raise Refusal("processing_limit")
            for index in range(count):
                with closing(document[index]) as page:
                    width, height = pdf_size(page)
                pages.append({"page_id": index + 1, "file_index": 0,
                              "file_page_index": index, "kind": kind,
                              "width": width, "height": height})
    else:
        if page_time > budget:
            raise Refusal("processing_limit")
        with Image.open(path) as image:
            if image.format not in ("PNG", "JPEG"):
                raise Refusal("unsupported_format")
            width, height = image_size(image, limits)
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()  # JPEG verify() alone does not decode or detect truncation.
        pages.append({"page_id": 1, "file_index": 0, "file_page_index": 0,
                      "kind": kind, "width": width, "height": height})
    return {"kind": kind, "pages": pages}


def main():
    warnings.simplefilter("error", Image.DecompressionBombWarning)
    try:
        request = json.load(sys.stdin)
        result = inspect(request)
        encoded = json.dumps(result, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > request["response_limit"]:
            raise Refusal("processing_limit")
    except Refusal as error:
        encoded = json.dumps({"error": error.args[0]})
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        encoded = '{"error":"pixel_limit"}'
    except Exception:
        encoded = '{"error":"damaged_input"}'
    print(encoded, flush=True)


if __name__ == "__main__":
    main()
