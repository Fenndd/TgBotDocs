"""English plain-text output with explicit UTF-16 code entities."""

from dataclasses import dataclass

from aiogram.types import MessageEntity


class RenderingError(ValueError):
    pass


def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


@dataclass(frozen=True, repr=False)
class MessagePart:
    text: str
    entities: tuple[MessageEntity, ...] = ()


LABELS = {"missing": "Missing", "unreadable": "Unreadable", "ambiguous": "Ambiguous",
          "invalid": "Unreadable (did not pass the format check)"}


def _value(field):
    if field.status == "extracted":
        value = field.accepted_value
        return ("true" if value else "false") if isinstance(value, bool) else str(value), True
    return LABELS[field.status], False


def _list_status(listing):
    """An unresolved list shows its reason with the REQ-022 labels (CONTRACTS)."""
    if listing.status == "unresolved":
        return LABELS[listing.reason]
    return listing.status.title()


def _absent(result):
    """Every requested item is justified missing: nothing requested is in the document."""
    return all(field.status == "missing" for field in result.fields) and all(
        listing.status == "unresolved" and listing.reason == "missing" for listing in result.lists)


def render_result(profile, result, *, compressed=False, note=None):
    """Split at scalar/row boundaries, never truncate or reveal invalid candidates.

    ``note`` is an application line such as the profile used; never document text.
    """
    units = []

    def unit(label, value, accepted):
        text = label + ": " + value
        entity = MessageEntity(type="code", offset=utf16_length(label + ": "), length=utf16_length(value))
        if utf16_length(text) > 4000:
            raise RenderingError("result_value_or_row_exceeds_telegram_limit")
        return MessagePart(text, (entity,) if accepted else ())

    definitions = {x.id: x for x in profile.fields}
    for field in result.fields:
        units.append(unit(definitions[field.field_id].label, *_value(field)))
    for listing in result.lists:
        definition = definitions[listing.field_id]
        units.append(MessagePart(f"{definition.label}: {_list_status(listing)}"))
        columns = {x.id: x for x in definition.columns}
        for index, row in enumerate(listing.rows, 1):
            text, entities = f"Row {index}\n", []
            for cell in row.cells:
                part = unit(columns[cell.field_id].label, *_value(cell))
                offset = utf16_length(text)
                entities.extend(e.model_copy(update={"offset": e.offset + offset}) for e in part.entities)
                text += part.text + "\n"
            if utf16_length(text) > 4000:
                raise RenderingError("result_value_or_row_exceeds_telegram_limit")
            units.append(MessagePart(text.rstrip(), tuple(entities)))
    title = "Result: " + result.outcome.title()
    if result.outcome == "failed":
        title += ("\nNone of the requested data is present in the document." if _absent(result)
                  else "\nNone of the requested data could be reliably extracted.")
    if note:
        title += "\n" + note
    if compressed and result.outcome != "complete":
        units.append(MessagePart("For better quality, resend the document as a file."))
    chunks, text, entities = [], title, []
    for part in units:
        if utf16_length(text + "\n" + part.text) > 4000:
            chunks.append(MessagePart(text, tuple(entities)))
            text, entities = "", []
        prefix = "\n" if text else ""
        offset = utf16_length(text + prefix)
        entities.extend(e.model_copy(update={"offset": e.offset + offset}) for e in part.entities)
        text += prefix + part.text
    chunks.append(MessagePart(text, tuple(entities)))
    if len(chunks) == 1:
        return tuple(chunks)
    numbered = []
    for index, part in enumerate(chunks, 1):
        prefix = f"Part {index}/{len(chunks)} (partial until all parts arrive)\n"
        if utf16_length(prefix + part.text) > 4096:
            raise RenderingError("result_message_exceeds_telegram_limit")
        numbered.append(MessagePart(prefix + part.text, tuple(
            e.model_copy(update={"offset": e.offset + utf16_length(prefix)}) for e in part.entities)))
    return tuple(numbered)
