#!/bin/zsh
# Bonsai 2 9B against Qwen 3.5 9B on the hard fake Radarr with the step cap raised from 12 to 20, same Ollama session.
# Why: 6 of Bonsai's 12 runs hit the cap at 12 (RESULTS.md). Criterion (stated before the run): Bonsai within 2 passes of Qwen at n=12;
# if Bonsai gains 3 or more over its cap-12 result (3/12) the cap was limiting it.
cd "$(dirname "$0")/.." || exit 1
for m in qwen3.5:9b bonsai2-9b-q2; do
  .venv/bin/python tests/eval.py --backend ollama --model $m --ctx 32768 --max-steps 20 --run-timeout 600 \
    --fake-radarr --radarr-task hard --n 12 --label bonsai-cap20-${m//[:\/]/_}
done
echo BONSAI_CAP20_DONE
