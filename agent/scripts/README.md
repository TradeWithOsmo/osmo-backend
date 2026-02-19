# Scripts Directory

Utility scripts for managing the Osmo Agent configuration and models.

## Model Fetching Script

### Purpose

Automatically fetch all available models from OpenRouter API and filter for models that support:
- ✅ **Tool Calling** - Ability to use function/tool calling
- ✅ **Reasoning** - Advanced reasoning capabilities

Only models with BOTH capabilities are included in the configuration.

### Files

- `fetch_models.py` - Main Python script that does the fetching and filtering
- `update_models.sh` - Bash script wrapper (Linux/Mac)
- `update_models.bat` - Batch script wrapper (Windows)

### Requirements

- Python 3.11+
- `OPENROUTER_API_KEY` environment variable set
- Dependencies: `httpx`, `langchain` (see requirements.txt)

### Usage

#### Linux/Mac

```bash
export OPENROUTER_API_KEY=your_key_here
./scripts/update_models.sh
```

Or make it executable first:

```bash
chmod +x scripts/update_models.sh
./scripts/update_models.sh
```

#### Windows

```cmd
set OPENROUTER_API_KEY=your_key_here
scripts\update_models.bat
```

#### Direct Python

```bash
export OPENROUTER_API_KEY=your_key_here
python scripts/fetch_models.py
```

### Output

The script generates:

1. **`src/config/models_config.py`** - Python configuration file with all supported models
   - Auto-generated
   - Contains model metadata (context window, pricing, etc.)
   - Ready to use in your agent

2. **`models_capable.json`** - JSON file with full model details
   - For reference and analysis
   - Contains raw model information from OpenRouter

### Example Output

```
🔄 Fetching models from OpenRouter...
✅ Successfully fetched 150+ models

🔍 Filtering models for tool calling + reasoning support...
Total models: 150+

✅ anthropic/claude-3.5-sonnet
✅ anthropic/claude-3-opus
✅ openai/gpt-4o
✅ openai/gpt-4-turbo
... (more models with both capabilities)

✅ Found 25 models with tool calling + reasoning support

✅ Config saved to: src/config/models_config.py
✅ Models list saved to: models_capable.json

📊 Summary:
   ✓ Total models: 25
   ✓ Providers: anthropic, openai, google, meta, mistral
   ✓ Config file: src/config/models_config.py
   ✓ JSON list: models_capable.json

✅ Models configuration updated successfully!
```

### How It Works

1. **Fetch** - Retrieves all models from OpenRouter API
2. **Filter** - Checks each model for:
   - `supports_tool_use` capability
   - `supports_reasoning` capability
3. **Validate** - Only keeps models with BOTH capabilities
4. **Generate** - Creates Python config file
5. **Save** - Exports JSON for reference

### Automation

To keep models in sync with OpenRouter, run regularly:

```bash
# Create a cron job (Linux/Mac)
0 0 * * 0 cd /path/to/agent && ./scripts/update_models.sh

# Or manually when needed
./scripts/update_models.sh
```

### Troubleshooting

#### Error: `OPENROUTER_API_KEY not set`

```bash
export OPENROUTER_API_KEY=your_key_here
```

Get your key from: https://openrouter.ai/keys

#### Error: `httpx not installed`

```bash
pip install httpx
```

#### Error: `No models found with both capabilities`

This means OpenRouter doesn't have models with both tool calling AND reasoning in your API tier. Contact OpenRouter support.

#### Permission Denied on .sh file

```bash
chmod +x scripts/update_models.sh
./scripts/update_models.sh
```

### Security

- Never commit your `OPENROUTER_API_KEY` to git
- Use environment variables only
- Generated config files are safe to commit

### Development

To modify the filtering logic:

Edit `scripts/fetch_models.py`:
- `filter_capable_models()` - Filter function
- Change the criteria in the conditionals
- Add new capability checks as needed

### Example: Use Generated Config

```python
from src.config.models_config import list_available_models, get_model_config

# Get all available models
models = list_available_models()
print(f"Available models: {len(models)}")

# Get specific model config
config = get_model_config("anthropic/claude-3.5-sonnet")
print(f"Model: {config['name']}")
print(f"Supports tool calling: {config['supports_tool_calling']}")
print(f"Supports reasoning: {config['supports_reasoning']}")
```

### More Info

- OpenRouter API: https://openrouter.ai/docs
- Models List: https://openrouter.ai/models
- Tool Calling: https://openrouter.ai/docs#function-calling
- Reasoning: https://openrouter.ai/docs#thinking
