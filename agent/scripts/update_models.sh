#!/bin/bash

# Update Models Script
# Fetches all models from OpenRouter API and filters by capabilities
# Only keeps models with BOTH tool calling AND reasoning support

set -e

echo "╔════════════════════════════════════════════════════════════════╗"
echo "║     OpenRouter Models Fetcher - Tool Calling + Reasoning       ║"
echo "╚════════════════════════════════════════════════════════════════╝"
echo ""

# Check if OPENROUTER_API_KEY is set
if [ -z "$OPENROUTER_API_KEY" ]; then
    echo "❌ Error: OPENROUTER_API_KEY environment variable not set"
    echo ""
    echo "Usage:"
    echo "  export OPENROUTER_API_KEY=your_key_here"
    echo "  ./scripts/update_models.sh"
    exit 1
fi

echo "✅ OPENROUTER_API_KEY found"
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "📁 Project root: $PROJECT_ROOT"
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    if ! command -v python &> /dev/null; then
        echo "❌ Error: Python not found"
        exit 1
    fi
    PYTHON=python
else
    PYTHON=python3
fi

echo "🐍 Using Python: $PYTHON"
echo ""

# Check if required packages are installed
echo "📦 Checking dependencies..."

if ! $PYTHON -c "import httpx" 2>/dev/null; then
    echo "⚠️  httpx not installed, installing..."
    pip install httpx
fi

if ! $PYTHON -c "import dotenv" 2>/dev/null; then
    echo "⚠️  python-dotenv not installed, installing..."
    pip install python-dotenv
fi

echo "✅ Dependencies ready"
echo ""

# Run the fetch_models script
echo "🔄 Running fetch_models.py..."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

cd "$PROJECT_ROOT"
$PYTHON scripts/fetch_models.py

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check if config was generated
if [ -f "$PROJECT_ROOT/src/config/models_config.py" ]; then
    echo "✅ Models configuration file updated!"
    echo "   Location: src/config/models_config.py"
    echo ""

    # Show stats
    MODEL_COUNT=$(grep -c "^    \"" "$PROJECT_ROOT/src/config/models_config.py" || echo "0")
    echo "📊 Models with tool calling + reasoning: $MODEL_COUNT"
fi

if [ -f "$PROJECT_ROOT/models_capable.json" ]; then
    echo "✅ Models list saved!"
    echo "   Location: models_capable.json"
fi

echo ""
echo "🎉 Update complete!"
exit 0
