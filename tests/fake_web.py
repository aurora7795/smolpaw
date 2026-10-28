"""
Deterministic fake web server and SearXNG search endpoint for repeatable tests.
Runs on 127.0.0.1 only.

Run standalone:
  .venv/bin/python tests/fake_web.py [port]

Importable:
  server, base_url = start(port=0)
  ...
  server.shutdown()
  server.server_close()
"""

import json
import random
import re
import socketserver
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

HOST = "127.0.0.1"
DEFAULT_PORT = 8768  # 8766 and 8767 are fake_mail.py's SMTP and IMAP ports

# Fixed word list containing exclusively letters (no digits 0-9).
FILLER_WORDS = [
    "the", "ridge", "valley", "station", "observatory", "refuge", "authority",
    "basin", "survey", "plateau", "summit", "elevation", "corridor", "boundary",
    "climate", "monitoring", "weather", "atmosphere", "geology", "strata",
    "terrace", "meadow", "timberline", "forest", "glacier", "stream", "tributary",
    "channel", "flow", "gradient", "alluvial", "gravel", "silt", "waterway",
    "marsh", "wetland", "estuary", "current", "depth", "volume", "catchment",
    "drainage", "reservoir", "aqueduct", "spillway", "dam", "culvert", "intake",
    "sluice", "headwall", "bedrock", "granite", "schist", "outcrop", "escarpment",
    "moraine", "talus", "scree", "pass", "col", "crevasse", "ridgepole",
    "shelter", "bunkhouse", "timber", "beam", "stone", "slate", "shingle",
    "insulation", "ventilation", "hearth", "chimney", "cupola", "belfry",
    "balcony", "stairway", "lintel", "threshold", "hallway", "vestibule",
    "alcove", "depot", "cache", "storehouse", "pantry", "cistern", "conduit",
    "pipeline", "generator", "turbine", "dynamo", "battery", "inverter",
    "circuit", "cable", "insulator", "radiator", "vent", "flue", "sensor",
    "detector", "recorder", "gauge", "barometer", "hygrometer", "compass",
    "transit", "level", "theodolite", "quadrant", "sextant", "chronometer",
    "spectrograph", "mirror", "lens", "prism", "grating", "collimator",
    "mount", "pedestal", "pier", "dome", "shutter", "slit", "aperture",
    "zenith", "nadir", "meridian", "azimuth", "horizon", "constellation",
    "nebula", "cluster", "galaxy", "stellar", "solar", "lunar", "planetary",
    "orbital", "eclipse", "radiation", "spectrum", "emission", "absorption",
    "continuous", "diffuse", "faint", "distant", "ancient", "remote",
    "isolated", "rugged", "lofty", "windswept", "serene", "tranquil",
    "verdant", "arid", "alpine", "riparian", "boreal", "temperate",
    "maritime", "continental", "polar", "tundra", "steppe", "prairie",
    "woodland", "thicket", "grove", "copse", "spinney", "canopy",
    "understory", "fern", "moss", "lichen", "sedge", "rush", "willow",
    "alder", "birch", "pine", "spruce", "fir", "larch", "hemlock",
    "cedar", "juniper", "yew", "oak", "beech", "ash", "elm", "maple",
    "hazel", "rowan", "hawthorn", "blackthorn", "heather", "gorse", "bracken",
]

PAGE_SPECS = {
    "orrin": {
        "title": "Orrin Ridge Observatory",
        "headings": [
            "Geographic Setting and Topography",
            "Primary Instrumentation and Optical Systems",
            "Atmospheric and Environmental Monitoring",
            "Observational Surveys and Astronomical Data",
            "Infrastructure and Utility Support",
        ],
        "facts": [
            ("primary mirror diameter", "4.7 metres", "The Kaelis reflector telescope has a primary mirror diameter of 4.7 metres."),
            ("Sylvanus spectrograph", "82 granite pillars", "The foundation of the Sylvanus spectrograph resting frame is anchored by 82 granite pillars."),
            ("Morven observation ridge", "163 kilometres per hour", "The weather station at the Morven observation ridge recorded a peak wind velocity of 163 kilometres per hour."),
            ("Alden infrared sensor", "14 Kelvin", "The Alden infrared sensor operates at an extreme baseline temperature of 14 Kelvin."),
            ("Brannoc solar patrol", "529 solar flares", "The Brannoc solar patrol documented 529 solar flares during the winter observation cycle."),
            ("Vespera utility station", "750 kilowatts", "The auxiliary backup generator at the Vespera utility station provides 750 kilowatts of power."),
        ],
        "seed": 101,
    },
    "vale": {
        "title": "Vale River Basin Authority",
        "headings": [
            "Hydrological Overview and Catchment Geography",
            "Spillway Engineering and Water Management",
            "Aquatic Ecology and Water Quality Monitoring",
            "Navigation Canals and Wetland Conservation",
            "Hydroelectric Power and Regional Utilities",
        ],
        "facts": [
            ("Caldera reservoir spillway", "1250 cubic metres per second", "The Caldera reservoir spillway has a maximum discharge capacity of 1250 cubic metres per second."),
            ("Rendall fish ladder", "38 stepped pools", "The Rendall fish ladder spans a continuous vertical gradient across 38 stepped pools."),
            ("Elidon monitoring station", "94 points", "Water purity testing at the Elidon monitoring station showed an overall quality index of 94 points."),
            ("Corran navigation canal", "6.2 metres", "The Corran navigation canal maintains an average channel depth of 6.2 metres along its transit route."),
            ("Fintan delta", "410 hectares", "The wetland conservation area across the Fintan delta protects 410 hectares of coastal marshland."),
            ("Marlock barrage", "27 intake turbines", "The hydroelectric powerhouse at Marlock barrage contains 27 intake turbines."),
        ],
        "seed": 202,
    },
    "tarn": {
        "title": "Tarn Alpine Refuge",
        "headings": [
            "High Alpine Geography and Access Routes",
            "Shelter Architecture and Accommodation",
            "Safety Logistics and Emergency Supplies",
            "Passage Ways and Mountain Crossings",
            "Off Grid Energy and Resource Storage",
        ],
        "facts": [
            ("Brecart ridge", "3100 metres", "The high mountain refuge at Brecart ridge is situated at an elevation of 3100 metres above sea level."),
            ("Dunreay shelter", "48 timber bunks", "The central dormitory building at the Dunreay shelter contains 48 timber bunks for guests."),
            ("Helvorn safety cache", "185 stranded travellers", "Emergency supplies kept inside the Helvorn safety cache can support 185 stranded travellers."),
            ("Torran gorge", "72 metres", "The footbridge crossing above the Torran gorge spans a total distance of 72 metres."),
            ("Kinloch cabin", "19 kilowatts", "The solar thermal collector array mounted on the Kinloch cabin produces 19 kilowatts of heating."),
            ("Scarva pass", "3.5 kilolitres", "The rainwater storage reservoir beside Scarva pass has a total capacity of 3.5 kilolitres."),
        ],
        "seed": 303,
    },
}

# Module-level FACTS table: slug -> list of {"key": ..., "value": ...}
FACTS: dict[str, list[dict[str, str]]] = {
    slug: [{"key": f[0], "value": f[1]} for f in spec["facts"]]
    for slug, spec in PAGE_SPECS.items()
}

# Exact fact sentences for each slug, for tests or verification
FACT_SENTENCES: dict[str, list[str]] = {
    slug: [f[2] for f in spec["facts"]]
    for slug, spec in PAGE_SPECS.items()
}

PAGE_TITLES: dict[str, str] = {
    slug: spec["title"] for slug, spec in PAGE_SPECS.items()
}


def _build_html_pages(filler_sentences_per_p: int = 4) -> dict[str, str]:
    pages = {}
    for slug, spec in PAGE_SPECS.items():
        rng = random.Random(spec["seed"])
        title = spec["title"]
        headings = spec["headings"]
        facts = spec["facts"]

        def make_filler():
            sentences = []
            for _ in range(filler_sentences_per_p):
                length = rng.randint(10, 16)
                words = [rng.choice(FILLER_WORDS) for _ in range(length)]
                sentences.append(" ".join(words).capitalize() + ".")
            return " ".join(sentences)

        paragraphs = [
            make_filler(),
            facts[0][2],
            make_filler(),
            make_filler(),
            facts[1][2],
            make_filler(),
            make_filler(),
            facts[2][2],
            make_filler(),
            make_filler(),
            make_filler(),
            facts[3][2],
            make_filler(),
            make_filler(),
            facts[4][2],
            make_filler(),
            make_filler(),
            facts[5][2],
            make_filler(),
            make_filler(),
        ]

        html_parts = [
            '<!doctype html>\n<html lang="en">\n<head>\n  <meta charset="utf-8">\n'
            f"  <title>{title}</title>\n</head>\n<body>\n  <h1>{title}</h1>\n"
        ]
        h_idx = 0
        for i, p in enumerate(paragraphs):
            if i % 4 == 0 and h_idx < len(headings):
                html_parts.append(f"  <h2>{headings[h_idx]}</h2>\n")
                h_idx += 1
            html_parts.append(f"  <p>{p}</p>\n")
        html_parts.append("</body>\n</html>\n")
        pages[slug] = "".join(html_parts)
    return pages


PAGE_HTML = _build_html_pages()
PAGE_BYTES = {slug: html.encode("utf-8") for slug, html in PAGE_HTML.items()}


def _search_pages(query: str, base_url: str) -> dict:
    query_words = [w.lower() for w in re.findall(r"\w+", query) if w]
    slug_order = ["orrin", "vale", "tarn"]
    scored = []
    for slug in slug_order:
        spec = PAGE_SPECS[slug]
        searchable = (spec["title"] + " " + " ".join(f[2] for f in spec["facts"])).lower()
        score = sum(1 for w in query_words if w in searchable) if query_words else 0
        scored.append((score, slug))

    scored.sort(key=lambda item: (-item[0], slug_order.index(item[1])))
    results = []
    for _score, slug in scored:
        title = PAGE_SPECS[slug]["title"]
        results.append({
            "title": title,
            "url": f"{base_url}/pages/{slug}",
            # Never a fact: a task must fetch the page to answer, not read it off the search result.
            "content": f"{title}. Reference page with background, measurements and notes.",
        })
    return {"results": results}


class FakeWebHandler(BaseHTTPRequestHandler):
    """Deterministic HTTP request handler for pages and search."""

    def date_time_string(self, timestamp: float | None = None) -> str:
        # Fixed RFC 1123 date string to ensure responses are byte-identical across runs.
        return "Thu, 01 Jan 2026 00:00:00 GMT"

    def log_message(self, *args: object) -> None:
        # Suppress logging to disk and stdout.
        pass

    def _send(self, status: int, content_type: str, body: bytes) -> None:
        self.send_response_only(status)
        self.send_header("Server", "FakeWeb/1.0")
        self.send_header("Date", self.date_time_string())
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        url = urlparse(self.path)
        path = url.path.rstrip("/")

        if path.startswith("/pages/"):
            slug = path[len("/pages/"):]
            if slug in PAGE_BYTES:
                self._send(200, "text/html; charset=utf-8", PAGE_BYTES[slug])
                return
            self._send(404, "text/plain; charset=utf-8", b"Not Found\n")
            return

        if path == "/search":
            qs = parse_qs(url.query)
            q = qs.get("q", [""])[0]
            port = self.server.server_address[1]
            base_url = f"http://{HOST}:{port}"
            res = _search_pages(q, base_url)
            data = json.dumps(res, indent=2).encode("utf-8")
            self._send(200, "application/json; charset=utf-8", data)
            return

        self._send(404, "text/plain; charset=utf-8", b"Not Found\n")


class ThreadedHTTPServer(socketserver.ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start(port: int = 0) -> tuple[HTTPServer, str]:
    """Start fake web server in a background daemon thread and return (server, base_url)."""
    server = ThreadedHTTPServer((HOST, port), FakeWebHandler)
    actual_port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://{HOST}:{actual_port}"


if __name__ == "__main__":
    port_arg = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    server_inst = ThreadedHTTPServer((HOST, port_arg), FakeWebHandler)
    print(f"FakeWeb running on http://{HOST}:{server_inst.server_address[1]}. Press Ctrl-C to stop.", flush=True)
    try:
        server_inst.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping FakeWeb...")
    finally:
        server_inst.shutdown()
        server_inst.server_close()
