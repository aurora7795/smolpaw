# SmolPaw notes

Copy this file to notes.md (gitignored). Keep it short: everything here is inlined into every model call.

## User facts
Key preferences that shape answers (time zone, units, etc.). Keep to 2-3 lines:
- timezone: Europe/London
- units: metric (Celsius, km)
- owner: Martin

## Services
Services you can reach. API keys are added to requests for these hosts automatically.
Format: `- name: URL | key_env=ENV_VAR | header=Header-Name`
The harness adds the key from .env to requests for these hosts. Never put keys here.

- radarr: http://192.168.1.50:7878 | key_env=RADARR_API_KEY | header=X-Api-Key
  Movie library manager.
