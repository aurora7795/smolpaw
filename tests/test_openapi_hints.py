"""
Tests for the write hints in openapi_search (#112): a POST/PUT/PATCH hit lists its id-like and path-like body fields
beside the GET endpoint that supplies them. Run with: .venv/bin/python tests/test_openapi_hints.py
"""

import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).parent.parent))

import generic_tools as g  # noqa: E402
from tests import eval as ev  # noqa: E402

g.LOG_DIR = Path(tempfile.mkdtemp()) / "logs"
failed = 0


def check(name: str, cond: bool) -> None:
    global failed
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        failed += 1


def spec(body_props: dict | None, extra_paths: dict | None = None, inline: bool = False) -> dict:
    schema = {"type": "object", "properties": body_props or {}}
    body = {"content": {"application/json": {"schema": schema if inline else {"$ref": "#/components/schemas/Thing"}}}}
    return {"paths": {
        "/api/things": {"get": {"summary": "List things"}, "post": {"summary": "Add a thing", "requestBody": body}},
        "/api/things/lookup": {"get": {"summary": "Find things"}},
        "/api/things/lookup/ext": {"get": {"summary": "Find by external id"}},
        "/api/colourschemes": {"get": {"summary": "List"}},
        "/api/vaults": {"get": {"summary": "List"}},
        "/api/vaults/{id}": {"get": {"summary": "One"}},
        **(extra_paths or {}),
    }, "components": {"schemas": {"Thing": schema}}}


def search(s: dict, kw: str = "things") -> str:
    g._SPECS["t"] = s
    return g.openapi_search("t", kw)


props = {"name": {}, "ext": {}, "colourSchemeId": {}, "vaultPath": {}, "owner": {}, "id": {}, "ownerId": {}, "x": {}}
out = search(spec(props, inline=False))
check("a body field named *Id with a matching list endpoint is shown beside it", "colourSchemeId <- GET /api/colourschemes" in out)
check("a *Path field is matched on its stem", "vaultPath <- GET /api/vaults" in out)
check("fields that do not look like ids or paths are left out", "name <-" not in out and "owner <-" not in out and "x <-" not in out)
check("an id-like field with no matching endpoint is left out", "ownerId" not in out)
check("a bare id field is not matched on nothing", " id <-" not in out and "; id <-" not in out)
check("a hit that is not a write gets no hint", out.splitlines()[0].startswith("GET /api/things") and "Fill" not in out.splitlines()[0])
check("an inline body schema works as well as a $ref", "colourSchemeId <- GET" in search(spec(props, inline=True)))
check("a lookup/<x> endpoint is shown as the lookup endpoint", "extId <- GET /api/things/lookup;" in search(spec({"extId": {}}))
      or "extId <- GET /api/things/lookup" in search(spec({"extId": {}})))
check("a write with no body schema gets no hint", "Fill from a GET" not in search(spec(None)))
bad = spec(props)
bad["paths"]["/api/things"]["post"]["requestBody"]["content"]["application/json"]["schema"] = {"$ref": "#/components/schemas/Missing"}
check("an unresolvable $ref is skipped, not an error", "Fill from a GET" not in search(bad))
many = {f"{n}Id": {} for n in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa")}
extra = {f"/api/{n}": {"get": {"summary": "List"}} for n in ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta", "iota", "kappa")}
line = [l for l in search(spec(many, extra)).splitlines() if "Fill from a GET" in l][0]
check("at most eight fields are listed", line.count(" <- GET ") == 8)
three = spec(props)
for i in range(5):
    three["paths"][f"/api/things/w{i}"] = {"put": {"summary": "Update a thing", "requestBody": three["paths"]["/api/things"]["post"]["requestBody"]}}
check("only the first three write hits carry a hint", search(three).count("Fill from a GET") == 3)

g.WRITE_HINTS = False
check("the switch turns the hints off", "Fill from a GET" not in search(spec(props)))
g.WRITE_HINTS = True

withparam = spec({"colourSchemeId": {}})
withparam["paths"]["/api/colourschemes"]["get"]["parameters"] = [{"name": "term", "in": "query"}, {"name": "limit", "in": "query"}]
check("the first query parameter of the GET is shown", "colourSchemeId <- GET /api/colourschemes?term=" in search(withparam))
header = spec({"colourSchemeId": {}})
header["paths"]["/api/colourschemes"]["get"]["parameters"] = [{"name": "X-Key", "in": "header"}]
check("a header or path parameter is not shown", "colourSchemeId <- GET /api/colourschemes\n" in search(header) + "\n")

# end to end: the fake Radarr's own spec, served over HTTP
port = ev.free_port()
url = f"http://127.0.0.1:{port}"
srv = subprocess.Popen([sys.executable, str(Path(__file__).parent / "fake_radarr.py"), str(port)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(50):
        try:
            requests.get(url, timeout=1)
            break
        except requests.RequestException:
            time.sleep(0.1)
    out = g.openapi_search(f"{url}/api/v3/openapi.json", "movie")
    check("the fake Radarr's spec names the lookup, profile and folder endpoints beside the add",
          "tmdbId <- GET /api/v3/movie/lookup?term=" in out and "qualityProfileId <- GET /api/v3/qualityprofile" in out
          and "rootFolderPath <- GET /api/v3/rootfolder" in out)
finally:
    srv.terminate()

# forgiving queries (#117): a method word filters, "add" means POST, an empty result points at real path words
s2 = spec(props)
out = search(s2, "POST /api/things")
check("a query with a method and a path finds that write", out.startswith("POST /api/things") and "GET /api/things" not in out)
check("a method alone lists nothing and points at path words", "No matching endpoints" in search(s2, "POST") and "things" in search(s2, "POST"))
check("add means POST", search(s2, "add things").startswith("POST /api/things"))
check("a word nowhere in the spec lists real path words", "vaults" in search(s2, "ThingResource"))
check("the shorter path comes first", search(s2, "things").splitlines()[0].endswith("List things"))
g.SEARCH_RANK = False
check("with the switch off an unmatched query is a plain miss", search(s2, "POST /api/things") == "No matching endpoints.")
g.SEARCH_RANK = True

print(f"\n{failed} failed")
sys.exit(1 if failed else 0)
