"""Bounded HTTP access to IRSA: retries for transient failures, a concurrency cap,
byte limits, and a record of every request (for manifests and Methods).

Standard library only. A failed request raises ArchiveRequestFailed; callers
record the failure and never substitute other data.
"""

from __future__ import annotations

import hashlib
import http.client
import socket
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime

USER_AGENT = "SkyShift/0.1 (local research build; bounded SPHEREx cutout client)"
TRANSIENT_HTTP = frozenset({429, 502, 503, 504})


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


@dataclass
class HttpRecord:
    url: str
    started_utc: str
    status: int | None
    bytes: int
    sha256: str | None
    elapsed_s: float
    attempts: int
    range: str | None = None
    content_range: str | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


class ArchiveRequestFailed(RuntimeError):
    def __init__(self, record: HttpRecord, reason: str) -> None:
        super().__init__(f"{reason} ({record.url}, attempts={record.attempts})")
        self.record = record
        self.reason = reason


@dataclass
class ArchiveClient:
    timeout_s: float = 120.0
    # IRSA's proxy answered roughly 2 of 3 SIA2 requests with fast (~0.5 s) '502 Proxy Error' responses on
    # 2026-11-14 (interleaved with normal 200s); 12 attempts bound the failure probability to ~1 % (worst case ~90 s).
    max_attempts: int = 12
    backoff_s: float = 1.5
    max_backoff_s: float = 10.0
    max_concurrency: int = 4
    user_agent: str = USER_AGENT
    log: list[HttpRecord] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not 1 <= self.max_concurrency <= 8:
            raise ValueError("max_concurrency must be between 1 and 8 (IRSA is a shared service)")
        self._slots = threading.BoundedSemaphore(self.max_concurrency)
        self._log_lock = threading.Lock()

    def get(self, url: str, *, byte_range: str | None = None, max_bytes: int | None = None) -> tuple[bytes, HttpRecord]:
        """GET `url`. With `byte_range` ('bytes=a-b' or 'bytes=-n') the server must answer 206.

        `max_bytes` aborts responses whose declared or received size exceeds the limit
        (protects against accidentally downloading a full 60 MB image).
        """
        if not url.startswith("https://irsa.ipac.caltech.edu/"):
            raise ValueError(f"refusing non-IRSA URL: {url}")
        started, t0 = utc_now(), time.perf_counter()
        last_error = "no attempt"
        status: int | None = None
        for attempt in range(1, self.max_attempts + 1):
            headers = {"User-Agent": self.user_agent}
            if byte_range:
                headers["Range"] = byte_range
            try:
                with self._slots:
                    req = urllib.request.Request(url, headers=headers)
                    with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:  # noqa: S310 (https, fixed host)
                        status = resp.status
                        declared = resp.headers.get("Content-Length")
                        if byte_range and status != 206:
                            raise _Permanent(f"server ignored Range ({status}); refusing a full download")
                        if max_bytes is not None and declared is not None and int(declared) > max_bytes:
                            raise _Permanent(f"response of {declared} bytes exceeds the {max_bytes}-byte limit")
                        body = resp.read() if max_bytes is None else resp.read(max_bytes + 1)
                        if max_bytes is not None and len(body) > max_bytes:
                            raise _Permanent(f"response exceeds the {max_bytes}-byte limit")
                        content_range = resp.headers.get("Content-Range")
                rec = HttpRecord(url, started, status, len(body), hashlib.sha256(body).hexdigest(), round(time.perf_counter() - t0, 3), attempt, byte_range, content_range)
                self._record(rec)
                return body, rec
            except _Permanent as exc:
                last_error = str(exc)
                break
            except urllib.error.HTTPError as exc:
                status = exc.code
                last_error = f"HTTP {exc.code} {exc.reason}"
                if exc.code not in TRANSIENT_HTTP:
                    break
            except (urllib.error.URLError, TimeoutError, socket.timeout, http.client.IncompleteRead, http.client.RemoteDisconnected, ConnectionError) as exc:
                status = None
                last_error = f"{type(exc).__name__}: {exc}"
            if attempt < self.max_attempts:
                time.sleep(min(self.max_backoff_s, self.backoff_s * attempt))
        rec = HttpRecord(url, started, status, 0, None, round(time.perf_counter() - t0, 3), attempt, byte_range, None, last_error)
        self._record(rec)
        raise ArchiveRequestFailed(rec, last_error)

    def _record(self, rec: HttpRecord) -> None:
        with self._log_lock:
            self.log.append(rec)


class _Permanent(Exception):
    """A response that must not be retried (wrong status for a range request, size limit)."""
