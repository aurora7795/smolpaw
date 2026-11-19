#!/bin/zsh
# #137, #138, #139: retests under the compact-final default. Ollama, 32K, step cap 12. Read-only measurement.
# #137 first (baseline, plus smolagents' prompt as a paired arm), then #138 (repeat-nudge: a worktree of main with the
# experiment commit cherry-picked; baseline = the #137 compact-final arm), then #139 (SMOLPAW_STALL_FAILS=3 against off).
# Gates are stated on the issues. Logs go to logs/ with labels r137-*, r138-*, r139-*.
cd "$(dirname "$0")/.." || exit 1
ROOT=$PWD
WT=${WT138:-$ROOT/../smolpaw-wt138}
PY=$ROOT/.venv/bin/python
~/.lmstudio/bin/lms unload --all >/dev/null 2>&1
ev() { # dir label args...
  local d=$1 label=$2; shift 2
  (cd $d && $PY tests/eval.py --backend ollama --ctx 32768 --max-steps 12 --run-timeout 400 --label $label "$@")
}
for m in gemma4:e4b qwen3.5:9b; do
  t=${m//[:\/]/_}
  ev $ROOT r137-$t-cf --model $m --fake-radarr --radarr-task hard --n 12
  ev $ROOT r137-$t-default --model $m --fake-radarr --radarr-task hard --n 12 --system-prompt default
  ev $WT r138-$t-nudge --model $m --fake-radarr --radarr-task hard --n 12
done
echo R137_R138_DONE
for m in gemma4:e4b qwen3.5:9b; do
  t=${m//[:\/]/_}
  for c in edit_duplicate_passage edit_last_line edit_special_chars edit_across_clip edit_crlf edit_one_section append_keep_all read_three_report; do
    ev $ROOT r139-$t-off --model $m --tracking $c --n 3
    SMOLPAW_STALL_FAILS=3 ev $ROOT r139-$t-fails3 --model $m --tracking $c --n 3
  done
  ev $ROOT r139-$t-off --model $m --counting-home --n 3
  SMOLPAW_STALL_FAILS=3 ev $ROOT r139-$t-fails3 --model $m --counting-home --n 3
done
echo ALLDONE
