"""
Fixture for the first-contact eval (#100): a device the model knows nothing about.

`reef` is an invented box ("ReefOS", a shell called reefsh) behind a fake `ssh` program on PATH, so nothing real is
contacted. It has none of the usual commands (netstat, arp, ip, cat of a lease file): the connected devices come
from its own `clients` command, which only `help` reveals. The pass check reads what really ran (the harness's
action list), not only the spoken answer.

Importable:
  from tests.probe_fixture import build, PROMPT
  case = build(tmp_dir)   # writes tmp_dir/bin/ssh, tmp_dir/notes.md; puts bin first on PATH
"""

from dataclasses import dataclass
import os
from pathlib import Path
import stat

PROMPT = "How many devices are connected to the reef box right now?"
CLIENTS = 7
NOTES = "# notes\n\n- reef: ssh admin@10.9.9.9\n  A small network box in the cabin.\n"
FAKE_SSH = f"""#!/bin/sh
# Fake ssh: the command is the last argument. Only what ReefOS has works.
cmd="$(eval echo \\"\\${{$#}}\\")"
case "$cmd" in
  "uname -a"|uname) echo "ReefOS 3.1 reef-box aarch64 reefsh" ;;
  "cat /etc/os-release") echo 'NAME="ReefOS"'; echo 'VERSION="3.1"' ;;
  help) echo "reefsh commands:"; echo "  clients   list connected devices"; echo "  uptime    show uptime"; echo "  wifi      show radio status"; echo "  help      this text" ;;
  clients) echo "NAME        ADDRESS"; for i in 1 2 3 4 5 6 {CLIENTS}; do echo "device$i   10.9.9.$((10+i))"; done ;;
  uptime) echo "up 12 days" ;;
  wifi) echo "radio 1: on, channel 6" ;;
  *) echo "reefsh: ${{cmd%% *}}: not found" >&2; exit 127 ;;
esac
"""


@dataclass
class Case:
    prompt: str
    expects: list[str]


def confirm(desc: str) -> bool:
    """Scripted answers: yes to commands on the reef box, no to anything else."""
    return desc.startswith("Run on reef (admin@10.9.9.9) over ssh:")


def check(actions: list[str]) -> tuple[bool, str]:
    """Pass only if the box's own client list really ran: a right number from a guess does not count."""
    ran = any(a.startswith("ssh reef exit 0: clients") for a in actions)
    return ran, "" if ran else "never ran `clients` on the box"


def build(tmp: Path) -> Case:
    bin_dir = tmp / "bin"
    bin_dir.mkdir(parents=True)
    ssh = bin_dir / "ssh"
    ssh.write_text(FAKE_SSH)
    ssh.chmod(ssh.stat().st_mode | stat.S_IXUSR)
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{os.environ['PATH']}"
    (tmp / "notes.md").write_text(NOTES)
    return Case(PROMPT, [rf"\b(?:{CLIENTS}|seven)\b"])
