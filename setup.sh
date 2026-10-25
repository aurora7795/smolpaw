#!/bin/zsh
# Run this once from ~/Claude/Smolpaw to set up a native Mac venv.
set -e

echo "→ Removing any existing (possibly Linux) .venv..."
rm -rf .venv

echo "→ Creating fresh venv..."
python3 -m venv .venv

echo "→ Installing dependencies..."
.venv/bin/pip install --upgrade pip --quiet
.venv/bin/pip install smolagents openai ddgs --quiet

echo ""
echo "✓ Done. To run:"
echo "  source .venv/bin/activate"
echo "  python3 agent.py"
