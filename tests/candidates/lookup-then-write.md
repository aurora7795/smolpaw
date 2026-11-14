# Writing to a service: look up, then write

Use before any POST, PUT or DELETE to a service in notes.md (add, create, update, remove).

1. Find the write endpoint with openapi_search. Also search the spec for "lookup" and "search".
2. Find the thing by name with a GET (a lookup or search endpoint, or the list). Copy its id fields from the result. Never type an id from memory.
3. GET every list the write needs, such as profiles or folders. Take the values from the result. Do not ask the user for them.
4. Only then send the write, using only values you read in steps 2 and 3.
