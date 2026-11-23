"""
Progress and error reporting for model calls in the CLI.

A model call can take minutes on a local server, and a dead server used to look the same as a slow one. This module
shows how long the current call has been waiting, says when it is retrying and why, and turns the OpenAI client's
terse errors ("Connection error.") into something that names the server and the likely cause.

The reporter is silent until `REPORTER.stream` is set (the CLI sets it to stderr), so the eval harness, the web
harness and the tests print nothing extra.
"""

import contextlib
import os
import sys
import threading
import time

import openai

RETRY_STATUS = {408, 409, 429}  # request timeout, conflict, rate limit; every 5xx is retried too
BACKOFF_MAX = 8.0  # seconds; the wait before retry n is min(2**(n-1), BACKOFF_MAX)
SLOW_REPLY = 10.0  # a reply slower than this is noted when it arrives


class ModelCallError(RuntimeError):
    """A model call that failed for good; the message says what happened and what to check."""


def fmt_elapsed(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds}s" if seconds < 60 else f"{seconds // 60}m {seconds % 60:02d}s"


def is_retryable(exc: BaseException) -> bool:
    """Transient trouble worth another attempt: no connection, a timeout, a busy or failing server."""
    if isinstance(exc, openai.APIConnectionError):  # APITimeoutError is a subclass
        return True
    if isinstance(exc, openai.APIStatusError):
        return exc.status_code in RETRY_STATUS or exc.status_code >= 500
    return False


def describe(exc: BaseException, base_url: str = "", model: str = "") -> str:
    """One line saying what went wrong with a model call and what to check."""
    where = f" at {base_url}" if base_url else ""
    if isinstance(exc, openai.APITimeoutError):
        return f"the model server{where} stopped answering (timed out); it may be overloaded or still loading the model"
    if isinstance(exc, openai.APIConnectionError):
        cause = exc.__cause__ or exc
        return (f"cannot reach the model server{where} ({type(cause).__name__}: {cause}); "
                "is Ollama or LM Studio running?")
    if isinstance(exc, openai.APIStatusError):
        detail = str(getattr(exc, "message", "") or exc).strip()
        hint = ""
        if exc.status_code == 404:
            hint = f"; is model {model!r} installed and loaded? " if model else "; is the model installed and loaded? "
        elif exc.status_code == 429:
            hint = "; the server is rate limiting or busy"
        elif exc.status_code >= 500:
            hint = "; the server failed while answering (out of memory, or a model crash?)"
        return f"the model server{where} returned HTTP {exc.status_code}: {detail}{hint}".rstrip()
    return f"{type(exc).__name__}: {exc}"


class Reporter:
    """Writes status lines for model calls. Off while `stream` is None.

    On a terminal the wait counter redraws in place every second; elsewhere (a pipe, a log) it prints a line every
    `idle_interval` seconds so a long call is visibly alive without flooding the log.
    """

    def __init__(self, stream=None, idle_interval: float = 30.0, tick: float = 1.0):
        self.stream = stream
        self.idle_interval = idle_interval
        self.tick = tick
        self._lock = threading.Lock()
        self._drawn = False

    @property
    def tty(self) -> bool:
        return bool(self.stream and getattr(self.stream, "isatty", lambda: False)())

    def _write(self, text: str) -> None:
        with contextlib.suppress(Exception):  # a closed or broken stderr must never fail a model call
            self.stream.write(text)
            self.stream.flush()

    def _erase(self) -> None:
        if self._drawn:
            self._write("\r\033[K")
            self._drawn = False

    def line(self, message: str) -> None:
        """A permanent status line (a retry, an error, a slow reply)."""
        if not self.stream:
            return
        with self._lock:
            self._erase()
            self._write(message + "\n")

    @contextlib.contextmanager
    def waiting(self, label: str):
        """Show how long the call inside the block has been waiting; clear the counter when it ends."""
        if not self.stream:
            yield
            return
        start = time.monotonic()
        stop = threading.Event()
        interval = self.tick if self.tty else self.idle_interval

        def beat() -> None:
            while not stop.wait(interval):
                message = f"[model] {label}... {fmt_elapsed(time.monotonic() - start)}"
                with self._lock:
                    if self.tty:
                        self._write("\r\033[K" + message)
                        self._drawn = True
                    else:
                        self._write(message + "\n")

        worker = threading.Thread(target=beat, daemon=True)
        worker.start()
        try:
            yield
        finally:
            stop.set()
            worker.join()
            with self._lock:
                self._erase()
        elapsed = time.monotonic() - start
        if elapsed >= SLOW_REPLY:  # only reached when the call succeeded
            self.line(f"[model] replied after {fmt_elapsed(elapsed)}")


REPORTER = Reporter()


def max_retries() -> int:
    """Retries after the first attempt (SMOLPAW_MODEL_RETRIES, default 2 as the OpenAI client used)."""
    raw = os.environ.get("SMOLPAW_MODEL_RETRIES", "")
    try:
        return max(0, int(raw)) if raw.strip() else 2
    except ValueError:
        print(f"WARNING: SMOLPAW_MODEL_RETRIES={raw!r} is not a whole number; using 2.", file=sys.stderr)
        return 2


def pause(seconds: float) -> None:
    """The wait before a retry (a function of its own so tests can skip it)."""
    time.sleep(seconds)


def call_with_status(fn, *, label: str, base_url: str, model: str, retries: int, reporter: Reporter | None = None):
    """Run `fn()` (one model call), reporting the wait, each retry and the final failure.

    Raises ModelCallError, with the original exception chained, once retries run out or the error is not transient.
    """
    reporter = reporter or REPORTER
    attempt = 0
    while True:
        attempt += 1
        try:
            with reporter.waiting(label if attempt == 1 else f"{label} (attempt {attempt})"):
                return fn()
        except Exception as exc:  # noqa: BLE001 - classified below; KeyboardInterrupt is not an Exception
            if not isinstance(exc, (openai.APIConnectionError, openai.APIStatusError)):
                raise  # a bug or a smolagents error, not a model-server failure; leave it as it was
            why = describe(exc, base_url, model)
            if is_retryable(exc) and attempt <= retries:
                delay = min(2.0 ** (attempt - 1), BACKOFF_MAX)
                reporter.line(f"[model] {why}. Retry {attempt} of {retries} in {fmt_elapsed(delay)}.")
                pause(delay)
                continue
            tries = f" after {attempt} attempts" if attempt > 1 else ""
            reporter.line(f"[model] failed{tries}: {why}")
            raise ModelCallError(f"{why}{tries and ' (' + tries.strip() + ')'}") from exc
