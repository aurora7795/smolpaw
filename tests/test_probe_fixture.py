"""
Tests for the first-contact eval fixture (tests/probe_fixture.py, #100) and the ssh_run probe wording.
Run with: .venv/bin/python tests/test_probe_fixture.py

Uses a temporary directory and a fake `ssh` on PATH; contacts nothing and touches no real files.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generic_tools as g  # noqa: E402
from tests import probe_fixture as pf  # noqa: E402

tmp = Path(tempfile.mkdtemp())
old_path = os.environ["PATH"]
case = pf.build(tmp)


def check(name: str, cond: bool) -> None:
    print(f"{'PASS' if cond else 'FAIL'}  {name}")
    if not cond:
        check.failed += 1


check.failed = 0


def ssh(cmd: str) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", "-o", "BatchMode=yes", "admin@10.9.9.9", cmd], capture_output=True, text=True)


check("the usual tools are missing on the box", all(ssh(c).returncode == 127 for c in ("netstat -an", "arp -a", "ip neigh", "cat /tmp/dhcp.leases")))
check("uname and help work, and help names the client command", "ReefOS" in ssh("uname -a").stdout and "clients" in ssh("help").stdout)
check("clients lists the expected number of devices", ssh("clients").stdout.count("device") == pf.CLIENTS)
check("the notes line parses as a device", g.DEVICE_LINE.match("- reef: ssh admin@10.9.9.9") is not None)
check("confirm says yes to the box and no to anything else",
      pf.confirm("Run on reef (admin@10.9.9.9) over ssh:\n  help") and not pf.confirm("Run shell command in workspace/\n  ls"))
check("the check needs the clients command to have run", pf.check(["ssh reef exit 0: help"])[0] is False
      and pf.check(["ssh reef exit 0: clients"])[0] is True and pf.check(["ssh reef exit 127: clients"])[0] is False)
check("the expected answer matches 7 and seven, not 17 or 70",
      all(re.search(case.expects[0], t) for t in ("There are 7", "seven")) and not any(
          re.search(case.expects[0], t) for t in ("17 devices", "70")))
check("ssh_run tells the model to probe an unknown device first", "uname -a" in (g.ssh_run.description or "") and "help" in g.ssh_run.description)

os.environ["PATH"] = old_path
print(f"\n{check.failed} failed")
sys.exit(1 if check.failed else 0)
