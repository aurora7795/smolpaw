"""
A fake Radarr for the unseen-id eval (#102): real film titles with TMDB-style ids a model may half-remember, and a
quality profile and root folder whose ids are not the ones Radarr usually has. Nothing real is touched.
Run: .venv/bin/python tests/fake_radarr.py [port]

  GET  /api/v3/movie/lookup?term=<text>   films whose title contains the text: title, year, tmdbId
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
    if "missing:tmdbId" not in problems and not any(f["tmdbId"] == body["tmdbId"] and f["title"] == body.get("title")
                                                    for f in FILMS):
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
        if path == "/api/v3/movie/lookup":
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
