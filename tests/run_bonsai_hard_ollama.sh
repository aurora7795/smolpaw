#!/bin/zsh
# Bonsai 2 9B (Q2_0, imported into Ollama as bonsai2-9b-q2) against Qwen 3.5 9B on the hard fake Radarr, same Ollama session.
# Setup once: printf 'FROM <path to Ternary-Bonsai-2-9B-Q2_0.gguf>\n' > Modelfile && ollama create bonsai2-9b-q2 -f Modelfile
# Criterion (as for the LM Studio run, stated before it): worth the wider matrix if within 2 passes of Qwen at n=12; +3 or more is a clear improvement.
cd "$(dirname "$0")/.." || exit 1
for m in qwen3.5:9b bonsai2-9b-q2; do
  .venv/bin/python tests/eval.py --backend ollama --model $m --ctx 32768 --max-steps 12 --run-timeout 400 \
    --fake-radarr --radarr-task hard --n 12 --label bonsai-hard-ollama-${m//[:\/]/_}
done
echo BONSAI_OLLAMA_DONE
