import logging

from tgbotdocs.application.service import configure_logging


def test_only_structured_technical_events_persist_even_on_dependency_failure(tmp_path, monkeypatch):
    config = tmp_path / "config.env"
    config.write_text(f"DATA_ROOT={tmp_path}\n", encoding="utf-8")
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", list(root.handlers))
    monkeypatch.setattr(root, "level", root.level)
    handler = configure_logging(config)
    try:
        marker = "synthetic_private_document_token_password"
        for name in ("aiogram.dispatcher", "aiohttp", "httpx", "asyncio", "other", "tgbotdocs.events"):
            logging.getLogger(name).error("unstructured %s", marker)
            try:
                raise RuntimeError(marker)
            except RuntimeError:
                logging.getLogger(name).exception("startup_failed")
        events = logging.getLogger("tgbotdocs.events")
        events.info("%s", marker)
        events.info("%s", "startup_completed")
        events.warning("service_retry_scheduled")
        events.info("job_finished %s %s pages=%d charged_s=%.1f", "a" * 32, "delivered_sent", 2, 3.5)
        events.info("job_finished %s %s pages=%d charged_s=%.1f", marker, "delivered_sent", 2, 3.5)
        handler.flush()
        log = (tmp_path / "logs/tgbotdocs.log").read_text(encoding="utf-8")
        assert marker not in log and "Traceback" not in log
        assert len(log.splitlines()) == 3
        assert "startup_completed" in log and "service_retry_scheduled" in log
        assert "job_finished " + "a" * 32 in log
        replacement = configure_logging(config)
        try:
            assert handler.stream is None
        finally:
            replacement.close()
    finally:
        handler.close()
