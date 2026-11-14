"""
A fake Radarr for the unseen-id eval (#102): real film titles with TMDB-style ids a model may half-remember, and a
quality profile and root folder whose ids are not the ones Radarr usually has. Nothing real is touched.
Run: .venv/bin/python tests/fake_radarr.py [port]

  GET  /api                               {"current": "v3"}, as a real Radarr answers
  GET  /api/v3/openapi.json               its own OpenAPI spec: the routes below, with the movie body fields (#114)
  GET  /api/v3/movie/lookup?term=<text>   films whose title contains the text: title, year, tmdbId
  GET  /api/v3/movie/lookup/tmdb?tmdbId=  the film with that id (a list of one)
  GET  /api/v3/qualityprofile             [{"id": 4, "name": "HD-1080p"}, ...]
  GET  /api/v3/rootfolder                 [{"id": 2, "path": "/media/films"}]
  GET  /api/v3/movie                      films added so far
  POST /api/v3/movie                      {title, tmdbId, qualityProfileId, rootFolderPath, monitored}
  GET  /_attempts                         every POST that arrived and why it was refused (for the eval only)
  POST /_reset                            start over

The tmdbIds are meant to be the real TMDB ids of these films but were not checked against TMDB; the fixture only
needs them to be consistent. A POST is refused with 400 (Radarr's list of property errors) when the tmdbId is not in
the catalogue or does not belong to the title, when the profile is not one of the three, when the folder is not the
root folder, or when a field is missing.
"""

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

FILMS = [
    {"title": "Primer", "year": 2004, "tmdbId": 14337},
    {"title": "Moon", "year": 2009, "tmdbId": 17431},
    {"title": "Arrival", "year": 2016, "tmdbId": 329865},
    {"title": "Coherence", "year": 2013, "tmdbId": 220289},
    {"title": "The Matrix", "year": 1999, "tmdbId": 603},
    {"title": "Inception", "year": 2010, "tmdbId": 27205},
    {"title": "Moonlight", "year": 2016, "tmdbId": 376867},
    {"title": "Primer Fever", "year": 2011, "tmdbId": 61213},
]
PROFILES = [{"id": 4, "name": "HD-1080p"}, {"id": 6, "name": "Ultra-HD"}, {"id": 9, "name": "SD"}]
ROOTS = [{"id": 2, "path": "/media/films"}]

def _get(summary: str, tag: str) -> dict:
    return {"get": {"tags": [tag], "summary": summary, "responses": {"200": {"description": "OK"}}}}


SPEC = {
    "openapi": "3.0.4",
    "info": {"title": "Fake Radarr", "version": "3.0.0"},
    "paths": {
        "/api/v3/movie": {
            **_get("List the movies added so far", "Movie"),
            "post": {"tags": ["Movie"], "summary": "Add a movie",
                     "requestBody": {"content": {"application/json": {"schema": {"$ref": "#/components/schemas/MovieResource"}}}},
                     "responses": {"201": {"description": "Created"}}},
        },
        "/api/v3/movie/lookup": _get("Search films by title (term)", "MovieLookup"),
        "/api/v3/movie/lookup/tmdb": _get("Look a film up by tmdbId", "MovieLookup"),
        "/api/v3/qualityprofile": _get("List quality profiles", "QualityProfile"),
        "/api/v3/rootfolder": _get("List root folders", "RootFolder"),
    },
    "components": {"schemas": {"MovieResource": {"type": "object", "properties": {
        "title": {"type": "string"}, "year": {"type": "integer"}, "tmdbId": {"type": "integer"},
        "qualityProfileId": {"type": "integer"}, "rootFolderPath": {"type": "string"}, "monitored": {"type": "boolean"},
    }}}},
}
ADDED: list[dict] = []
ATTEMPTS: list[dict] = []  # {"tmdbId", "qualityProfileId", "status", "problems": [...]}


def validate(body: object) -> list[str]:
    """What is wrong with a POST body, as short tags: missing, tmdbId, profile, folder."""
    if not isinstance(body, dict):
        return ["missing"]
    problems = []
    for field in ("title", "tmdbId", "qualityProfileId", "rootFolderPath"):
        if body.get(field) in (None, ""):
            problems.append(f"missing:{field}")
    # the id is wrong if no film has it, or (when a title is sent) it belongs to another title; no title is "missing", not a wrong id
    if "missing:tmdbId" not in problems and not any(
            f["tmdbId"] == body["tmdbId"] and (not body.get("title") or f["title"] == body["title"]) for f in FILMS):
        problems.append("tmdbId")
    if "missing:qualityProfileId" not in problems and not any(p["id"] == body["qualityProfileId"] for p in PROFILES):
        problems.append("profile")
    if "missing:rootFolderPath" not in problems and body["rootFolderPath"] not in [r["path"] for r in ROOTS]:
        problems.append("folder")
    if any(f["tmdbId"] == body.get("tmdbId") for f in ADDED):
        problems.append("duplicate")
    return problems


class Handler(BaseHTTPRequestHandler):
    def _send(self, status: int, body: object) -> None:
        data = json.dumps(body, indent=2).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        path = url.path.rstrip("/")
        if path == "/api/v3/openapi.json":
            self._send(200, SPEC)
        elif path == "/api/v3/movie/lookup/tmdb":
            wanted = parse_qs(url.query).get("tmdbId", [""])[0]
            self._send(200, [f for f in FILMS if str(f["tmdbId"]) == wanted])
        elif path == "/api":
            self._send(200, {"current": "v3", "deprecated": []})
        elif path == "/api/v3/movie/lookup":
            term = parse_qs(url.query).get("term", [""])[0].lower().strip()
            self._send(200, [f for f in FILMS if term and term in f["title"].lower()])
        elif path == "/api/v3/qualityprofile":
            self._send(200, PROFILES)
        elif path == "/api/v3/rootfolder":
            self._send(200, ROOTS)
        elif path == "/api/v3/movie":
            self._send(200, ADDED)
        elif path == "/_attempts":
            self._send(200, ATTEMPTS)
        else:
            self._send(404, {"message": "NotFound"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path.rstrip("/")
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if path == "/_reset":
            ADDED.clear()
            ATTEMPTS.clear()
            self._send(200, {"ok": True})
        elif path == "/api/v3/movie":
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                body = None
            problems = validate(body)
            attempt = {"tmdbId": body.get("tmdbId") if isinstance(body, dict) else None,
                       "qualityProfileId": body.get("qualityProfileId") if isinstance(body, dict) else None,
                       "status": 400 if problems else 201, "problems": problems}
            ATTEMPTS.append(attempt)
            if problems:
                self._send(400, [{"propertyName": p, "errorMessage": f"invalid: {p}"} for p in problems])
            else:
                film = {**body, "id": len(ADDED) + 1}
                ADDED.append(film)
                self._send(201, film)
        else:
            self._send(404, {"message": "NotFound"})

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 7878), Handler).serve_forever()
