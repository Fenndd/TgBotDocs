"""Generate T01a synthetic development assets; never run inference or Telegram."""

from __future__ import annotations

import argparse
import hashlib
import html
import importlib.metadata
import json
import math
import platform
import struct
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFont, features
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

HERE = Path(__file__).resolve().parent
WARNING = "SYNTHETIC - DEVELOPMENT ONLY - HUMAN REVIEW PENDING"
SCRIPTS = {"Latin", "Cyrillic", "Arabic", "Chinese", "Japanese", "Devanagari"}
BLUE = "#164359"
INK = "#17242d"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def unicode_cmap(path: Path) -> set[int]:
    """Read Unicode cmap formats 4/12 from the first SFNT/TTC face, without installs."""
    data = path.read_bytes()
    u16 = lambda offset: struct.unpack_from(">H", data, offset)[0]
    u32 = lambda offset: struct.unpack_from(">I", data, offset)[0]
    face = u32(12) if data[:4] == b"ttcf" else 0
    cmap = None
    for index in range(u16(face + 4)):
        record = face + 12 + index * 16
        if data[record:record + 4] == b"cmap":
            cmap = u32(record + 8)
            break
    if cmap is None:
        raise ValueError(f"Font has no cmap: {path.name}")
    covered: set[int] = set()
    for index in range(u16(cmap + 2)):
        record = cmap + 4 + index * 8
        platform_id, encoding = u16(record), u16(record + 2)
        if platform_id != 0 and not (platform_id == 3 and encoding in (1, 10)):
            continue
        subtable = cmap + u32(record + 4)
        fmt = u16(subtable)
        if fmt == 12:
            for group in range(u32(subtable + 12)):
                start, end, glyph = struct.unpack_from(">III", data, subtable + 16 + group * 12)
                covered.update(range(start + (glyph == 0), end + 1))
        elif fmt == 4:
            count = u16(subtable + 6) // 2
            ends = subtable + 14
            starts = ends + 2 * count + 2
            deltas = starts + 2 * count
            ranges = deltas + 2 * count
            for segment in range(count):
                delta = u16(deltas + 2 * segment)
                offset = u16(ranges + 2 * segment)
                for codepoint in range(u16(starts + 2 * segment), u16(ends + 2 * segment) + 1):
                    if codepoint == 0xFFFF:
                        continue
                    glyph = u16(ranges + 2 * segment + offset + 2 * (codepoint - u16(starts + 2 * segment))) if offset else codepoint
                    mapped = (glyph + delta) % 65536 if glyph else 0
                    if mapped:
                        covered.add(codepoint)
    return covered


def load_cases(path: Path, fonts: Path) -> tuple[dict, dict[str, Path]]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    cases = spec["cases"]
    if spec.get("schema_version") != 1 or len(cases) != 12:
        raise ValueError("Expected schema version 1 and exactly 12 development cases")
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("Duplicate case IDs")
    if {case["script"] for case in cases} != SCRIPTS:
        raise ValueError("All six scripts are required")
    font_paths = {case["font"]: fonts / case["font"] for case in cases}
    font_paths["arial.ttf"] = fonts / "arial.ttf"
    cmaps = {name: unicode_cmap(path) for name, path in font_paths.items()}
    for case in cases:
        for page in case["pages"]:
            values = [field["value"] for field in page["fields"]]
            values += [value for row in page.get("rows", []) for value in row.values()]
            for value in values:
                missing = sorted({ord(char) for char in value} - cmaps[case["font"]])
                if missing:
                    raise ValueError(f"{case['id']}: missing glyphs {[f'U+{cp:04X}' for cp in missing]}")
    if not features.check_feature("raqm"):
        raise RuntimeError("Pillow RAQM is required for Arabic and Devanagari shaping")
    return spec, font_paths


def text(draw: ImageDraw.ImageDraw, value: str, xy: tuple[int, int], font_path: Path,
         size: int, width: int, *, direction: str = "ltr", color: str = INK) -> list[int]:
    """Draw complete, shaped text and return its half-open tight ink box in pixels."""
    while size >= 20:
        font = ImageFont.truetype(str(font_path), size, layout_engine=ImageFont.Layout.RAQM)
        box = draw.textbbox((0, 0), value, font=font, direction=direction)
        if box[2] - box[0] <= width:
            break
        size -= 2
    else:
        raise ValueError("Text does not fit at the minimum font size")
    position = (xy[0] - box[0], xy[1] - box[1])
    draw.text(position, value, fill=color, font=font, direction=direction)
    return [xy[0], xy[1], xy[0] + box[2] - box[0], xy[1] + box[3] - box[1]]


def render_page(case: dict, page: dict, page_index: int, fonts: dict[str, Path]) -> tuple[Image.Image, list[dict]]:
    card = case["layout"] == "card"
    width, height = (2560, 1600) if card else (2480, 3508)
    image = Image.new("RGB", (width, height), "#f3f0e8" if card else "white")
    draw = ImageDraw.Draw(image)
    base_font = fonts["arial.ttf"]
    value_font = fonts[case["font"]]
    draw.rectangle((70, 70, width - 70, height - 70), outline=BLUE, width=5)
    draw.rectangle((70, 70, width - 70, 280), fill=BLUE)
    text(draw, case["title"], (130, 130), base_font, 72, width - 260, color="white")
    text(draw, WARNING, (130, 305), base_font, 36, width - 260, color=BLUE)
    text(draw, f"{case['id']} | {case['script']} | page {page_index + 1} / {len(case['pages'])}"
         + (f" | {page['side']}" if "side" in page else ""), (130, 385), base_font, 36, width - 260)
    annotations: list[dict] = []
    layout = case["layout"]
    if layout == "certificate":
        draw.rectangle((180, 480, width - 180, height - 230), outline="#9c7d34", width=9)
    left = 450 if layout == "receipt" else (260 if layout == "certificate" else 180)
    content_width = width - 2 * left
    y = 570 if not card else 530
    spacing = 320 if layout == "letter" else 245
    if card:
        spacing = 245
    for field in page["fields"]:
        if layout in ("form", "contract"):
            draw.rectangle((left - 25, y - 25, left + content_width + 25, y + 175), fill="#eef3f5", outline="#ccd9df", width=3)
        text(draw, field["key"].replace("_", " ").upper(), (left, y), base_font, 40, content_width, color=BLUE)
        box = text(draw, field["value"], (left, y + 75), value_font, 76 if card else 66,
                   content_width, direction=case.get("direction", "ltr"))
        annotations.append({"field": field["key"], "value": field["value"], "bbox_px": box,
                            "expected_status": "extracted", "normalization": "none_exact_unicode"})
        if layout == "receipt":
            draw.line((left, y + 180, left + content_width, y + 180), fill="#b7b7b7", width=2)
        y += spacing
    if page.get("rows"):
        y += 40
        column_widths = [1100, 350, content_width - 1450]
        columns = ["item", "quantity", "amount"]
        x = left
        for key, cell_width in zip(columns, column_widths):
            draw.rectangle((x, y, x + cell_width, y + 100), fill=BLUE)
            text(draw, key.upper(), (x + 15, y + 25), base_font, 38, cell_width - 30, color="white")
            x += cell_width
        y += 100
        for row_index, row in enumerate(page["rows"]):
            x = left
            for key, cell_width in zip(columns, column_widths):
                draw.rectangle((x, y, x + cell_width, y + 150), outline="#768f9b", width=3)
                box = text(draw, row[key], (x + 20, y + 45), value_font, 60, cell_width - 40,
                           direction=case.get("direction", "ltr"))
                annotations.append({"field": f"rows[{row_index}].{key}", "row_index": row_index,
                                    "column": key, "value": row[key], "bbox_px": box,
                                    "expected_status": "extracted", "normalization": "none_exact_unicode"})
                x += cell_width
            y += 150
    text(draw, "No real people, identifiers or organizations. Not a valid document.",
         (130, height - 160), base_font, 34, width - 260, color=BLUE)
    for annotation in annotations:
        x0, y0, x1, y1 = annotation["bbox_px"]
        if not (0 <= x0 < x1 <= width and 0 <= y0 < y1 < height - 190):
            raise ValueError(f"Clipped field in {case['id']}: {annotation['field']}")
    return image, annotations


def scale_annotations(annotations: list[dict], source_size: tuple[int, int], size: tuple[int, int]) -> list[dict]:
    sx, sy = size[0] / source_size[0], size[1] / source_size[1]
    result = []
    for annotation in annotations:
        x0, y0, x1, y1 = annotation["bbox_px"]
        box = [max(0, math.floor(x0 * sx) - 2), max(0, math.floor(y0 * sy) - 2),
               min(size[0], math.ceil(x1 * sx) + 2), min(size[1], math.ceil(y1 * sy) + 2)]
        result.append({**annotation, "bbox_px": box})
    return result


def image_record(path: Path, root: Path, image: Image.Image, kind: str, annotations: list[dict], **extra: object) -> dict:
    return {"path": path.relative_to(root).as_posix(), "sha256": sha256(path), "kind": kind,
            "width": image.width, "height": image.height, "bbox_convention": "half_open_xyxy_top_left_pixels",
            "annotations": annotations, **extra}


def review_sheet(path: Path, case: dict, page_images: list[tuple[Image.Image, list[dict]]], fonts: dict[str, Path]) -> None:
    """Whole-page previews followed by every expected value and its source crop."""
    field_count = sum(len(annotations) for _, annotations in page_images)
    sheet = Image.new("RGB", (1800, 1030 + field_count * 155), "white")
    draw = ImageDraw.Draw(sheet)
    base_font = fonts["arial.ttf"]
    text(draw, f"{case['id']} / {case['script']} / HUMAN REVIEW PENDING", (40, 35), base_font, 44, 1720)
    text(draw, "Reference strings and crops are generated from the same source. This is not independent review.",
         (40, 105), base_font, 28, 1720)
    for index, (image, annotations) in enumerate(page_images):
        thumbnail = image.copy()
        thumbnail.thumbnail((760, 730))
        x = 50 + index * 850
        sheet.paste(thumbnail, (x, 180))
        for annotation in annotations:
            sx, sy = thumbnail.width / image.width, thumbnail.height / image.height
            x0, y0, x1, y1 = annotation["bbox_px"]
            draw.rectangle((x + x0 * sx, 180 + y0 * sy, x + x1 * sx, 180 + y1 * sy), outline="red", width=2)
    y = 970
    for page_index, (image, annotations) in enumerate(page_images):
        for annotation in annotations:
            text(draw, f"p{page_index + 1} {annotation['field']} - expected exact value:",
                 (40, y), base_font, 27, 1720, color=BLUE)
            text(draw, annotation["value"], (40, y + 48), fonts[case["font"]], 42, 800,
                 direction=case.get("direction", "ltr"))
            x0, y0, x1, y1 = annotation["bbox_px"]
            crop = image.crop((max(0, x0 - 6), max(0, y0 - 6), min(image.width, x1 + 6), min(image.height, y1 + 6)))
            crop.thumbnail((850, 100))
            sheet.paste(crop, (900, y + 35))
            y += 155
    sheet.save(path, compress_level=9)


def generate(spec: dict, fonts: dict[str, Path], output: Path, spec_path: Path) -> dict:
    cases = []
    for case in spec["cases"]:
        folder = output / case["id"]
        folder.mkdir()
        page_images = []
        pages = []
        for page_index, source in enumerate(case["pages"]):
            image, annotations = render_page(case, source, page_index, fonts)
            page_images.append((image, annotations))
            page_id = f"{case['id']}-p{page_index + 1:02}"
            original = folder / f"{page_id}-image-file.png"
            image.save(original, compress_level=9)
            images = [image_record(original, output, image, "image_file", annotations,
                                   delivery_simulated=False, photographic_evidence=False)]
            for long_side in (1280, 2560):
                photo = image.copy()
                photo.thumbnail((long_side, long_side), Image.Resampling.LANCZOS)
                photo_path = folder / f"{page_id}-simulated-telegram-photo-{long_side}.jpg"
                photo.save(photo_path, quality=85, subsampling=2, optimize=False, progressive=False)
                images.append(image_record(photo_path, output, photo, f"simulated_telegram_photo_{long_side}",
                                           scale_annotations(annotations, image.size, photo.size),
                                           delivery_simulated=True, photographic_evidence=False,
                                           jpeg_quality=85, jpeg_subsampling=2, longer_side_px=long_side))
            pages.append({"page_id": page_id, "side": source.get("side"), "images": images})
        pdf_record = None
        if case["delivery_path"] == "pdf":
            pdf_path = folder / f"{case['id']}.pdf"
            canvas = Canvas(str(pdf_path), pagesize=(595.2, 841.92), invariant=1, pageCompression=1)
            canvas.setTitle(f"{case['id']} - synthetic development only")
            canvas.setAuthor("Synthetic fixture generator")
            for image, _ in page_images:
                canvas.drawImage(ImageReader(image), 0, 0, width=595.2, height=841.92)
                canvas.showPage()
            canvas.save()
            pdf_record = {"path": pdf_path.relative_to(output).as_posix(), "sha256": sha256(pdf_path),
                          "page_count": len(pages), "image_backed": True,
                          "page_size_points": [595.2, 841.92]}
            with pdfium.PdfDocument(str(pdf_path)) as document:
                if len(document) != len(pages):
                    raise ValueError("Unexpected PDF page count")
                for page_index, page in enumerate(pages):
                    pdf_page = document[page_index]
                    try:
                        for dpi in (150, 200):
                            bitmap = pdf_page.render(scale=dpi / 72)
                            try:
                                rendered = bitmap.to_pil().convert("RGB")
                            finally:
                                bitmap.close()
                            render_path = folder / f"{page['page_id']}-pdf-{dpi}dpi.png"
                            rendered.save(render_path, compress_level=9)
                            original_image, annotations = page_images[page_index]
                            page["images"].append(image_record(render_path, output, rendered, "pdf_render",
                                                               scale_annotations(annotations, original_image.size, rendered.size),
                                                               dpi=dpi, delivery_simulated=False,
                                                               photographic_evidence=False))
                    finally:
                        pdf_page.close()
        sheet = folder / f"{case['id']}-review.png"
        review_sheet(sheet, case, page_images, fonts)
        requested = [f"{page['page_id']}:{annotation['field']}" for page in pages for annotation in page["images"][0]["annotations"]]
        cases.append({"id": case["id"], "origin": "generated_synthetic_no_real_personal_data",
                      "permission": "synthetic development only", "script": case["script"], "language": case["language"],
                      "scenario": case.get("scenario", case["layout"]), "delivery_path": case["delivery_path"],
                      "actual_telegram_delivery": False, "human_review": {"status": "pending", "reviewer": None,
                         "required_method": "Inspect each delivered variant and compare every glyph/value and region with reference; record independent human review before quality measurement"},
                      "instruction": "Read the requested fields and cells exactly. Return only requested fields with their page IDs. Do not translate, normalize, or infer missing values.",
                      "expected_profile": {"id": f"synthetic-{case['id']}", "fixture_only": True, "requested_fields": requested},
                      "expected_response": [{"page_id": page["page_id"], "fields": [{k: annotation[k] for k in ("field", "value", "expected_status", "normalization")} for annotation in page["images"][0]["annotations"]]} for page in pages],
                      "pages": pages, "pdf": pdf_record,
                      "inputs": [pdf_record["path"]] if pdf_record else [next(image["path"] for image in page["images"] if image["kind"] == case["delivery_path"]) for page in pages],
                      "review_sheet": sheet.relative_to(output).as_posix()})
    write_review_gallery(output / "review.html", cases)
    artifacts = [{"path": path.relative_to(output).as_posix(), "sha256": sha256(path), "bytes": path.stat().st_size}
                 for path in sorted(output.rglob("*")) if path.is_file()]
    return {"schema_version": 1, "purpose": "T01a runtime development; not benchmark acceptance",
            "synthetic_only": True, "human_review_status": "pending", "eligible_for_quality_measurement": False,
            "actual_telegram_delivery": False, "arbitrary_photograph_evidence": False,
            "reproducibility": {"generator_sha256": sha256(Path(__file__)), "cases_sha256": sha256(spec_path),
                "python": platform.python_version(), "packages": {name: importlib.metadata.version(name) for name in ("Pillow", "reportlab", "pypdfium2")},
                "raqm": features.version_feature("raqm"), "fonts": {name: {"sha256": sha256(path), "face_index": 0, "cmap_check": "passed_for_all_source_values"} for name, path in sorted(fonts.items())},
                "pdf": "ReportLab invariant=1; image-backed pages; PDFium renders at 150 and 200 DPI",
                "photo_simulation": "Pillow LANCZOS resize, JPEG quality=85/subsampling=2; no Telegram upload or camera capture"},
            "cases": cases, "artifacts": artifacts, "inventory_excludes": ["manifest.json"]}


def write_review_gallery(path: Path, cases: list[dict]) -> None:
    """Local HTML gallery; review state is deliberately not inferred or auto-saved."""
    parts = ["""<!doctype html><html lang="en"><meta charset="utf-8">
<title>T01a synthetic development review - pending</title>
<style>body{font:18px system-ui,sans-serif;max-width:1400px;margin:24px auto;padding:0 20px;color:#17242d}
header{background:#fff1ca;padding:20px}h2{border-top:4px solid #164359;padding-top:24px}
table{border-collapse:collapse;width:100%;margin:20px 0}td,th{border:1px solid #bbcbd2;padding:8px;text-align:left}
.reference{font-size:24px;white-space:pre-wrap}img{max-width:100%;height:auto;border:1px solid #bbcbd2}
summary{padding:12px;background:#eef3f5;cursor:pointer}details{margin:12px 0}.page{display:grid;grid-template-columns:1fr 1fr;gap:24px}
@media(max-width:900px){.page{display:block}}@media print{details{display:block}summary{display:block}}
</style><header><h1>T01a synthetic development review</h1>
<p><strong>HUMAN REVIEW PENDING. Synthetic only. No real Telegram delivery or camera photographs.</strong></p>
<p>Compare each full image with exact reference values and their intended places. Open every delivered variant used for quality measurement.
For scripts you cannot read, compare full glyph sequences with a reference and record that method.
Generated references and crops are not independent review. Record reviewer and method separately; this gallery never marks a case reviewed.</p></header>"""]
    for case in cases:
        parts.append(f"<section><h2>{html.escape(case['id'])}: {html.escape(case['script'])} / {html.escape(case['scenario'])}</h2>")
        parts.append(f"<p>Primary path: {html.escape(case['delivery_path'])}. Human review pending.</p>")
        if case["pdf"]:
            parts.append(f"<p><a href='{html.escape(case['pdf']['path'], quote=True)}'>Open synthetic multi-page PDF</a></p>")
        parts.append(f"<p><a href='{html.escape(case['review_sheet'], quote=True)}'>Reference and source-crop contact sheet</a></p>")
        for page in case["pages"]:
            parts.append(f"<h3>{html.escape(page['page_id'])}" + (f" / {html.escape(page['side'])}" if page["side"] else "") + "</h3><div class='page'><div><table><tr><th>Requested field/cell</th><th>Exact reference</th></tr>")
            for annotation in page["images"][0]["annotations"]:
                direction = "rtl" if case["script"] == "Arabic" else "ltr"
                parts.append(f"<tr><td>{html.escape(annotation['field'])}</td><td class='reference' dir='{direction}' lang='{html.escape(case['language'], quote=True)}'>{html.escape(annotation['value'])}</td></tr>")
            parts.append("</table><p>All statuses: extracted; normalization: none (exact Unicode). These are expected values only.</p></div><div>")
            for index, image in enumerate(page["images"]):
                label = image["kind"] + (f" {image['dpi']} DPI" if "dpi" in image else "")
                if image.get("delivery_simulated"):
                    label += " - SIMULATED; not delivered through Telegram"
                parts.append(f"<details {'open' if index == 0 else ''}><summary>{html.escape(label)} ({image['width']} x {image['height']})</summary><a href='{html.escape(image['path'], quote=True)}'><img loading='lazy' src='{html.escape(image['path'], quote=True)}' alt='{html.escape(page['page_id'] + ' ' + label, quote=True)}'></a><p>Click image to inspect full resolution. Region coordinates are in manifest.json.</p></details>")
            parts.append("</div></div>")
        parts.append("</section>")
    parts.append("</html>\n")
    path.write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path, help="Absolute, empty/nonexistent directory outside any Git checkout")
    parser.add_argument("--cases", type=Path, default=HERE / "development-cases.json")
    parser.add_argument("--fonts-dir", type=Path, default=Path("C:/Windows/Fonts"))
    args = parser.parse_args()
    if not args.output.is_absolute():
        parser.error("--output must be an absolute path")
    output = args.output.resolve()
    if any((ancestor / ".git").exists() for ancestor in (output, *output.parents)):
        parser.error("--output must be outside every Git checkout")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("--output must be an empty or nonexistent directory; existing assets are never overwritten")
    spec, fonts = load_cases(args.cases, args.fonts_dir)
    output.mkdir(parents=True, exist_ok=True)
    manifest = generate(spec, fonts, output, args.cases)
    write_json(output / "manifest.json", manifest)
    print(f"Generated {len(manifest['cases'])} synthetic cases and {len(manifest['artifacts'])} assets; human review pending.")


if __name__ == "__main__":
    main()
