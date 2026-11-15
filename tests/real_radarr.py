"""
Rung 3 against a real Radarr (#1): a pool of films to add, scripted approvals that allow one kind of write, a
read-back check on the server's own state, and a report of what was added so it can be removed by hand.

Used by `tests/eval.py --real-radarr`; the pieces are here so tests/test_real_radarr.py can exercise them against
tests/fake_radarr.py without a real service. Nothing here deletes anything.

The approver is the only thing between a model's write and the library, so it is deliberately narrow:
  - it approves `POST <radarr>/api/v3/movie` for the film this run is meant to add, and nothing else
    (a lookup in Radarr is a GET, so no other POST is needed);
  - a body whose tmdbId is not this run's film is declined; one whose tmdbId is not any pool film also stops the eval;
  - a film whose write already succeeded is not written again, and a run gets at most MAX_WRITES_PER_RUN attempts
    (a model's first body is often malformed and Radarr refuses it without writing, so a retry is allowed);
  - an auth failure (401/403) or MAX_FAILED_WRITES_IN_A_ROW failed writes in a row stop the eval: after a stop it
    declines everything.
The confirmation prompt shows at most the first 500 characters of the body, and a model that copies a whole lookup
result puts the tmdbId past that. So the approver says yes when the preview is cut off before any tmdbId, and a second
gate (`Approver.wrap`, installed around `requests.request` in the eval process) checks the full body just before it is
sent and blocks it unless it is this run's film. Nothing is sent that either check could not see.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import urlparse

import requests

# Films that are unlikely to be in a library already, with the year that tells them apart from others of the same
# title. Six, not three: each model's runs add their own films, and the library is cleaned up by hand afterwards,
# so the second model must not find the first one's films there. The pool also caps the real adds at six.
POOL: list[tuple[str, int]] = [
    ("The Man from Earth", 2007),
    ("Safety Not Guaranteed", 2012),
    ("Dark Star", 1974),
    ("Beyond the Black Rainbow", 2010),
    ("Rubber", 2010),
    ("Timecrimes", 2007),
]
PROMPT = "Add the movie {title} ({year}) to Radarr."
MAX_WRITES_PER_RUN = 3
MAX_FAILED_WRITES_IN_A_ROW = 6
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def get_json(url: str, key: str, path: str, params: dict | None = None):
    """A read-only GET against Radarr's API. The key goes in a header and is never printed."""
    r = requests.get(f"{url.rstrip('/')}{path}", params=params, headers={"X-Api-Key": key} if key else {}, timeout=30)
    r.raise_for_status()
    return r.json()


def is_local(url: str) -> bool:
    """True for a server on this machine, where a write cannot reach a real service."""
    return urlparse(url).hostname in LOCAL_HOSTS


@dataclass
class Film:
    title: str
    year: int
    tmdb_id: int


def library_ids(url: str, key: str) -> set[int]:
    return {m["tmdbId"] for m in get_json(url, key, "/api/v3/movie")}


def resolve_films(url: str, key: str, pool: list[tuple[str, int]]) -> tuple[list[Film], list[str], set[int]]:
    """Look each pool film up (read-only). Returns the films to use (exact title and year, not in the library yet),
    the reasons for those not used, and the tmdbIds of every pool film found, used or not."""
    have = library_ids(url, key)
    usable, skipped, found = [], [], set()
    for title, year in pool:
        results = get_json(url, key, "/api/v3/movie/lookup", {"term": title})
        hit = next((m for m in results if m.get("title", "").lower() == title.lower() and m.get("year") == year), None)
        if hit is None:
            skipped.append(f"{title} ({year}): not found by lookup")
            continue
        found.add(hit["tmdbId"])
        if hit["tmdbId"] in have:
            skipped.append(f"{title} ({year}): already in the library")
        else:
            usable.append(Film(title, year, hit["tmdbId"]))
    return usable, skipped, found


def preview_cut_off(desc: str) -> bool:
    """True when the confirmation prompt shows only the first 500 characters of a longer body."""
    return len(desc.split("body: ", 1)[1]) >= 500 if "body: " in desc else False


def preview_tmdb_id(desc: str) -> int | None:
    """The tmdbId in the body preview of a confirmation prompt, or None when it is not there."""
    m = re.search(r'"tmdbId"\s*:\s*(\d+)', desc)
    return int(m.group(1)) if m else None


@dataclass
class Approver:
    """Scripted yes/no for the confirmation prompts of a real-Radarr run. Install `.confirm` as generic_tools.CONFIRM."""

    url: str
    pool_ids: set[int]  # tmdbIds of every pool film; a write for anything else stops the eval
    actions: list[str]  # generic_tools.ACTIONS, read to count failed writes
    current: int | None = None  # tmdbId this run should add
    stop_reason: str = ""
    approved: list[int] = field(default_factory=list)  # tmdbId of each write let through, one entry per attempt
    succeeded: set[int] = field(default_factory=set)  # tmdbIds whose write came back 2xx
    declined: list[str] = field(default_factory=list)  # first line of each declined prompt, with the reason
    blocked: list[str] = field(default_factory=list)  # writes the send-time gate stopped, with the reason
    _seen: int = 0
    _fail_streak: int = 0
    _run_writes: int = 0
    _run_start: tuple[int, int, int] = (0, 0, 0)

    def start_run(self, tmdb_id: int) -> None:
        """Point the approver at this run's film, with a fresh attempt allowance."""
        self.current, self._run_writes, self._seen = tmdb_id, 0, 0  # the run's action list starts empty
        self._run_start = (len(self.approved), len(self.declined), len(self.blocked))

    def run_record(self) -> dict:
        """What this run's approver did: writes let through, prompts declined, writes the gate blocked."""
        a, d, b = self._run_start
        return {"approved_writes": self.approved[a:], "declined_prompts": self.declined[d:], "blocked_writes": self.blocked[b:]}

    def _count_failures(self) -> None:
        if len(self.actions) < self._seen:  # the run's action list was cleared
            self._seen = 0
        for line in self.actions[self._seen:]:
            m = re.match(r"^POST \S+ -> HTTP (\d+)", line)
            if not m:
                continue
            status = int(m.group(1))
            self._fail_streak = self._fail_streak + 1 if status >= 400 else 0
            if status < 300 and self.current is not None:
                self.succeeded.add(self.current)
            if status in (401, 403) and not self.stop_reason:
                self.stop_reason = f"HTTP {status} from Radarr: the key is not accepted"
        self._seen = len(self.actions)

    def _gate_problem(self, method: str, url: str, body: object) -> str:
        """Why a write must not be sent, judged on the whole body; empty when it may go."""
        if method.upper() != "POST" or url.rstrip("/") != f"{self.url.rstrip('/')}/api/v3/movie":
            return f"{method} {url} is not the one write this eval allows"
        tmdb = body.get("tmdbId") if isinstance(body, dict) else None
        if tmdb is None:
            return "the body has no tmdbId"
        if tmdb not in self.pool_ids:
            self.stop_reason = f"a write for tmdbId {tmdb}, which is not one of the pool films"
            return self.stop_reason
        if tmdb != self.current:
            return f"tmdbId {tmdb} is not this run's film"
        return ""

    def wrap(self, real_request: Callable) -> Callable:
        """requests.request with a last check on every write: the full body must be this run's film."""
        def request(method, url, **kwargs):
            if str(method).upper() != "GET":
                problem = self._gate_problem(str(method), str(url), kwargs.get("json"))
                if problem:
                    self.blocked.append(problem)
                    raise requests.RequestException(f"not sent: {problem} (the eval harness blocks it before it leaves)")
            return real_request(method, url, **kwargs)
        return request

    def after_run(self) -> None:
        """Count the writes of the run that just ended, so a streak of failures stops the eval before the next run."""
        self._count_failures()
        if self._fail_streak >= MAX_FAILED_WRITES_IN_A_ROW and not self.stop_reason:
            self.stop_reason = f"{self._fail_streak} failed writes in a row"

    def confirm(self, desc: str) -> bool:
        first = desc.splitlines()[0] if desc else ""

        def no(reason: str) -> bool:
            self.declined.append(f"{first[:120]} ({reason})")
            return False

        self._count_failures()
        if self.stop_reason:
            return no("stopped")
        if self._fail_streak >= MAX_FAILED_WRITES_IN_A_ROW:
            self.stop_reason = f"{self._fail_streak} failed writes in a row"
            return no(self.stop_reason)
        if first.rstrip("/") != f"POST {self.url.rstrip('/')}/api/v3/movie":
            return no("only POST /api/v3/movie is approved")
        tmdb = preview_tmdb_id(desc)
        if tmdb is None and not preview_cut_off(desc):
            return no("no tmdbId in the body")
        if tmdb is None:
            tmdb = self.current  # not visible in the preview; the send-time gate checks the whole body
        if tmdb not in self.pool_ids:
            self.stop_reason = f"a write for tmdbId {tmdb}, which is not one of the pool films"
            return no(self.stop_reason)
        if tmdb != self.current:
            return no("a pool film, but not this run's")
        if tmdb in self.succeeded:
            return no("this film was already added in this eval")
        if self._run_writes >= MAX_WRITES_PER_RUN:
            return no(f"this run has used its {MAX_WRITES_PER_RUN} write attempts")
        self._run_writes += 1
        self.approved.append(tmdb)
        return True


@dataclass
class Added:
    radarr_id: int
    title: str
    tmdb_id: int


def check(url: str, key: str, film: Film, before: set[int], added_log: list[Added]) -> tuple[bool, str]:
    """Pass only if the library gained exactly this film, with a quality profile and root folder that exist.
    Everything added (for any reason) is appended to added_log so it can be listed for removal."""
    library = get_json(url, key, "/api/v3/movie")
    new = [m for m in library if m["tmdbId"] not in before]
    added_log.extend(Added(m.get("id", 0), m.get("title", "?"), m["tmdbId"]) for m in new)
    profiles = {p["id"] for p in get_json(url, key, "/api/v3/qualityprofile")}
    roots = [r["path"] for r in get_json(url, key, "/api/v3/rootfolder")]
    if [m["tmdbId"] for m in new] != [film.tmdb_id]:
        return False, f"library gained {[(m.get('title'), m['tmdbId']) for m in new]}, wanted only {film.title} ({film.tmdb_id})"
    m = new[0]
    in_root = any(str(m.get("rootFolderPath", m.get("path", ""))).startswith(r.rstrip("/")) for r in roots)
    if m.get("qualityProfileId") not in profiles or not in_root:
        return False, f"added {film.title} with profile {m.get('qualityProfileId')} / folder {m.get('rootFolderPath', m.get('path'))}, not ones that exist"
    return True, f"added {film.title} (radarr id {m.get('id')}, tmdb {film.tmdb_id}) with an existing profile and root folder"


def queue_report(url: str, key: str, added: list[Added]) -> list[str]:
    """Read-only: queue entries for the films that were added, as a to-clean-up list. Empty if Radarr has no queue."""
    try:
        queue = get_json(url, key, "/api/v3/queue", {"pageSize": 200})
    except (requests.RequestException, ValueError):
        return []
    records = queue.get("records", []) if isinstance(queue, dict) else queue
    ids = {a.radarr_id for a in added}
    return [f"queue: {r.get('title', '?')} ({r.get('status', '?')})" for r in records if r.get("movieId") in ids]


def cleanup_report(url: str, key: str, added: list[Added]) -> str:
    """What to remove by hand: titles with Radarr's own ids, plus any queue entries (downloads may have started)."""
    if not added:
        return "nothing was added to the library; nothing to clean up"
    lines = [f"  {a.title} (radarr id {a.radarr_id}, tmdb {a.tmdb_id})" for a in added]
    lines += [f"  {q}" for q in queue_report(url, key, added)]
    return "added to the library, remove by hand (also check the queue and any downloaded files):\n" + "\n".join(lines)

