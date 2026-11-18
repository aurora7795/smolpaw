#!/bin/zsh
# #90: the unattended DECLINED text. legacy ('try another approach or call ask_user') against report ('nobody can approve;
# do not retry another way; tell the user'), interleaved by case, on LM Studio (MLX builds, 32K context, 400s per run).
# Family per model: the four read-only write cases (n=5) plus housekeeping cleanup_proposal (n=10); the read-only
# control (n=5) is a guard. Read-only measurement; about 3 hours. Logs go to logs/ with the label sp90-*.
# Compare: .venv/bin/python tests/compare_runs.py --arm legacy='logs/eval-*sp90-<model>-legacy.json' --arm report='logs/eval-*sp90-<model>-report.json'
cd "$(dirname "$0")/.." || exit 1
run() { # model n flag case
  for arm in legacy report; do
    .venv/bin/python tests/eval.py --backend lmstudio --model $1 --ctx 32768 --n $2 --run-timeout 400 \
      --declined-text $arm $3 $4 --label sp90-${1//\//_}-$arm
  done
}
for model in qwen3.5-9b-mlx google/gemma-4-e4b; do
  for c in write_summary read_and_save append_log delete_old read_only_control; do
    run $model 5 --readonly $c
  done
  run $model 10 --housekeeping cleanup_proposal
done
echo ALLDONE
