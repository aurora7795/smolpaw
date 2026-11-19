#!/bin/zsh
# Bonsai 2 9B (Q2_0 GGUF) against Qwen 3.5 9B (MLX) on the hard fake Radarr, same LM Studio session. Read-only measurement.
# Criterion (stated before the run): Bonsai is worth the wider matrix if it is within 2 passes of Qwen at n=12; a clear improvement is +3 or more.
cd "$(dirname "$0")/.." || exit 1
for m in qwen3.5-9b-mlx ternary-bonsai-2-9b; do
  .venv/bin/python tests/eval.py --backend lmstudio --model $m --ctx 32768 --max-steps 12 --run-timeout 400 \
    --fake-radarr --radarr-task hard --n 12 --label bonsai-hard-$m
done
echo BONSAI_DONE
