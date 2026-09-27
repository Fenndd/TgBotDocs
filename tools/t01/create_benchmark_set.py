"""Prepare the sealed T01c benchmark package (40/20/10); never runs a model or Telegram.

Writes plan.json (a `BenchmarkPlan`), every synthetic input, per-case reference sheets,
printable originals for the 20 difficult cases, capture instructions and a README.
Human-captured inputs are recorded later by `python -m tgbotdocs.recognition.benchmark
ingest`. All sources are new synthetic families: the generator refuses case IDs, field
IDs or printed values of four or more characters shared with the development/tuning
specifications (short counts such as "2" inevitably recur).

Profile library rule: every case receives three profiles owned by one synthetic user,
ordered by a per-case hash: its category's profile plus the profiles of the next two
categories in the fixed order of `category_order` (cyclic). Special negatives: equal
profiles get the receipt profile, its equally applicable twin and one distractor; mixed
documents get both documents' profiles and the next unused category; the no-profile case
gets the three categories that follow its own.
"""

from __future__ import annotations

import argparse
import functools
import hashlib
import html
import importlib.metadata
import json
import platform
import sys
from pathlib import Path
from typing import Callable

import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFilter, ImageFont, features
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import create_development_set as development  # noqa: E402  (hash-pinned; imported, never modified)

from tgbotdocs.recognition import benchmark  # noqa: E402
from tgbotdocs.recognition.contracts import ExtractionProfile, ListField, ScalarField  # noqa: E402
from tgbotdocs.recognition.corpus import (Artifact, ExpectedList, ExpectedOutcome, ExpectedRow,  # noqa: E402
                                          ExpectedValue, Origin)

A4 = (2480, 3508)
CARD = (2560, 1600)
RECEIPT = (1240, 3100)
INK = "#1d252c"
FOOTER = "Synthetic test document - fictional people and organizations - not valid for any purpose."
REVIEW_PASSWORD = "benchmark-review-only"
PDF_PAGE = (595.2, 841.92)
PERMISSION = "synthetic benchmark document generated for T01c; fictional content, no real personal data"
REFUSALS = {"not_document": "not_document", "blank": "unreadable", "illegible": "unreadable",
            "mixed_image_set": "mixed", "mixed_pdf": "mixed", "equal_profiles": "uncertain",
            "protected_pdf": "input_refused", "no_suitable_profile": "no_profile"}
TEXT_COLUMNS = {"description", "entry_text"}
INDEPENDENT_VALUE_LENGTH = 4
CONDITION_TEXT = {
    "rotation": "Hold the phone rotated about 15-30 degrees relative to the page edges; keep the whole page in frame and in focus.",
    "perspective": "Photograph from an oblique angle (about 30-45 degrees from straight above) so the page looks like a trapezoid; keep the whole page in frame.",
    "dim_lighting": "Use dim or uneven light (main light off, one lamp from the side, no flash) so part of the page is clearly darker.",
    "glare": "Let a bright lamp or the flash reflect on the page (a clear plastic sleeve helps) so a glare spot covers part of it, not all of it.",
    "blur": "Take the photo slightly out of focus or with slight motion; text should look soft while the layout stays recognizable.",
    "partial_crop": "Frame the page so that the {side} part of the document (about 10-25%) is outside the photo.",
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- specification

def load_spec(path: Path, fonts_dir: Path) -> tuple[dict, dict[str, Path]]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    if spec.get("schema_version") != 1:
        raise ValueError("Expected benchmark specification schema version 1")
    if not features.check_feature("raqm"):
        raise RuntimeError("Pillow RAQM is required for Arabic and Devanagari shaping")
    fonts = {name: fonts_dir / name for name in {case["font"] for case in spec["cases"]} | {"arial.ttf"}}
    coverage = {name: development.unicode_cmap(font) for name, font in fonts.items()}
    for case in spec["cases"]:
        missing = sorted({ord(char) for text in printed_strings(case, spec) for char in text}
                         - coverage[case["font"]] - {0x20})
        if missing:
            raise ValueError(f"{case['id']}: font lacks glyphs {[f'U+{cp:04X}' for cp in missing]}")
    return spec, fonts


def page_fields(page: dict) -> dict[str, str]:
    """Scalars printed on a page, before and after its rows, in printed order."""
    return {**page.get("fields", {}), **page.get("after_rows", {})}


def printed_strings(case: dict, spec: dict) -> list[str]:
    language = spec["languages"][case["language"]]
    strings = []
    for page in case["pages"]:
        category = page.get("category", case["category"])
        strings.append(language["titles"][category])
        strings += [language["labels"][key] for key in page_fields(page)]
        strings += list(page_fields(page).values())
        for row in page.get("rows", []):
            strings += list(row.values()) + [language["labels"][key] for key in row]
    for row in case.get("rows", []):
        strings += list(row.values()) + [language["labels"][key] for key in row]
    list_field = list_field_id(spec, case["category"])
    if list_field:
        strings += [language["labels"][list_field], language["continued"], language["continues"]]
    if case["layout"] == "letter":
        strings += language["letter_body"]
    strings += case.get("printed_instruction", [])
    return strings


def list_field_id(spec: dict, category: str) -> str | None:
    return next((field["id"] for field in spec["profiles"][category]["fields"] if "columns" in field), None)


def profile_field_ids(spec: dict) -> set[str]:
    ids = set()
    for profile in spec["profiles"].values():
        for field in profile["fields"]:
            ids.add(field["id"])
            ids.update(column["id"] for column in field.get("columns", []))
    return ids


def printed_values(case: dict) -> set[str]:
    values = {value for page in case["pages"] for value in page_fields(page).values()}
    values |= {value for page in case["pages"] for row in page.get("rows", []) for value in row.values()}
    return values | {value for row in case.get("rows", []) for value in row.values()}


def check_independence(spec: dict, earlier_specs: list[dict]) -> None:
    """Benchmark sources must share no field ID, case ID or printed value with earlier splits."""
    ids, values, cases = {"rows"}, set(), set()
    for earlier in earlier_specs:
        for case in earlier["cases"]:
            cases.add(case["id"])
            for page in case["pages"]:
                ids.update(field["key"] for field in page["fields"])
                values.update(field["value"] for field in page["fields"])
                for row in page.get("rows", []):
                    ids.update(row)
                    values.update(row.values())
    if profile_field_ids(spec) & ids:
        raise ValueError("Benchmark profile field IDs must differ from development/tuning field IDs")
    # Small counts such as "2" inevitably recur; every longer value must be new.
    distinctive = {value for value in values if len(value.strip()) >= INDEPENDENT_VALUE_LENGTH}
    shared = [case["id"] for case in spec["cases"] if printed_values(case) & distinctive]
    if shared:
        raise ValueError(f"Benchmark values repeat development/tuning values in {', '.join(shared)}")
    if {case["id"] for case in spec["cases"]} & cases:
        raise ValueError("Benchmark case IDs must not reuse development/tuning IDs")
    if any(profile["name"].lower().startswith("synthetic") for profile in spec["profiles"].values()):
        raise ValueError("Benchmark profiles must be worded independently of tuning fixture profiles")


def earlier_specs() -> list[dict]:
    return [json.loads((HERE / name).read_text(encoding="utf-8"))
            for name in ("development-cases.json", "tuning-cases.json")]


# ---------------------------------------------------------------- ground truth and plan

def build_profile(spec: dict, key: str) -> ExtractionProfile:
    source = spec["profiles"][key]
    fields = []
    for field in source["fields"]:
        if "columns" in field:
            columns = tuple(ScalarField(id=c["id"], label=c["label"], description=c["description"], type="text")
                            for c in field["columns"])
            fields.append(ListField(id=field["id"], label=field["label"], description=field["description"],
                                    columns=columns))
        else:
            fields.append(ScalarField(id=field["id"], label=field["label"], description=field["description"],
                                      type="text"))
    return ExtractionProfile(id=source["id"], owner=spec["owner"], version=1, name=source["name"],
                             description=source["description"], original_instruction=source["original_instruction"],
                             fields=tuple(fields))


def library_keys(case: dict, spec: dict) -> list[str]:
    order = spec["category_order"]

    def following(category: str, count: int, exclude: set[str]) -> list[str]:
        start = order.index(category)
        result = []
        for step in range(1, len(order)):
            candidate = order[(start + step) % len(order)]
            if candidate not in exclude and candidate not in result:
                result.append(candidate)
            if len(result) == count:
                return result
        raise ValueError("Not enough distractor categories")

    scenario, category = case.get("scenario"), case["category"]
    if scenario == "equal_profiles":
        keys = [category, f"{category}_twin"] + following(category, 1, {category})
    elif scenario == "no_suitable_profile":
        keys = following(category, 3, {category})
    elif scenario in ("mixed_image_set", "mixed_pdf"):
        first, second = (page["category"] for page in case["pages"])
        keys = [first, second] + following(second, 1, {first, second})
    else:
        keys = [category] + following(category, 2, {category})
    return sorted(keys, key=lambda key: sha256_text(f"{case['id']}/{key}"))


def row_layout(case: dict) -> list[list[tuple[int, dict, str]]]:
    """Per page: (row index, printed cells, part) where part is full, head or tail."""
    pages: list[list[tuple[int, dict, str]]] = [[] for _ in case["pages"]]
    rows = case.get("rows", [])
    counts = case.get("rows_per_page", [len(rows)] + [0] * (len(case["pages"]) - 1))
    split = case.get("split_row")
    index = 0
    for page_index, count in enumerate(counts):
        for _ in range(count):
            cells = rows[index]
            if split and split["row"] == index + 1 and page_index + 1 < len(pages):
                tail = {key: value for key, value in cells.items() if key in split["continued"]}
                head = {key: value for key, value in cells.items() if key not in split["continued"]}
                pages[page_index].append((index, head, "head"))
                pages[page_index + 1].append((index, tail, "tail"))
            else:
                pages[page_index].append((index, cells, "full"))
            index += 1
    if index != len(rows):
        raise ValueError(f"{case['id']}: rows_per_page does not place every row")
    for page in pages:
        page.sort(key=lambda item: (item[0], item[2] != "tail"))
    return pages


def expected_outcome(case: dict, spec: dict) -> ExpectedOutcome:
    scenario = case.get("scenario")
    if scenario in REFUSALS:
        return ExpectedOutcome(matching=REFUSALS[scenario], outcome="refused")
    profile = spec["profiles"][case["category"]]
    fields, lists = [], []
    for field in profile["fields"]:
        if "columns" in field:
            placed: dict[int, dict[str, int]] = {}
            for page_id, page_rows in enumerate(row_layout(case), start=1):
                for index, cells, _ in page_rows:
                    for key in cells:
                        placed.setdefault(index, {})[key] = page_id
            rows = []
            for index, cells in enumerate(case.get("rows", [])):
                row_pages = tuple(sorted(set(placed[index].values())))
                rows.append(ExpectedRow(source_key=f"row-{index + 1}", source_pages=row_pages, cells=tuple(
                    ExpectedValue(field_id=column["id"], status="extracted", present=True, value=cells[column["id"]],
                                  source_pages=(placed[index][column["id"]],)) for column in field["columns"])))
            lists.append(ExpectedList(field_id=field["id"], status="complete", enumeration_complete=True,
                                      rows=tuple(rows)))
            continue
        printed = [(page_id, page_fields(page)[field["id"]]) for page_id, page in enumerate(case["pages"], start=1)
                   if field["id"] in page_fields(page)]
        pages = tuple(page_id for page_id, _ in printed)
        if not printed:
            if field["id"] not in case.get("absent", []):
                raise ValueError(f"{case['id']}: profile field {field['id']} is neither printed nor declared absent")
            fields.append(ExpectedValue(field_id=field["id"], status="missing", present=False))
        elif len({value for _, value in printed}) > 1:
            fields.append(ExpectedValue(field_id=field["id"], status="ambiguous", present=True, source_pages=pages))
        else:
            fields.append(ExpectedValue(field_id=field["id"], status="extracted", present=True, value=printed[0][1],
                                        source_pages=pages))
    complete = all(value.status in ("extracted", "missing") for value in fields)
    return ExpectedOutcome(matching="matched", profile_id=profile["id"], outcome="complete" if complete else "partial",
                           fields=tuple(fields), lists=tuple(lists))


def artifact_specs(case: dict) -> list[tuple[str, str, str]]:
    """Generated files as (artifact ID, relative path, kind); inputs listed first."""
    identity, pages = case["id"], len(case["pages"])
    folder = f"{identity}/{identity}"
    specs: list[tuple[str, str, str]] = []
    if case["delivery"] == "pdf":
        specs.append(("pdf", f"{folder}.pdf", "pdf"))
        specs += [(f"original-{n}", f"{folder}-p{n:02}-original.png", "original") for n in range(1, pages + 1)]
    elif case["quality"] == "difficult" or case["delivery"] == "photo":
        specs.append(("original-1", f"{folder}-original.png", "original"))
    else:
        specs += [(f"page-{n}", f"{folder}-p{n:02}.png", "image_file") for n in range(1, pages + 1)]
        if case.get("scenario") == "illegible":
            specs.append(("original-1", f"{folder}-original.png", "original"))
    specs.append(("reference", f"{folder}-reference.png", "reference"))
    return specs


def scenario_name(case: dict, expected: ExpectedOutcome) -> str:
    if case["quality"] == "negative":
        return case["scenario"]
    if case["quality"] == "difficult":
        return f"physical_{case['condition']}"
    if case["delivery"] == "photo":
        return f"telegram_photo_{case['telegram']}"
    if case["delivery"] == "pdf":
        rows = [row for value in expected.lists for row in value.rows]
        if any(len(row.source_pages) > 1 for row in rows):
            return "multipage_pdf_record_split_across_boundary"
        if len({page for row in rows for page in row.source_pages}) > 1:
            return "multipage_pdf_list_across_boundary"
        return "multipage_pdf" if len(case["pages"]) > 1 else "single_page_pdf"
    return "two_sided_card" if len(case["pages"]) == 2 and case["layout"] == "card" else "single_page_image_file"


def pending_input(case: dict, printable_page: int | None) -> benchmark.PendingInput | None:
    if case["quality"] == "difficult":
        source = case["capture"]
        condition = CONDITION_TEXT[case["condition"]].format(side=case.get("crop_side", ""))
        start = f"Print page {printable_page} of printable-originals.pdf on A4 at 100% scale. {condition} "
        if source == "camera":
            finish = (f"Photograph it with the phone camera and copy the original camera file, not a messenger copy, "
                      f"to inbox/camera/{case['id']}.jpg.")
        else:
            finish = (f"Photograph it with the phone camera, send the photo through Telegram as a compressed photo "
                      f"with HD {'on' if case['telegram'] == 'hd' else 'off'}, and save the received photo to "
                      f"inbox/telegram/{case['id']}.jpg.")
        return benchmark.PendingInput(artifact_id=f"{source}-photo", source=source,
                                      telegram_quality=case.get("telegram") if source == "telegram" else None,
                                      condition=case["condition"], instruction=start + finish)
    if case["delivery"] == "photo":
        return benchmark.PendingInput(
            artifact_id="telegram-photo", source="telegram", telegram_quality=case["telegram"],
            instruction=(f"Send {case['id']}/{case['id']}-original.png through Telegram as a compressed photo with HD "
                         f"{'on' if case['telegram'] == 'hd' else 'off'} (not as a file), and save the received photo "
                         f"to inbox/telegram/{case['id']}.jpg."))
    return None


def planned_case(case: dict, spec: dict, digest: Callable[[str], str], printable_page: int | None) -> benchmark.PlannedCase:
    files = artifact_specs(case)
    artifacts = tuple(Artifact(id=identity, path=path, sha256=digest(path), kind=kind) for identity, path, kind in files)
    pending = pending_input(case, printable_page)
    inputs = (pending.artifact_id,) if pending else tuple(a.id for a in artifacts if a.kind == case["delivery"])
    originals = [a.sha256 for a in artifacts if a.kind in ("original", "image_file")]
    expected = expected_outcome(case, spec)
    origin = Origin(family_id=case["id"], kind="synthetic", permission_basis=PERMISSION,
                    original_sha256=originals[0], ancestor_sha256=tuple(originals[1:]))
    return benchmark.PlannedCase(
        case_id=case["id"], origin=origin, script=case["script"], language=case["language"],
        category=case["category"], quality=case["quality"], scenario=scenario_name(case, expected),
        delivery_path=case["delivery"], artifacts=artifacts, input_artifact_ids=inputs,
        page_ids=tuple(range(1, len(case["pages"]) + 1)),
        profiles=tuple(build_profile(spec, key) for key in library_keys(case, spec)), expected=expected,
        pending=pending, layout=case["layout"], table_style=case.get("table"), printable_page=printable_page)


def printable_pages(spec: dict) -> dict[str, int]:
    difficult = [case["id"] for case in spec["cases"] if case["quality"] == "difficult"]
    return {identity: index for index, identity in enumerate(difficult, start=1)}


def build_plan(spec: dict, digest: Callable[[str], str], reproducibility: dict[str, str]) -> benchmark.BenchmarkPlan:
    pages = printable_pages(spec)
    shared = (Artifact(id="printable-originals", path="printable-originals.pdf",
                       sha256=digest("printable-originals.pdf"), kind="original"),)
    return benchmark.BenchmarkPlan(schema_version=1, shared_artifacts=shared, reproducibility=reproducibility,
                                   cases=tuple(planned_case(case, spec, digest, pages.get(case["id"]))
                                               for case in spec["cases"]))


# ---------------------------------------------------------------- rendering

@functools.lru_cache(maxsize=512)
def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)


def fit(draw: ImageDraw.ImageDraw, value: str, font_path: Path, size: int, width: int, direction: str) -> tuple[int, int]:
    """Largest size <= `size` (step 2, minimum 20) whose ink box fits, as development.text does."""
    while size >= 20:
        box = draw.textbbox((0, 0), value, font=_font(str(font_path), size), direction=direction)
        if box[2] - box[0] <= width:
            return size, box[2] - box[0]
        size -= 2
    raise ValueError("Text does not fit at the minimum font size")


class Page:
    """One rendered page; x coordinates are logical (start to end) and mirrored for RTL."""

    def __init__(self, size: tuple[int, int], paper: str, rtl: bool, font: Path, arial: Path, accent: str):
        self.image = Image.new("RGB", size, paper)
        self.draw = ImageDraw.Draw(self.image)
        self.width, self.height = size
        self.rtl, self.font, self.arial, self.accent = rtl, font, arial, accent
        self.annotations: list[dict] = []

    def span(self, x0: float, x1: float) -> tuple[int, int]:
        return (round(self.width - x1), round(self.width - x0)) if self.rtl else (round(x0), round(x1))

    def rect(self, x0: float, y0: float, x1: float, y1: float, **style) -> None:
        a, b = self.span(x0, x1)
        self.draw.rectangle((a, round(y0), b, round(y1)), **style)

    def line(self, x0: float, y: float, x1: float, *, fill: str = "#9aa7b0", width: int = 2, dash: int = 0) -> None:
        a, b = self.span(x0, x1)
        if not dash:
            self.draw.line((a, round(y), b, round(y)), fill=fill, width=width)
            return
        for start in range(a, b, dash * 2):
            self.draw.line((start, round(y), min(b, start + dash), round(y)), fill=fill, width=width)

    def write(self, value: str, x0: float, x1: float, y: float, size: int, *, color: str = INK,
              align: str = "start", latin: bool = False, key: str | None = None) -> list[int]:
        a, b = self.span(x0, x1)
        font = self.arial if latin else self.font
        direction = "rtl" if self.rtl and not latin else "ltr"
        size, width = fit(self.draw, value, font, size, b - a, direction)
        if align == "center":
            left = a + (b - a - width) // 2
        elif (align == "start") != self.rtl:
            left = a
        else:
            left = b - width
        box = development.text(self.draw, value, (left, round(y)), font, size, width + 1, direction=direction, color=color)
        if key is not None:
            self.annotations.append({"field": key, "value": value, "bbox_px": box})
        return box


def render_case(case: dict, spec: dict, fonts: dict[str, Path], *,
                degrade_illegible: bool = True) -> list[tuple[Image.Image, list[dict]]]:
    """Pages with value annotations; the illegible negative is degraded unless a clean reference is wanted."""
    scenario = case.get("scenario")
    if scenario == "blank":
        return [(Image.new("RGB", A4, "white"), [])]
    if scenario == "not_document":
        return [(abstract_image(case["id"]), [])]
    row_pages = row_layout(case)
    result = []
    for index, page_spec in enumerate(case["pages"]):
        page = render_page(case, spec, fonts, index, page_spec, row_pages[index])
        if scenario == "illegible" and degrade_illegible:
            degrade(page)
        result.append((page.image, page.annotations))
    return result


def render_page(case: dict, spec: dict, fonts: dict[str, Path], index: int, page_spec: dict,
                rows: list[tuple[int, dict, str]]) -> Page:
    language = spec["languages"][case["language"]]
    category = page_spec.get("category", case["category"])
    layout = case["layout"]
    size = CARD if layout == "card" else RECEIPT if layout == "receipt" else A4
    page = Page(size, case.get("paper", "white"), case["script"] == "Arabic", fonts[case["font"]],
                fonts["arial.ttf"], case.get("accent", "#1f4e79"))
    value_size, label_size = case.get("value_size", 64), case.get("label_size", 38)
    margin = 120 if size != A4 else 200
    title = language["titles"][category]
    y = header(page, layout, case.get("header", "rule"), title, margin, page_spec.get("side"))
    fields = [(key, language["labels"][key], value) for key, value in page_spec.get("fields", {}).items()]
    photo_side = layout == "card" and page_spec.get("side") != "back"
    y = scalars(page, layout, fields, margin, y, value_size, label_size, start=margin + 540 if photo_side else margin)
    list_id = list_field_id(spec, category)
    page_rows = page_spec.get("rows")
    if page_rows is not None:
        rows = [(row_index, cells, "full") for row_index, cells in enumerate(page_rows)]
    if rows and list_id:
        columns = case.get("columns") or [column["id"] for column in
                                           next(f for f in spec["profiles"][category]["fields"] if f["id"] == list_id)["columns"]]
        y = table(page, case.get("table", "ruled"), list_id, language, columns, rows, margin, y + 40,
                  min(value_size, 58), label_size, continued=index > 0)
    trailing = [(key, language["labels"][key], value) for key, value in page_spec.get("after_rows", {}).items()]
    if trailing:
        y = scalars(page, "inline", trailing, margin, y + 60, value_size, label_size)
    if layout == "letter":
        for line in language["letter_body"]:
            y += 30
            page.write(line, margin, page.width - margin, y, max(label_size, 40))
            y += max(label_size, 40) * 1.6
    if case.get("printed_instruction"):
        top = y + 60
        lines = case["printed_instruction"]
        page.rect(margin, top, page.width - margin, top + 60 + len(lines) * 72, outline="#8a2b2b", width=4)
        for number, line in enumerate(lines):
            page.write(line, margin + 40, page.width - margin - 40, top + 40 + number * 72, 44)
        y = top + 60 + len(lines) * 72
    footer(page, margin, index, len(case["pages"]))
    if y > page.height - 230:
        raise ValueError(f"{case['id']}: content overflows page {index + 1}")
    for annotation in page.annotations:
        x0, y0, x1, y1 = annotation["bbox_px"]
        if not (0 <= x0 < x1 <= page.width and 0 <= y0 < y1 < page.height - 190):
            raise ValueError(f"{case['id']}: clipped value {annotation['field']}")
    return page


def header(page: Page, layout: str, style: str, title: str, margin: int, side: str | None) -> float:
    width, accent = page.width, page.accent
    if layout == "card":
        page.draw.rounded_rectangle((30, 30, width - 30, page.height - 30), radius=60, outline=accent, width=6)
        page.draw.rounded_rectangle((30, 30, width - 30, 250), radius=60, fill=accent)
        page.draw.rectangle((30, 150, width - 30, 250), fill=accent)
        page.write(title, margin, width - margin, 110, 76, color="white")
        if side == "back":
            page.draw.rectangle((30, 290, width - 30, 420), fill="#2b2b2b")
            return 480
        page.rect(margin, 330, margin + 480, 950, fill="#d9dde1", outline="#9aa5ad", width=4)
        start = margin + 480
        cx = (page.span(margin, start)[0] + page.span(margin, start)[1]) // 2
        page.draw.ellipse((cx - 110, 440, cx + 110, 660), fill="#aab3ba")
        page.draw.rounded_rectangle((cx - 190, 700, cx + 190, 950), radius=90, fill="#aab3ba")
        return 330
    if layout == "receipt":
        page.write(title, margin, width - margin, 170, 64, align="center")
        page.line(margin, 290, width - margin, fill=INK, width=3, dash=18)
        return 350
    if layout == "certificate":
        page.draw.rectangle((90, 90, width - 90, page.height - 230), outline=accent, width=10)
        page.draw.rectangle((125, 125, width - 125, page.height - 265), outline="#b89a4e", width=4)
        page.write(title, margin + 100, width - margin - 100, 380, 110, color=accent, align="center")
        return 700
    if layout == "letter":
        page.write(title, margin, width - margin, 200, 70, color=accent)
        page.line(margin, 330, width - margin, fill=accent, width=6)
        return 470
    if style == "band":
        page.draw.rectangle((0, 0, width, 360), fill=accent)
        page.write(title, margin, width - margin, 140, 86, color="white")
        return 500
    if style == "center":
        page.write(title, margin, width - margin, 200, 90, color=accent, align="center")
        page.line(margin, 360, width - margin, fill=accent, width=4)
        page.line(margin, 380, width - margin, fill=accent, width=2)
        return 500
    page.write(title, margin, width - margin, 200, 84, color=accent)
    page.line(margin, 340, width - margin, fill=accent, width=5)
    return 480


def scalars(page: Page, layout: str, fields: list[tuple[str, str, str]], margin: int, y: float,
            value_size: int, label_size: int, *, start: int | None = None) -> float:
    width, accent = page.width, page.accent
    if layout == "card":
        start = margin if start is None else start
        for key, label, value in fields:
            page.write(label, start, width - margin, y, label_size, color=accent)
            page.write(value, start, width - margin, y + label_size * 1.45, value_size, key=key)
            y += label_size * 1.45 + value_size * 1.35 + 60
        return y
    if layout == "certificate":
        for key, label, value in fields:
            page.write(label, margin + 100, width - margin - 100, y, label_size, color=accent, align="center")
            page.write(value, margin + 100, width - margin - 100, y + label_size * 1.5, value_size, align="center", key=key)
            y += label_size * 1.5 + value_size * 1.4 + 110
        return y
    if layout == "receipt":
        for key, label, value in fields:
            page.write(label, margin, width * 0.5, y, label_size)
            page.write(value, width * 0.42, width - margin, y + label_size * 1.3, value_size, align="end", key=key)
            y += label_size * 1.3 + value_size * 1.35 + 30
            page.line(margin, y, width - margin, fill="#8f8f8f", width=2, dash=12)
            y += 40
        return y
    if layout in ("inline", "letter"):
        label_width = (width - 2 * margin) * (0.3 if layout == "letter" else 0.36)
        for key, label, value in fields:
            row = max(value_size, label_size) * 1.5
            page.write(label + (":" if layout == "letter" else ""), margin, margin + label_width,
                       y + (value_size - label_size) * 0.5, label_size, color=accent)
            page.write(value, margin + label_width + 40, width - margin, y, value_size, key=key)
            if layout == "inline":
                page.line(margin, y + row, width - margin, fill="#c5ced4")
            y += row + 50
        return y
    if layout == "two_column":
        column = (width - 2 * margin - 80) / 2
        for number, (key, label, value) in enumerate(fields):
            x0 = margin + (number % 2) * (column + 80)
            page.write(label, x0, x0 + column, y, label_size, color=accent)
            page.write(value, x0, x0 + column, y + label_size * 1.45, value_size, key=key)
            page.line(x0, y + label_size * 1.45 + value_size * 1.4, x0 + column, fill="#c5ced4")
            if number % 2 or number == len(fields) - 1:
                y += label_size * 1.45 + value_size * 1.4 + 90
        return y
    if layout == "boxed_form":
        label_width, row = (width - 2 * margin) * 0.34, value_size * 2.1
        for key, label, value in fields:
            page.rect(margin, y, margin + label_width, y + row, fill="#eef1f4", outline="#6f7c85", width=3)
            page.rect(margin + label_width, y, width - margin, y + row, outline="#6f7c85", width=3)
            page.write(label, margin + 24, margin + label_width - 24, y + (row - label_size) / 2, label_size, color=accent)
            page.write(value, margin + label_width + 30, width - margin - 30, y + (row - value_size) / 2, value_size, key=key)
            y += row
        return y + 40
    for key, label, value in fields:  # stacked
        page.write(label, margin, width - margin, y, label_size, color=accent)
        page.write(value, margin, width - margin, y + label_size * 1.45, value_size, key=key)
        y += label_size * 1.45 + value_size * 1.35 + 70
    return y


def table(page: Page, style: str, list_id: str, language: dict, columns: list[str],
          rows: list[tuple[int, dict, str]], margin: int, y: float, value_size: int, label_size: int,
          *, continued: bool) -> float:
    width, accent, labels = page.width, page.accent, language["labels"]
    title = labels[list_id] + (f" {language['continued']}" if continued else "")
    page.write(title, margin, width - margin, y, label_size + 6, color=accent)
    y += (label_size + 6) * 1.8
    if style == "record_blocks":
        label_width = (width - 2 * margin) * 0.3
        page.line(margin, y - 20, width - margin, fill=accent, width=4)
        for index, cells, part in rows:
            for column in columns:
                if column not in cells:
                    continue
                page.write(labels[column] + ":", margin, margin + label_width, y + (value_size - label_size) * 0.5,
                           label_size, color=accent)
                page.write(cells[column], margin + label_width + 30, width - margin, y, value_size,
                           key=f"{list_id}[{index}].{column}")
                y += value_size * 1.55
            if part == "head":
                page.write(language["continues"], margin, width - margin, y + 20, label_size, color=accent, align="end")
                y += label_size * 2
            else:
                page.line(margin, y + 10, width - margin, fill="#8d99a3", width=3)
                y += 50
        return y
    weights = [3.0 if column in TEXT_COLUMNS else 1.3 for column in columns]
    edges = [margin]
    for weight in weights:
        edges.append(edges[-1] + (width - 2 * margin) * weight / sum(weights))
    head, row_height = label_size * 2.4, value_size * 2.2
    for number, column in enumerate(columns):
        x0, x1 = edges[number], edges[number + 1]
        if style == "banded":
            page.rect(x0, y, x1, y + head, fill=accent)
        elif style == "boxed_table":
            page.rect(x0, y, x1, y + head, fill="#e4e7ea", outline="#4d5a63", width=4)
        page.write(labels[column], x0 + 22, x1 - 22, y + (head - label_size) / 2, label_size,
                   color="white" if style == "banded" else accent)
    y += head
    if style == "ruled":
        page.line(margin, y, width - margin, fill=accent, width=5)
    for position, (index, cells, _) in enumerate(rows):
        if style == "banded" and position % 2:
            page.rect(margin, y, width - margin, y + row_height, fill="#edf2f6")
        for number, column in enumerate(columns):
            x0, x1 = edges[number], edges[number + 1]
            if style == "boxed_table":
                page.rect(x0, y, x1, y + row_height, outline="#4d5a63", width=3)
            page.write(cells[column], x0 + 22, x1 - 22, y + (row_height - value_size) / 2, value_size,
                       align="end" if column not in TEXT_COLUMNS else "start", key=f"{list_id}[{index}].{column}")
        y += row_height
        if style == "ruled":
            page.line(margin, y, width - margin, fill="#b3bdc4")
    return y + 30


def footer(page: Page, margin: int, index: int, count: int) -> None:
    page.write(FOOTER, margin, page.width - margin - (160 if count > 1 else 0), page.height - 150, 30,
               color=page.accent, latin=True)
    if count > 1:
        page.write(f"{index + 1} / {count}", page.width - margin - 140, page.width - margin, page.height - 150, 34,
                   latin=True, align="end")


def degrade(page: Page) -> None:
    """Illegible negative: mosaic plus blur so no glyph survives; annotations stay for review."""
    small = page.image.resize((page.width // 22, page.height // 22), Image.Resampling.BILINEAR)
    page.image = small.resize((page.width, page.height), Image.Resampling.NEAREST).filter(ImageFilter.GaussianBlur(6))


def abstract_image(identity: str) -> Image.Image:
    """Deterministic abstract composition without any text."""
    image = Image.new("RGB", A4, "#f4efe6")
    draw = ImageDraw.Draw(image)
    seed = hashlib.sha256(identity.encode()).digest()
    palette = ["#d2553f", "#2f7f8f", "#f2b134", "#5a4e8c", "#88b04b", "#1f3b57"]
    for band in range(14):
        draw.rectangle((0, band * 250, A4[0], band * 250 + 120), fill=palette[seed[band] % len(palette)])
    for number in range(9):
        x, y, radius = 200 + seed[number] * 8, 300 + seed[number + 9] * 11, 150 + seed[number + 18]
        draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=palette[number % len(palette)],
                     outline="#ffffff", width=12)
    draw.polygon([(300, 3200), (1240, 2300), (2200, 3300)], fill="#1f3b57")
    return image


def write_pdf(path: Path, images: list[Image.Image], *, password: str | None = None) -> None:
    encryption = StandardEncryption(password, ownerPassword=password, canPrint=1, strength=128) if password else None
    canvas = Canvas(str(path), pagesize=PDF_PAGE, invariant=1, pageCompression=1, encrypt=encryption)
    canvas.setTitle("Synthetic benchmark document")
    canvas.setAuthor("Synthetic benchmark generator")
    for image in images:
        scale = min(PDF_PAGE[0] / image.width, PDF_PAGE[1] / image.height)
        width, height = image.width * scale, image.height * scale
        canvas.drawImage(ImageReader(image), (PDF_PAGE[0] - width) / 2, (PDF_PAGE[1] - height) / 2,
                         width=width, height=height)
        canvas.showPage()
    canvas.save()


def write_printable(path: Path, originals: list[tuple[str, int, Image.Image]]) -> None:
    """One difficult original per A4 page; the case label sits in the margin outside the document."""
    canvas = Canvas(str(path), pagesize=PDF_PAGE, invariant=1, pageCompression=1)
    canvas.setTitle("Benchmark printable originals")
    canvas.setAuthor("Synthetic benchmark generator")
    for identity, number, image in originals:
        box_width, box_height = PDF_PAGE[0] - 72, PDF_PAGE[1] - 110
        if image.width > image.height:
            box_width = min(box_width, 400)
        scale = min(box_width / image.width, box_height / image.height)
        width, height = image.width * scale, image.height * scale
        x, y = (PDF_PAGE[0] - width) / 2, 60 + (box_height - height) / 2
        canvas.drawImage(ImageReader(image), x, y, width=width, height=height)
        canvas.setStrokeColorRGB(0.75, 0.75, 0.75)
        canvas.rect(x, y, width, height)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(36, 26, f"{identity} | print page {number} of {len(originals)} | A4 at 100% scale | "
                                  "keep this label outside the photo")
        canvas.showPage()
    canvas.save()


def save_png(image: Image.Image, path: Path) -> None:
    image.save(path, compress_level=6)


def render_files(case: dict, spec: dict, fonts: dict[str, Path], output: Path) -> Image.Image:
    """Write every generated file of one case; return the original to print for difficult cases."""
    pages = render_case(case, spec, fonts)
    identity = case["id"]
    folder = output / identity
    folder.mkdir()
    if case.get("scenario") == "illegible":
        clean = render_case(case, spec, fonts, degrade_illegible=False)
        save_png(clean[0][0], folder / f"{identity}-original.png")
        review_pages = clean
    else:
        review_pages = pages
    if case["delivery"] == "pdf":
        write_pdf(folder / f"{identity}.pdf", [image for image, _ in pages],
                  password=REVIEW_PASSWORD if case.get("scenario") == "protected_pdf" else None)
        for number, (image, _) in enumerate(pages, start=1):
            save_png(image, folder / f"{identity}-p{number:02}-original.png")
    elif case["quality"] == "difficult" or case["delivery"] == "photo":
        save_png(pages[0][0], folder / f"{identity}-original.png")
    else:
        for number, (image, _) in enumerate(pages, start=1):
            save_png(image, folder / f"{identity}-p{number:02}.png")
    sheet_case = {"id": identity, "script": case["script"], "font": case["font"],
                  "direction": "rtl" if case["script"] == "Arabic" else "ltr"}
    development.review_sheet(folder / f"{identity}-reference.png", sheet_case, review_pages, fonts)
    expected = {path for _, path, _ in artifact_specs(case)}
    written = {path.relative_to(output).as_posix() for path in folder.iterdir()}
    if written != expected:
        raise ValueError(f"{identity}: generated files differ from the planned artifacts")
    return pages[0][0]


def verify_pdfs(output: Path, plan: benchmark.BenchmarkPlan) -> None:
    for case in plan.cases:
        for artifact in case.artifacts:
            if artifact.kind != "pdf":
                continue
            path = output / artifact.path
            if case.scenario == "protected_pdf":
                try:
                    pdfium.PdfDocument(str(path)).close()
                except pdfium.PdfiumError:
                    continue
                raise ValueError(f"{case.case_id}: protected PDF opened without a password")
            with pdfium.PdfDocument(str(path)) as document:
                if len(document) != len(case.page_ids):
                    raise ValueError(f"{case.case_id}: unexpected PDF page count")


# ---------------------------------------------------------------- documents for the human

def capture_instructions(plan: benchmark.BenchmarkPlan) -> str:
    esc = html.escape
    rows = []
    for case in plan.cases:
        if case.pending is None:
            continue
        pending = case.pending
        rows.append(
            f"<tr><td>{esc(case.case_id)}</td><td>{esc(case.quality)}</td>"
            f"<td>{esc(pending.condition or 'none (clean digital original)')}</td>"
            f"<td>{esc(case.delivery_path)}</td><td>{esc(pending.telegram_quality or 'not applicable')}</td>"
            f"<td><code>inbox/{esc(pending.inbox_name(case.case_id))}</code></td><td>{esc(pending.instruction)}</td></tr>")
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<title>T01c benchmark capture instructions</title>
<style>body{{font:17px system-ui,sans-serif;max-width:1500px;margin:24px auto;padding:0 20px;color:#17242d}}
header{{background:#fff1ca;padding:18px 22px}}table{{border-collapse:collapse;width:100%;margin:20px 0}}
td,th{{border:1px solid #bbcbd2;padding:8px;text-align:left;vertical-align:top}}th{{background:#eef3f5}}
code{{background:#f2f4f5;padding:1px 4px}}</style>
<header><h1>T01c benchmark capture instructions</h1>
<p><strong>No model run may touch these cases before the benchmark is sealed.</strong> Human review is pending for every case.</p>
<ol><li>Print <code>printable-originals.pdf</code> on A4 at 100% scale. Each page carries a small case label in the margin; keep it outside the photo.</li>
<li>For each row below, reproduce the condition exactly once and save exactly one JPEG at the destination path, inside the <code>inbox</code> folder next to <code>plan.json</code>.</li>
<li>Camera rows: copy the original file from the phone (USB or cloud export of the original); never a messenger copy. It must be JPEG and larger than 2,560 px on the longer side.</li>
<li>Telegram rows: send the image to a private test chat (for example, Saved Messages) as a <em>photo</em>, not as a file. Enable HD only where the row says <code>hd</code>. Open the received photo in Telegram Desktop and save it (Save image as). Standard photos are at most 1,280 px on the longer side; HD photos are larger than 1,280 and at most 2,560 px.</li>
<li>Turn off camera location tagging or remove location metadata; ingest refuses files that contain GPS data.</li>
<li>Then run <code>python -m tgbotdocs.recognition.benchmark ingest</code> as described in tools/t01/README-benchmark.md.</li></ol></header>
<p>{len(rows)} captures: every difficult case and every readable photo-path case. All other inputs are already generated.</p>
<table><tr><th>Case</th><th>Quality</th><th>Condition</th><th>Delivery path</th><th>Telegram quality</th><th>Destination</th><th>Instruction</th></tr>
{''.join(rows)}
</table></html>
"""


def readme(plan: benchmark.BenchmarkPlan) -> str:
    counts = {quality: sum(case.quality == quality for case in plan.cases) for quality in ("readable", "difficult", "negative")}
    captures = sum(case.pending is not None for case in plan.cases)
    return f"""# T01c sealed benchmark preparation package

Generated by `tools/t01/create_benchmark_set.py`. Synthetic content only; fictional people and organizations.

- Cases: {len(plan.cases)} ({counts['readable']} readable, {counts['difficult']} difficult, {counts['negative']} negative).
- `plan.json`: the machine-readable plan (`BenchmarkPlan`), with hashes of every generated file.
- `printable-originals.pdf`: originals of the difficult cases to print and photograph.
- `capture-instructions.html`: the {captures} human captures to place under `inbox/camera/` or `inbox/telegram/`.
- `<case>/`: generated inputs, originals and `<case>-reference.png` review sheets.

Human review is pending for every case. No model run may touch these cases before sealing.
The protected PDF opens with the non-secret review password `{REVIEW_PASSWORD}`; it is never supplied at runtime.
Follow `tools/t01/README-benchmark.md` for capture, ingest, review, apply and sealing.
"""


def reproducibility(spec_path: Path, fonts: dict[str, Path]) -> dict[str, str]:
    values = {"generator_sha256": development.sha256(Path(__file__)), "spec_sha256": development.sha256(spec_path),
              "development_helpers_sha256": development.sha256(Path(development.__file__)),
              "benchmark_module_sha256": development.sha256(Path(benchmark.__file__)),
              "python": platform.python_version(), "raqm": str(features.version_feature("raqm")),
              "randomness": "none; fixed layouts; ReportLab invariant=1"}
    values.update({f"package:{name}": importlib.metadata.version(name)
                   for name in ("Pillow", "reportlab", "pypdfium2", "pydantic")})
    values.update({f"font:{name}": development.sha256(path) for name, path in sorted(fonts.items())})
    return values


def generate(spec: dict, fonts: dict[str, Path], output: Path, spec_path: Path) -> benchmark.BenchmarkPlan:
    printable = []
    pages = printable_pages(spec)
    for case in spec["cases"]:
        original = render_files(case, spec, fonts, output)
        if case["id"] in pages:
            printable.append((case["id"], pages[case["id"]], original))
    write_printable(output / "printable-originals.pdf", printable)
    plan = build_plan(spec, lambda path: development.sha256(output / path), reproducibility(spec_path, fonts))
    problems = benchmark.composition_problems(plan)
    if problems:
        raise ValueError(f"Benchmark composition incomplete: {', '.join(problems)}")
    verify_pdfs(output, plan)
    (output / "inbox" / "camera").mkdir(parents=True)
    (output / "inbox" / "telegram").mkdir(parents=True)
    (output / "capture-instructions.html").write_text(capture_instructions(plan), encoding="utf-8")
    (output / "README.md").write_text(readme(plan), encoding="utf-8")
    (output / "plan.json").write_bytes(benchmark.canonical_json_bytes(plan.model_dump(mode="json")))
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", required=True, type=Path,
                        help="Absolute, empty or nonexistent directory outside every Git checkout")
    parser.add_argument("--cases", type=Path, default=HERE / "benchmark-cases.json")
    parser.add_argument("--fonts-dir", type=Path, default=Path("C:/Windows/Fonts"))
    args = parser.parse_args()
    if not args.output.is_absolute():
        parser.error("--output must be an absolute path")
    output = args.output.resolve()
    if any((ancestor / ".git").exists() for ancestor in (output, *output.parents)):
        parser.error("--output must be outside every Git checkout")
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error("--output must be an empty or nonexistent directory; existing assets are never overwritten")
    spec, fonts = load_spec(args.cases, args.fonts_dir)
    check_independence(spec, earlier_specs())
    output.mkdir(parents=True, exist_ok=True)
    plan = generate(spec, fonts, output, args.cases)
    print(f"Generated {len(plan.cases)} benchmark cases; "
          f"{sum(case.pending is not None for case in plan.cases)} human captures pending; human review pending.")
    print(f"plan.json sha256 {development.sha256(output / 'plan.json')}")


if __name__ == "__main__":
    main()
