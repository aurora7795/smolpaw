"""
Cost of model-written run summaries (#47): extra seconds and tokens per summary, and the delay to a request
started while one is in flight (one model is loaded, so they compete).

Per trial, on the easy Tidepool task with an isolated workspace and notes (read-only, prompts answered "no"):
  1. run, then run again straight away                      -> "off": the second run's wall time and steps
  2. run, start a summary of its answer in a thread, and
     start the next run immediately                          -> "on": the second run's wall time and steps,
                                                                plus the summary call's seconds and tokens

  .venv/bin/python tests/summary_cost.py --backend ollama --model qwen3.5:9b --n 3
"""

import argparse
import json
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

import eval as ev  # noqa: E402
import generic_tools as g  # noqa: E402
import web  # noqa: E402
from agent import BACKENDS, build_agent, load_env  # noqa: E402


def timed_summary(model, prompt: str, answer: str, out: dict) -> None:
    """Run web.summarize_run against the real model, recording seconds and the model's token counts."""
    class Counting:
        """Wrap the model to read the token counts web.call_summary_model does not return."""
        def __call__(self, messages, **kw):
            msg = model(messages, **kw)
            usage = getattr(msg, "token_usage", None)
            out["input_tokens"] = getattr(usage, "input_tokens", None)
            out["output_tokens"] = getattr(usage, "output_tokens", None)
            return msg

    def call(text: str) -> str:
        return web.call_summary_model(Counting(), text)

    t0 = time.time()
    out["summary"] = web.summarize_run(prompt, answer, call)
    out["seconds"] = round(time.time() - t0, 1)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--backend", choices=sorted(BACKENDS), default="ollama")
    ap.add_argument("--model", required=True)
    ap.add_argument("--n", type=int, default=3)
    ap.add_argument("--max-steps", type=int, default=12)
    ap.add_argument("--ctx", type=int, default=16384)
    ap.add_argument("--no-load", action="store_true")
    args = ap.parse_args()

    load_env()
    tmp = Path(tempfile.mkdtemp())
    port = ev.free_port()
    server = subprocess.Popen([sys.executable, str(ev.ROOT / "tests/fake_api.py"), str(port), "easy"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    url = f"http://127.0.0.1:{port}"
    (tmp / "notes.md").write_text(f"# notes\n\n- tidepool: {url}\n  Harbour logbook service. No API key needed.\n")
    g.NOTES, g.MEMORY, g.SKILLS = tmp / "notes.md", tmp / "memory.md", tmp / "skills"
    g.WORKSPACE = tmp / "workspace"
    g.WORKSPACE.mkdir()
    g.CONFIRM = lambda desc: False
    g.ASK = lambda q: "(no answer: nobody is at the keyboard. Do not ask again; make your best attempt.)"
    prompt = ev.TIDEPOOL_PROMPT.format(url=url)
    expects = ["kestrel", "340"]

    try:
        ctx = None if args.no_load else ev.ensure_model(args.model, args.ctx, args.backend)
        model = build_agent(args.model, "tool", args.max_steps, "generic", args.backend).model
        run = lambda: ev.run_once(args.model, prompt, expects, args.max_steps, args.backend)  # noqa: E731
        print(f"summary_cost | {args.backend}: {args.model} | loaded context {ctx} | n={args.n}")
        trials = []
        for i in range(1, args.n + 1):
            run()                       # warm-up: the first run after a load is slower
            off = run()                 # a run straight after a finished run, no summary
            first = run()
            info: dict = {}
            th = threading.Thread(target=timed_summary, args=(model, prompt, first["answer"], info))
            th.start()
            on = run()                  # started while the summary is in flight
            th.join()
            trials.append({"off": off, "on": on, "summary": info})
            print(f"  trial {i}: summary {info.get('seconds')}s {info.get('input_tokens')} in "
                  f"{info.get('output_tokens')} out | next run off {off['wall_s']}s {off['steps']} steps "
                  f"{'PASS' if off['passed'] else 'FAIL'} | on {on['wall_s']}s {on['steps']} steps "
                  f"{'PASS' if on['passed'] else 'FAIL'} | {info.get('summary')!r}")
        n = len(trials)
        mean = lambda f: sum(f(t) for t in trials) / n  # noqa: E731
        print(f"  => summary {mean(lambda t: t['summary']['seconds']):.1f}s, "
              f"{mean(lambda t: t['summary'].get('input_tokens') or 0):.0f} in, "
              f"{mean(lambda t: t['summary'].get('output_tokens') or 0):.0f} out | "
              f"next run off {mean(lambda t: t['off']['wall_s']):.1f}s "
              f"({mean(lambda t: t['off']['steps']):.1f} steps), "
              f"on {mean(lambda t: t['on']['wall_s']):.1f}s ({mean(lambda t: t['on']['steps']):.1f} steps)")
        out = ev.ROOT / "logs" / f"summarycost-{datetime.now():%Y%m%d-%H%M%S}-{args.backend}-{ev.safe_name(args.model)}.json"
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps({"backend": args.backend, "model": args.model, "loaded_context": ctx,
                                   "prompt": prompt, "trials": trials}, indent=2))
        print(f"  saved {out.relative_to(ev.ROOT)}")
    finally:
        server.terminate()


if __name__ == "__main__":
    main()
