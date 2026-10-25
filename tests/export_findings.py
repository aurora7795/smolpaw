"""
Bundle every run log in logs/ into one readable Markdown report, for sending exploratory
testing findings to someone else (for example, a second person testing on their own machine).

Each agent.run() writes one logs/<timestamp>-<model>.jsonl file (see generic_tools.start_log),
already secret-redacted as it is written. This just reads them back and renders each one as a
short, chronological summary: prompt, every shell/http/confirm/ask/openapi_search action, the
final answer and what the harness says actually happened.

  .venv/bin/python tests/export_findings.py                  # all logs, written to findings.md
  .venv/bin/python tests/export_findings.py --since 2026-10-25 --out today.md
  .venv/bin/python tests/export_findings.py --stdout          # print instead of writing a file
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"


def _line(e: dict) -> str:
    t, kind = e.get("t", "")[11:19], e.get("kind")
    if kind == "shell":
        return f"- {t} `$ {e.get('command')}` (exit {e.get('exit')})"
    if kind == "http":
        return f"- {t} `{e.get('method')} {e.get('url')}` -> {e.get('status')}"
    if kind == "preflight":
        return f"- {t} refused before sending: `{e.get('method')} {e.get('url')}` ({e.get('reason')})"
    if kind == "confirm":
        first = (str(e.get("desc", "")).splitlines() or [""])[0]
        return f"- {t} asked: {first} -> {'yes' if e.get('approved') else 'no'}"
    if kind == "ask":
        return f"- {t} question: {e.get('question')}  \n  answer: {e.get('answer')}"
    if kind == "read_file":
        return f"- {t} `read_file` {e.get('path')} -> {e.get('result')}"
    if kind == "write_file":
        return f"- {t} `write_file` {e.get('path')} ({e.get('chars')} chars) -> {e.get('result')}"
    if kind == "list_skills":
        return f"- {t} `list_skills` -> {e.get('result')}"
    if kind == "read_skill":
        return f"- {t} `read_skill` {e.get('name')} -> {e.get('result')}"
    if kind == "write_skill":
        return f"- {t} `write_skill` {e.get('name')} ({e.get('chars')} chars) -> {e.get('result')}"
    if kind == "openapi_search":
        return f"- {t} `openapi_search` {e.get('spec_url')} {e.get('keyword') or '(no keyword)'} -> {e.get('result')}"
    if kind == "fetch_page":
        return f"- {t} `fetch_page` {e.get('url')} {e.get('query') or '(no query)'} -> {e.get('result')}"
    if kind == "remember":
        return f"- {t} `remember` {e.get('fact')}"
    if kind == "recall":
        return f"- {t} `recall` {e.get('query') or '(all)'} -> {e.get('result')}"
    return None


def render(path: Path) -> str | None:
    entries = []
    for raw in path.read_text().splitlines():
        try:
            entries.append(json.loads(raw))
        except json.JSONDecodeError:
            continue
    start = next((e for e in entries if e.get("kind") == "start"), None)
    final = next((e for e in entries if e.get("kind") == "final"), None)
    if not start:
        return None
    lines = [_line(e) for e in entries if e.get("kind") not in ("start", "final")]
    duration = ""
    if final and start:
        try:
            d = (datetime.fromisoformat(final["t"]) - datetime.fromisoformat(start["t"])).total_seconds()
            duration = f"{d:.0f}s"
        except (KeyError, ValueError):
            pass
    out = [f"## {path.stem}", "", f"**Model:** {start.get('model')}  ", f"**Prompt:** {start.get('prompt')}", ""]
    out += [ln for ln in lines if ln] or ["(no actions)"]
    out.append("")
    if final:
        out.append(f"**Answer:**\n> {str(final.get('answer', '')).replace(chr(10), chr(10) + '> ')}")
        if final.get("actions"):
            out.append("\n**Harness says:**")
            out += [f"- {a}" for a in final["actions"]]
        if duration:
            out.append(f"\n**Duration:** {duration} · **Actions logged:** {len(lines)}")
    else:
        out.append("*(run did not finish — no final answer logged)*")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--since", help="only logs from this date or later, e.g. 2026-10-25")
    ap.add_argument("--out", default="findings.md", help="output file (default: findings.md)")
    ap.add_argument("--stdout", action="store_true", help="print the report instead of writing a file")
    args = ap.parse_args()

    if not LOG_DIR.exists():
        print("No logs/ directory yet — run the agent at least once first.")
        sys.exit(1)
    files = sorted(LOG_DIR.glob("*.jsonl"))
    if args.since:
        files = [f for f in files if f.name >= args.since]
    if not files:
        print("No matching run logs found.")
        sys.exit(1)

    reports = [r for r in (render(f) for f in files) if r]
    header = f"# SmolPaw exploratory findings\n\n{len(reports)} run(s), generated {datetime.now():%Y-%m-%d %H:%M}.\n\n"
    text = header + "\n\n---\n\n".join(reports) + "\n"

    if args.stdout:
        print(text)
    else:
        Path(args.out).write_text(text)
        print(f"Wrote {args.out} ({len(reports)} runs).")


if __name__ == "__main__":
    main()
