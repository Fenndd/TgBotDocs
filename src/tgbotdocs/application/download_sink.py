"""Bound actual streamed bytes before they reach owned temporary storage."""

import io


FILE_LIMIT = 20 * 1024 * 1024


class DownloadError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class QuotaCoordinator:
    """Event-loop check/write seam; no await may occur between these operations.

    Future renderer reservations can extend this single shared coordinator.
    Current downloads use synchronous BinaryIO writes, so another download cannot
    consume the same checked capacity before the current chunk is written.
    """

    def __init__(self, lifecycle):
        self.lifecycle = lifecycle

    def write(self, stream, chunk):
        try:
            self.lifecycle.check_capacity(len(chunk))
            written = stream.write(chunk)
            if written != len(chunk):
                raise DownloadError("storage_limit")
            stream.flush()
            return written
        except OSError:
            raise DownloadError("storage_limit") from None


class DownloadSink(io.RawIOBase):
    """Exclusive generated path, forward-only, no buffering of document bytes."""

    def __init__(self, path, coordinator, *, limit_bytes=FILE_LIMIT):
        super().__init__()
        self.coordinator, self.limit_bytes = coordinator, limit_bytes
        self.written = 0
        self._stream = None
        try:
            self._stream = path.open("xb")
        except OSError:
            raise DownloadError("storage_limit") from None

    def writable(self):
        return True

    def write(self, chunk):
        if self.closed:
            raise ValueError("closed download sink")
        if self.written + len(chunk) > self.limit_bytes:
            raise DownloadError("file_too_large")
        try:
            count = self.coordinator.write(self._stream, chunk)
        except OSError:
            raise DownloadError("storage_limit") from None
        self.written += count
        return count

    def flush(self):
        if self._stream is not None and not self._stream.closed:
            try:
                self._stream.flush()
            except OSError:
                raise DownloadError("storage_limit") from None

    def close(self):
        if not self.closed:
            try:
                super().close()
            finally:
                if self._stream is not None:
                    try:
                        self._stream.close()
                    except OSError:
                        raise DownloadError("storage_limit") from None
