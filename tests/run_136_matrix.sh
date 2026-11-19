#!/bin/zsh
# Historical: this run used LM Studio, whose copies of its models have been deleted (default is now Ollama); re-download them to rerun.
# #136: housekeeping (n=4) and read-only (n=5) on LM Studio, smolagents' prompt against compact-final, interleaved by case.
# Gemma 4 E4B first, then Qwen 3.5 9B. Read-only measurement; takes about 5 hours. Logs go to logs/ with the label sp136-*.
# Compare: .venv/bin/python tests/compare_runs.py --arm default='logs/eval-*sp136-google_gemma-4-e4b-default.json' --arm final='logs/eval-*sp136-google_gemma-4-e4b-compact-final.json' --family housekeeping
cd "$(dirname "$0")/.." || exit 1
run() { # model n flag case
  for style in default compact-final; do
    .venv/bin/python tests/eval.py --backend lmstudio --model $1 --ctx 32768 --n $2 --run-timeout 400 \
      --system-prompt $style $3 $4 --label sp136-${1//\//_}-$style
  done
}
for model in google/gemma-4-e4b qwen3.5-9b-mlx; do
  for c in log_errors biggest_files stuck_downloads weekly_summary cleanup_proposal mail_summary calendar_conflicts disk_report; do
    run $model 4 --housekeeping $c
  done
  for c in write_summary read_and_save read_only_control append_log delete_old; do
    run $model 5 --readonly $c
  done
done
echo ALLDONE
