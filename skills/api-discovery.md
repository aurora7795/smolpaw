# API discovery: how to learn an unfamiliar web API

Use when a service in notes.md has a URL but you do not know its endpoints.

1. Use http_request for web services. Never run the service name as a shell command.
2. The API key is added for you. Never put a key or a placeholder like YOUR_API_KEY in a URL or body: a fake key causes a 401.
3. Try GET <base>/api. It often returns the API version, e.g. {"current": "v3"}, so endpoints live under /api/v3/.
4. Do not guess endpoint names. Find them with openapi_search(spec_url, keyword), e.g. keyword "queue".
   Pages like /swagger and /docs return web-page HTML, not the spec: ignore them.
5. Known specs (OpenAPI JSON):
   - Radarr: https://raw.githubusercontent.com/Radarr/Radarr/develop/src/Radarr.Api.V3/openapi.json
6. Call a GET endpoint first and read the status code:
   - 200: read the JSON and answer from it.
   - 401: key problem. Check you did not add a key yourself. Do not ask the user for it.
   - 404: wrong path. Search the spec again with another keyword.
7. Report exactly what the response said. If a call fails, say so.
