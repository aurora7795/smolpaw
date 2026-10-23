"""
Radarr tools for the Smolpaw agent.

Config comes from the environment:
  RADARR_URL      e.g. http://192.168.1.50:7878
  RADARR_API_KEY  Settings > General in Radarr
  RADARR_DRY_RUN  "1" (default) blocks add_movie; set to "0" to allow real adds
"""

import os

import requests
from smolagents import tool


LAST_ACTION = ""  # outcome of the most recent add_movie, shown by the harness as ground truth


def _record(msg: str) -> str:
    global LAST_ACTION
    LAST_ACTION = msg
    return msg


def _cfg() -> tuple[str, dict]:
    url = os.environ.get("RADARR_URL", "").rstrip("/")
    key = os.environ.get("RADARR_API_KEY", "")
    if not url or not key:
        raise RuntimeError("Set RADARR_URL and RADARR_API_KEY in the environment.")
    return url, {"X-Api-Key": key}


def _get(path: str, **params):
    url, headers = _cfg()
    r = requests.get(f"{url}/api/v3/{path}", headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


@tool
def search_movie(term: str) -> str:
    """Search Radarr's metadata lookup for movies matching a title.

    Args:
        term: Movie title to search for, optionally with the year, e.g. "Heat 1995".
    """
    results = _get("movie/lookup", term=term)[:5]
    if not results:
        return "No matches."
    return "\n".join(
        f"tmdb_id={m['tmdbId']} | {m['title']} ({m.get('year')}) | "
        f"{'already in library' if m.get('id') else 'not in library'}"
        for m in results
    )


@tool
def list_add_options() -> str:
    """List the quality profiles and root folders that add_movie accepts."""
    profiles = _get("qualityprofile")
    folders = _get("rootfolder")
    return (
        "Quality profiles: "
        + ", ".join(f"{p['id']}={p['name']}" for p in profiles)
        + "\nRoot folders: "
        + ", ".join(f['path'] for f in folders)
    )


@tool
def add_movie(tmdb_id: int, quality_profile_id: int, root_folder_path: str) -> str:
    """Add a movie to Radarr and start searching for a download. Asks the user to confirm first.

    Args:
        tmdb_id: The tmdb_id returned by search_movie.
        quality_profile_id: A profile id returned by list_add_options.
        root_folder_path: A root folder path returned by list_add_options.
    """
    found = _get("movie/lookup", term=f"tmdb:{tmdb_id}")
    if not found:
        return _record(f"No movie found for tmdb_id {tmdb_id}.")
    movie = found[0]
    label = f"{movie['title']} ({movie.get('year')})"

    if movie.get("id"):
        return _record(f"{label} is already in the library.")
    profiles = {p["id"]: p["name"] for p in _get("qualityprofile")}
    folders = [f["path"] for f in _get("rootfolder")]
    if quality_profile_id not in profiles or root_folder_path not in folders:
        return _record((
            "NOT ADDED: invalid quality_profile_id or root_folder_path. Valid values: "
            f"profiles {profiles}, folders {folders}. Retry with valid values."
        ))
    if os.environ.get("RADARR_DRY_RUN", "1") != "0":
        return _record((
            f"DRY RUN - NOT ADDED. {label} was NOT added to Radarr and no download started. "
            "Call final_answer now and say it was not added because dry-run mode is on."
        ))
    if input(f"\nAdd {label} to Radarr and start download? [y/N] ").strip().lower() != "y":
        return _record("User declined; nothing was added.")

    url, headers = _cfg()
    movie.update(
        qualityProfileId=quality_profile_id,
        rootFolderPath=root_folder_path,
        monitored=True,
        addOptions={"searchForMovie": True},
    )
    r = requests.post(f"{url}/api/v3/movie", headers=headers, json=movie, timeout=30)
    if not r.ok:
        return _record(f"Radarr rejected the add: {r.status_code} {r.text[:300]}")
    return _record(
        f"SUCCESS: Added {label} to Radarr and triggered a download search. "
        "Call final_answer now and tell the user it was added."
    )


@tool
def get_queue() -> str:
    """Show Radarr's current download queue with progress."""
    records = _get("queue", pageSize=20, includeMovie="true").get("records", [])
    if not records:
        return "Queue is empty."
    lines = []
    for q in records:
        size = q.get("size") or 0
        pct = 100 * (size - q.get("sizeleft", 0)) / size if size else 0
        title = q.get("movie", {}).get("title") or q.get("title")
        lines.append(f"{title} | {q.get('status')} | {pct:.0f}%")
    return "\n".join(lines)


RADARR_TOOLS = [search_movie, list_add_options, add_movie, get_queue]
