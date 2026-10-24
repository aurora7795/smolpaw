# SmolPaw notes

Copy this file to notes.md (gitignored) and list only the services a task needs.
Format: `- name: URL | key_env=ENV_VAR | header=Header-Name`
The harness adds the key from .env to requests for these hosts. Never put keys here.

- radarr: http://192.168.1.50:7878 | key_env=RADARR_API_KEY | header=X-Api-Key
  Movie library manager.
