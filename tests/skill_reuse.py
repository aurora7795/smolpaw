"""
Rung 5 (#4): can a model write a useful skill from a discovery run, and does reusing it make the task cheaper?

Each trial, on an invented API (Tidepool) with an isolated, initially empty skills/ folder and its own notes:
  1. discovery run: the usual prompt; the only prompts answered "yes" are skill writes, everything else is "no";
  2. checks on the skill it wrote: written at all, no secrets, a recipe (no copy of the answer), names the API path;
  3. reuse run: the same prompt in a fresh agent that now has the skill inlined or listed.
The real skills/, notes.md and workspace/ are never touched. Read-only apart from the temp skill.

  .venv/bin/python tests/skill_reuse.py --backend ollama --model qwen3.5:9b --variant detail --n 3
"""

import argparse
import json
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import eval as ev  # noqa: E402
import generic_tools as g  # noqa: E402
from agent import BACKENDS, load_env  # noqa: E402

ANSWER = ("kestrel", "340")
ASK_FOR_SKILL = (" When you have the answer, save a short skill with write_skill describing how to find this kind of "
                 "answer in this service, so next time it is quicker.")


def skill_checks(skills: Path) -> dict:
    files = sorted(skills.glob("*.md")) if skills.exists() else []
    text = "\n".join(f.read_text() for f in files)
    low = text.lower()
    return {
        "written": bool(files),
        "names": [f.stem for f in files],
        "chars": len(text),
        "no_secrets": g._redact(text) == text,
        "no_answer_copied": not any(a in low for a in ANSWER),
        "names_api_path": "/v2/" in text,
        "text": text[:1500],
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="ollama")
    ap.add_argument("--model", required=True)
    ap.add_argument("--variant", default="detail")
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--ctx", type=int, default=16384)
    ap.add_argument("--no-load", action="store_true")
    ap.add_argument("--ask-for-skill", action="store_true",
                    help="add a sentence to the discovery prompt asking for a skill (otherwise only the standing "
                         "guidance in the system prompt suggests it)")
    args = ap.parse_args()

    load_env()
    tmp = Path(tempfile.mkdtemp())
    port = ev.free_port()
    server = subprocess.Popen([sys.executable, str(ev.ROOT / "tests/fake_api.py"), str(port), args.variant],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    url = f"http://127.0.0.1:{port}"
    (tmp / "notes.md").write_text(f"# notes\n\n- tidepool: {url}\n  Harbour logbook service. No API key needed.\n")
    g.NOTES = tmp / "notes.md"
    g.MEMORY = tmp / "memory.md"
    g.WORKSPACE = tmp / "workspace"
    g.WORKSPACE.mkdir()
    g.ASK = lambda q: "(no answer: nobody is at the keyboard. Do not ask again; make your best attempt.)"
    g.CONFIRM = lambda desc: desc.startswith(("Create skill", "Update skill"))
    prompt = ev.TIDEPOOL_PROMPT.format(url=url)
    expects = list(ANSWER)

    try:
        ctx = None if args.no_load else ev.ensure_model(args.model, args.ctx, args.backend)
        print(f"skill_reuse tidepool-{args.variant} | {args.backend}: {args.model} | loaded context {ctx} | n={args.n}")
        trials = []
        for i in range(1, args.n + 1):
            g.SKILLS = tmp / f"skills{i}"  # fresh, empty per trial
            discovery = ev.run_once(args.model, prompt + (ASK_FOR_SKILL if args.ask_for_skill else ""), expects, args.max_steps, args.backend)
            skill = skill_checks(g.SKILLS)
            reuse = ev.run_once(args.model, prompt, expects, args.max_steps, args.backend)
            trials.append({"discovery": discovery, "skill": skill, "reuse": reuse})
            ok = skill["written"] and skill["no_secrets"] and skill["no_answer_copied"] and skill["names_api_path"]
            print(f"  trial {i}: discovery {'PASS' if discovery['passed'] else 'FAIL'} {discovery['steps']} steps "
                  f"{discovery['wall_s']}s {discovery['input_tokens']} in | skill "
                  f"{'written' if skill['written'] else 'NOT written'} ({skill['chars']} chars, "
                  f"{'good' if ok else 'flawed'}) | reuse {'PASS' if reuse['passed'] else 'FAIL'} "
                  f"{reuse['steps']} steps {reuse['wall_s']}s {reuse['input_tokens']} in")
        n = len(trials)
        mean = lambda key, phase: sum(t[phase][key] for t in trials) / n  # noqa: E731
        print(f"  => skills written {sum(t['skill']['written'] for t in trials)}/{n} | "
              f"discovery {sum(t['discovery']['passed'] for t in trials)}/{n}, "
              f"{mean('steps', 'discovery'):.1f} steps, {mean('wall_s', 'discovery'):.0f}s, "
              f"{mean('input_tokens', 'discovery'):.0f} in | "
              f"reuse {sum(t['reuse']['passed'] for t in trials)}/{n}, "
              f"{mean('steps', 'reuse'):.1f} steps, {mean('wall_s', 'reuse'):.0f}s, "
              f"{mean('input_tokens', 'reuse'):.0f} in")
        out = ev.ROOT / "logs" / (f"skillreuse-{datetime.now():%Y%m%d-%H%M%S}-{args.backend}-"
                                  f"{ev.safe_name(args.model)}-{args.variant}{'-asked' if args.ask_for_skill else ''}.json")
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"backend": args.backend, "model": args.model, "variant": args.variant,
                                   "asked_for_skill": args.ask_for_skill, "loaded_context": ctx, "prompt": prompt, "trials": trials}, indent=2))
        print(f"  saved {out.relative_to(ev.ROOT)}")
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
