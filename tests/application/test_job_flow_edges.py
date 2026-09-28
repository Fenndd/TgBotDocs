"""T06 edge cases from the independent review: deferral, cancellation races, turn
order, snapshots, result shapes and two-user isolation. Uses the test_job_flow harness."""

import asyncio
from uuid import uuid4

from test_job_flow import Harness, matching, profile, recognized

from tgbotdocs.application.compiler import CompileResult
from tgbotdocs.application.events import ButtonClick, Event
from tgbotdocs.application.pipeline import PhaseOutcome
from tgbotdocs.application.rendering import render_result
from tgbotdocs.application.transport import Upload
from tgbotdocs.recognition.contracts import (ExtractionProfile, FieldResult, ListField, ListResult, ListRow,
                                             MatchingResponse, RecognitionResult, ScalarField)
from tgbotdocs.recognition.core import CoreResult


def table_profile():
    field = ListField(id="rows", label="Rows", description="Rows", columns=(
        ScalarField(id="value", label="Value", description="Value", type="text"),))
    return ExtractionProfile(id=str(uuid4()), owner="1", version=1, name="Table", description="Table",
                             original_instruction="Rows", fields=(field,))


async def test_deferred_confirmation_preview_lives_from_its_display():
    h = Harness()
    try:
        await h.sign_in()
        h.recognition.results.append(matching("no_profile", "x"))
        await h.file("scan")
        gate = asyncio.Event()

        async def slow(owner, instruction, current):
            await gate.wait()
            return CompileResult(drafts=(profile(1, "Card"),))

        async def compile_later(owner, instruction, *, current=(), remaining_budget_s=300, charged=None, **kw):
            h.compiler.calls.append((instruction, current, remaining_budget_s))
            return await slow(owner, instruction, current)

        h.compiler.compile = compile_later
        h.app.submit(Event("text", 1, payload="Read the card ID"))
        await h.until(lambda: h.flow.jobs[1].state == "compiling")
        # While the job compiles, Settings is editable; the job's question is deferred.
        h.app.submit(Event("text", 1, payload="Settings"))
        await h.until(lambda: any(a == "create" for a, _ in h.app.settings.session(1).buttons.values()))
        create = next(t for t, (a, _) in h.app.settings.session(1).buttons.items() if a == "create")
        h.app.submit(Event("callback", 1, payload=ButtonClick(create, "c")))
        await h.until(lambda: h.app.settings.waiting(1))
        h.clock.now = 100
        gate.set()
        await h.settle()
        job = h.flow.jobs[1]
        assert job.state == "awaiting_confirmation" and job.deferred is not None
        h.clock.now = 950  # the Settings draft expires on this tick; the job question appears
        h.app.tick()
        await h.settle()
        assert job.deferred is None and "Review every profile" in h.texts()[-1]
        h.clock.now = 950 + 800
        h.recognition.results.append(recognized(job.preview.drafts[0], user_selected=True))
        await h.click("save")
        assert len(h.store.rows) == 1 and h.results() and not h.flow.jobs
    finally:
        await h.close()


async def test_cancel_during_delivery_withdraws_a_part_queued_behind_another_message():
    h = Harness()
    try:
        card = profile(1)
        h.store.rows[card.id] = card
        await h.sign_in()
        h.recognition.gate = asyncio.Event()
        h.recognition.results.append(recognized(card))
        h.app.submit(Event("file", 1, update_id=10, message_id=10, payload=Upload("scan", 1)))
        await h.until(lambda: h.flow.status(1) == "processing")
        held = asyncio.Event()
        original = h.transport.send

        async def slow(owner, text, **kwargs):
            if text.startswith("A document is active"):
                await held.wait()
            return await original(owner, text, **kwargs)

        h.transport.send = slow
        h.app.submit(Event("text", 1, payload="anything"))  # this reply holds the chat's turn
        await h.until(lambda: True)
        h.recognition.gate.set()
        await h.until(lambda: h.flow.jobs[1].state == "delivering")
        h.app.submit(Event("text", 1, payload="Cancel"))
        await h.until(lambda: h.flow.jobs[1].state == "finishing")
        held.set()
        await h.settle()
        assert not h.results() and not h.flow.jobs
    finally:
        await h.close()


def test_unresolved_lists_show_their_reason_and_failed_results_their_cause():
    field = ListField(id="rows", label="Rows", description="Rows", columns=(
        ScalarField(id="value", label="Value", description="Value", type="text"),))
    number = ScalarField(id="number", label="Number", description="Number", type="text")
    table = ExtractionProfile(id="p", owner="1", version=1, name="Table", description="Table",
                              original_instruction="Rows", fields=(number, field))
    read = FieldResult(field_id="number", status="extracted", raw_value="A1", source_pages=(1,))
    for reason, label in (("missing", "Missing"), ("unreadable", "Unreadable"), ("ambiguous", "Ambiguous"),
                          ("invalid", "Unreadable (did not pass the format check)")):
        listing = ListResult(field_id="rows", status="unresolved", reason=reason, enumeration_complete=True)
        text = render_result(table, RecognitionResult(fields=(read,), lists=(listing,), outcome="partial"))[0].text
        assert f"Rows: {label}" in text and "Unresolved" not in text
    missing = FieldResult(field_id="number", status="missing")
    absent = ListResult(field_id="rows", status="unresolved", reason="missing", enumeration_complete=True)
    text = render_result(table, RecognitionResult(fields=(missing,), lists=(absent,), outcome="failed"))[0].text
    assert "None of the requested data is present in the document." in text
    unreadable = FieldResult(field_id="number", status="unreadable")
    text = render_result(table, RecognitionResult(fields=(unreadable,), lists=(absent,), outcome="failed"))[0].text
    assert "could be reliably extracted" in text


async def test_cancel_in_each_waiting_state_discards_drafts_and_expires_old_buttons():
    h = Harness()
    try:
        card = profile(1)
        h.store.rows[card.id] = card
        await h.sign_in()
        for index, target in enumerate(("awaiting_choice", "awaiting_instruction", "awaiting_confirmation")):
            h.recognition.results.append(matching("uncertain" if target == "awaiting_choice" else "no_profile", "x"))
            await h.file(f"scan{index}", message_id=20 + index)
            job = h.flow.jobs[1]
            if target == "awaiting_confirmation":
                h.compiler.results.append(CompileResult(drafts=(profile(1, "Draft"),)))
                await h.text("Read the draft ID")
                assert h.previews._entries
            assert job.state == target
            tokens = list(job.buttons)
            if index == 1:
                await h.click("cancel")
            else:
                await h.text("Cancel")
            assert not h.flow.jobs and not h.previews._entries and job.submission.job_id in h.intake.cleaned
            h.app.submit(Event("callback", 1, payload=ButtonClick(tokens[0], f"old{index}")))
            await h.settle()
            assert h.transport.answers[-1] == (f"old{index}", "Session expired")
        assert list(h.store.rows) == [card.id]
    finally:
        await h.close()


async def test_late_results_of_a_replaced_or_cancelled_pass_are_discarded():
    h = Harness()
    try:
        card = profile(1)
        h.store.rows[card.id] = card
        await h.sign_in()
        h.recognition.gate, h.recognition.ignore_cancel = asyncio.Event(), True
        h.recognition.results.append(recognized(card, "OLD"))
        h.app.submit(Event("file", 1, update_id=1, message_id=1, payload=Upload("a1", 1, False, "g")))
        await h.until(lambda: 1 in h.flow.jobs and not h.flow.jobs[1].pending)
        h.clock.now = 3
        h.app.tick()
        await h.until(lambda: h.flow.status(1) == "processing")
        job = h.flow.jobs[1]
        first = job.generation
        # A late album part replaces the pass; the old call still returns a result.
        h.app.submit(Event("file", 1, update_id=2, message_id=2, payload=Upload("a2", 1, False, "g")))
        await h.until(lambda: job.generation > first)
        h.recognition.results.append(recognized(card, "NEW"))
        h.recognition.gate.set()
        await h.until(lambda: job.state == "collecting" and not job.pending)
        h.clock.now = 10
        h.app.tick()
        await h.settle()
        assert h.results() and all("OLD" not in text for text, _ in h.results())
        assert "NEW" in h.results()[-1][0]
        # Cancel while a response is underway: nothing is delivered after Cancel.
        h.recognition.gate = asyncio.Event()
        h.recognition.results.append(recognized(card, "AFTER-CANCEL"))
        h.app.submit(Event("file", 1, update_id=3, message_id=3, payload=Upload("b1", 1)))
        await h.until(lambda: h.flow.status(1) == "processing")
        h.app.submit(Event("text", 1, payload="Cancel"))
        await h.until(lambda: h.flow.jobs[1].state == "finishing")
        h.recognition.gate.set()
        await h.settle()
        assert all("AFTER-CANCEL" not in text for text, _ in h.results()) and not h.flow.jobs
    finally:
        await h.close()


async def test_waiting_is_not_charged_turn_order_is_kept_and_snapshot_is_immutable():
    h = Harness()
    try:
        first, second = profile(1, "Invoice"), profile(1, "Receipt")
        h.store.rows.update({first.id: first, second.id: second})
        await h.sign_in()
        await h.sign_in(2)
        h.recognition.gate = asyncio.Event()
        h.recognition.results.append(matching("uncertain"))
        h.app.submit(Event("file", 1, update_id=1, message_id=1, payload=Upload("scan", 1)))
        await h.until(lambda: h.flow.status(1) == "processing")
        # A profile saved while the job is processing is not in its snapshot.
        late = profile(1, "Late")
        h.store.rows[late.id] = late
        h.recognition.gate.set()
        await h.settle()
        h.recognition.gate = None
        job = h.flow.jobs[1]
        h.recognition.results.append(matching("uncertain"))
        await h.file("other", owner=2, message_id=2)
        h.clock.now = 800  # waiting for the user is not charged
        await h.click("instruct")
        assert "Late" not in h.texts()[-1] and {p.name for p in job.choices} == {"Invoice", "Receipt"}
        h.recognition.results.append(recognized(second, user_selected=True))
        await h.click("Receipt")
        calls = h.recognition.calls
        assert calls[-1].remaining == 1800 - 10 and calls[-1].order == calls[0].order < calls[1].order
        assert late not in calls[0].snapshots and job.used_s == 20
    finally:
        await h.close()


async def test_partial_compressed_and_long_results_are_delivered_completely():
    h = Harness()
    try:
        table = table_profile()
        h.store.rows[table.id] = table
        await h.sign_in()
        rows = tuple(ListRow(cells=(FieldResult(field_id="value", status="extracted",
                                                raw_value=f"{i:03d}" + "v" * 900, source_pages=(1,)),),
                             source_pages=(1,), source_key=str(i)) for i in range(12))
        listing = ListResult(field_id="rows", status="complete", rows=rows, enumeration_complete=True)
        result = CoreResult(MatchingResponse(status="matched", profile_index=1), table,
                            RecognitionResult(fields=(), lists=(listing,), outcome="complete"), False)
        h.recognition.results.append(PhaseOutcome(result=result))
        await h.file("long", message_id=1)
        parts = [t for t in h.texts() if t.startswith("Part ")]
        total = len(parts)
        assert total > 1 and [p.split(" ", 2)[1] for p in parts] == [f"{i}/{total}" for i in range(1, total + 1)]
        joined = "".join(parts)
        assert all(f"{i:03d}" in joined for i in range(12)) and not h.flow.jobs
        cells = (FieldResult(field_id="value", status="extracted", raw_value="001", source_pages=(1,)),)
        partial = ListResult(field_id="rows", status="partial", enumeration_complete=False, rows=(
            ListRow(cells=cells, source_pages=(1,), source_key="a"),))
        result = CoreResult(MatchingResponse(status="matched", profile_index=1), table,
                            RecognitionResult(fields=(), lists=(partial,), outcome="partial"), False)
        h.recognition.results.append(PhaseOutcome(result=result))
        await h.file("photo", message_id=2, compressed=True)
        text = h.results()[-1][0]
        assert text.startswith("Result: Partial") and "resend the document as a file" in text
    finally:
        await h.close()


async def test_two_users_cannot_act_on_each_others_jobs_previews_or_results():
    h = Harness()
    try:
        await h.sign_in(1)
        await h.sign_in(2)
        for owner in (1, 2):
            h.recognition.results.append(matching("no_profile", "x"))
            await h.file(f"scan{owner}", owner=owner, message_id=owner)
            h.compiler.results.append(CompileResult(drafts=(profile(owner, f"Draft{owner}"),)))
            await h.text("Read the ID", owner=owner)
        one, two = h.flow.jobs[1], h.flow.jobs[2]
        assert one.state == two.state == "awaiting_confirmation"
        for owner, other in ((1, two), (2, one)):
            for token in list(other.buttons):
                h.app.submit(Event("callback", owner, payload=ButtonClick(token, "x")))
        forged = f"j:{h.flow.nonce}:{one.submission.job_id}:{one.generation:x}:00000000"
        h.app.submit(Event("callback", 1, payload=ButtonClick(forged, "forged")))
        await h.settle()
        assert one.state == two.state == "awaiting_confirmation" and not h.store.rows
        assert h.transport.answers and all(text == "Session expired" for _, text in h.transport.answers)
        old = list(one.buttons)
        await h.text("Cancel", owner=1)
        h.recognition.results.append(matching("no_profile", "x"))
        await h.file("again", owner=1, message_id=9)
        h.app.submit(Event("callback", 1, payload=ButtonClick(old[0], "old")))
        await h.settle()
        assert h.transport.answers[-1] == ("old", "Session expired")
        assert h.flow.jobs[1].state == "awaiting_instruction"
        h.recognition.results.append(recognized(two.preview.drafts[0], "OWNER-2", user_selected=True))
        await h.click("save", owner=2)
        assert h.results(2) and not h.results(1)
        assert all(p.owner == "2" for p in h.store.rows.values())
    finally:
        await h.close()


async def test_job_outcomes_are_logged_as_content_free_technical_events(caplog):
    h = Harness()
    try:
        card = profile(1)
        h.store.rows[card.id] = card
        await h.sign_in()
        with caplog.at_level("INFO", logger="tgbotdocs.events"):
            h.recognition.results.append(recognized(card, "SECRET-VALUE-42"))
            await h.file("scan", message_id=1)
            h.recognition.results.append(matching("unreadable"))
            await h.file("blurred", message_id=2)
        lines = [r.getMessage() for r in caplog.records if r.name == "tgbotdocs.events"]
        assert any(" delivered_complete pages=1 charged_s=10.0" in line for line in lines)
        assert any(" unreadable pages=1 " in line for line in lines)
        assert all("SECRET" not in line and "Card" not in line and "scan" not in line for line in lines)
    finally:
        await h.close()
