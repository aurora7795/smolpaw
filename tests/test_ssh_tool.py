"""
Tests for the ssh_run tool and the devices lines in notes.md.
Run with: .venv/bin/python tests/test_ssh_tool.py

Uses fake `ssh` and `sshpass` programs on a temporary PATH, a temporary notes.md, workspace and logs; it never
connects to anything and never touches the real notes.md, .env or logs/.
"""

import os
import stat
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generic_tools as g  # noqa: E402
import secret_store  # noqa: E402

tmp = Path(tempfile.mkdtemp())
g.NOTES = tmp / "notes.md"
secret_store.PATH = tmp / ".env"  # not the real one: its saved names would also mask the password
g.LOG_DIR = tmp / "logs"
g.WORKSPACE = tmp / "workspace"
g.WORKSPACE.mkdir()
bin_dir = tmp / "bin"
bin_dir.mkdir()
record = tmp / "record.txt"
PW = "hunter2-router"


def check(name: str, cond: bool) -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check.failed += 1


check.failed = 0


def make_bin(name: str, body: str) -> None:
    f = bin_dir / name
    f.write_text("#!/bin/sh\n" + body)
    f.chmod(f.stat().st_mode | stat.S_IEXEC)


# sshpass -e ssh ...: record what it was given, then run the real command line with the -e dropped.
make_bin("sshpass", f'echo "sshpass argv: $@" >> {record}\necho "sshpass SSHPASS: $SSHPASS" >> {record}\nshift\nexec "$@"\n')
# ssh: record argv, leak the password on purpose into stdout, fail when asked to.
make_bin("ssh", f'echo "ssh argv: $@" >> {record}\n'
                'for last; do :; done\n'
                'if [ "$last" = "fail" ]; then echo "Permission denied" >&2; exit 255; fi\n'
                'echo "up 3 days; login was $SSHPASS"\n')
os.environ["PATH"] = f"{bin_dir}:{os.environ['PATH']}"

prompts: list[str] = []
answer = {"v": True}
g.CONFIRM = lambda desc: (prompts.append(desc), answer["v"])[1]

os.environ["ROUTER_PASS"] = PW

# --- parsing --------------------------------------------------------------------------

g.NOTES.write_text("""# notes
- radarr: http://192.168.1.30:7878 | key_env=RADARR_API_KEY
  a service
- router: ssh admin@192.168.1.1 | pass_env=ROUTER_PASS | port=2222
  home router
- nas: ssh pi@nas.local
- bad1: ssh -oProxyCommand=x@host
- bad2: ssh user@-oProxyCommand
- bad3: ssh user@host name | pass_env=lower
- bad4: ssh user@host | port=99999
""")
d = g.devices()
check("a device line is parsed", d["router"] == {"user": "admin", "host": "192.168.1.1", "pass_env": "ROUTER_PASS", "port": "2222"})
check("a device without pass_env logs in with a key", d["nas"] == {"user": "pi", "host": "nas.local"})
check("a service line is not a device and a device line is not a service", "radarr" not in d and "router" not in g.services())
check("an option cannot be smuggled in through the user or host", "bad1" not in d and "bad2" not in d and "bad3" not in d)
check("a bad variable name or port is dropped, the device stays", d.get("bad4") == {"user": "user", "host": "host"})

# --- offered only when there is a device ------------------------------------------------

before = [t.name for t in g.GENERIC_TOOLS if t is not g.ssh_run]
check("with a device, apply_devices offers ssh_run", g.apply_devices() is True and g.ssh_run in g.GENERIC_TOOLS)
check("offering it twice adds it once", g.apply_devices() and g.GENERIC_TOOLS.count(g.ssh_run) == 1)
g.NOTES.write_text("# notes\n- radarr: http://h:1\n")
check("with no device it is removed again", g.apply_devices() is False and g.ssh_run not in g.GENERIC_TOOLS)
check("and the other tools are exactly as before", [t.name for t in g.GENERIC_TOOLS] == before)
g.NOTES.unlink()
check("with no notes.md at all it is not offered", g.apply_devices() is False and g.ssh_run not in g.GENERIC_TOOLS)

# --- running it ---------------------------------------------------------------------------

g.NOTES.write_text("- router: ssh admin@192.168.1.1 | pass_env=ROUTER_PASS | port=2222\n- nas: ssh pi@nas.local\n")
g.start_log("m", "check the router")
out = g.ssh_run("router", "uptime")
rec = record.read_text()
check("the user is asked first, with the device, login and command but no password",
      len(prompts) == 1 and "router" in prompts[0] and "admin@192.168.1.1" in prompts[0] and "uptime" in prompts[0]
      and PW not in prompts[0])
check("it goes through sshpass -e and ssh with the destination, port and command as separate arguments",
      "sshpass argv: -e ssh" in rec and "-p 2222 admin@192.168.1.1 uptime" in rec)
check("the password is in sshpass's environment only, on no command line", f"SSHPASS: {PW}" in rec
      and all(PW not in line for line in rec.splitlines() if "argv" in line))
check("it asks for the host key on first contact and gives up after one password try",
      "StrictHostKeyChecking=accept-new" in rec and "NumberOfPasswordPrompts=1" in rec and "ConnectTimeout=10" in rec)
check("the result shows the exit code and output", "exit code 0" in out and "up 3 days" in out)
check("the password is masked even when the device echoes it back", PW not in out and "[REDACTED]" in out)
logs = "".join(f.read_text() for f in g.LOG_DIR.glob("*.jsonl"))
check("the run log has the ssh entry and never the password", '"kind": "ssh"' in logs and PW not in logs)
check("the outcome is recorded for the harness summary", any("ssh router exit 0: uptime" in a for a in g.ACTIONS))

record.write_text("")
out = g.ssh_run("router", "fail")
check("a failed login is reported with its exit code and message", "exit code 255" in out and "Permission denied" in out)

answer["v"] = False
record.write_text("")
out = g.ssh_run("router", "reboot")
check("a declined command is not run", out == g.DECLINED and record.read_text() == "")
answer["v"] = True

prompts.clear()
record.write_text("")
g.ssh_run("nas", "df -h")
rec = record.read_text()
check("a device with no pass_env uses ssh alone, in batch mode, with no sshpass",
      "sshpass" not in rec and "BatchMode=yes" in rec and "pi@nas.local df -h" in rec)

prompts.clear()
check("an unknown device is refused with the known names, without asking",
      "unknown device" in g.ssh_run("printer", "ls") and "router" in g.ssh_run("printer", "ls") and not prompts)
check("an empty or huge command is refused without asking",
      g.ssh_run("router", "  ").startswith("ERROR") and g.ssh_run("router", "x" * 2001).startswith("ERROR") and not prompts)
del os.environ["ROUTER_PASS"]
check("a missing password variable is an error that points to Settings > Secrets and asks nothing",
      "ROUTER_PASS is not set" in g.ssh_run("router", "uptime") and "Secrets" in g.ssh_run("router", "uptime") and not prompts)
os.environ["ROUTER_PASS"] = PW
os.environ["PATH"] = str(tmp / "empty")
check("a missing sshpass is an error and asks nothing", "sshpass is not installed" in g.ssh_run("router", "uptime") and not prompts)

# --- masking in general ---------------------------------------------------------------------

check("a device password is masked in any tool output, not only ssh_run", g._redact(f"x {PW} y") == "x [REDACTED] y")

print(f"\n{check.failed} failed")
sys.exit(1 if check.failed else 0)
