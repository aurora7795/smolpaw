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

- myservice: http://192.168.1.50:8080 | key_env=MYSERVICE_API_KEY | header=X-Api-Key
  One line on what it is, for example "home media library manager".

## Devices
Devices the ssh_run tool can log into (a router, a NAS). Every command asks you first; the password is read from the named variable (save it under Settings > Secrets, or in .env), so the model never sees it.
Format: `- name: ssh user@host | pass_env=ENV_VAR | port=22` (leave out pass_env to log in with an ssh key, port is optional)

- router: ssh admin@192.168.1.1 | pass_env=ROUTER_PASS
  One line on what it is and what is safe to run, for example "home router; read-only commands only".
