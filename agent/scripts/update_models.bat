@echo off
REM Update models from OpenRouter API
REM This script fetches all models with tool calling + reasoning support

setlocal enabledelayedexpansion

echo.
echo ╔════════════════════════════════════════════════════════════╗
echo ║     OpenRouter Models Fetcher - Tool Calling + Reasoning   ║
echo ╚════════════════════════════════════════════════════════════╝
echo.

REM Check if OPENROUTER_API_KEY is set
if not defined OPENROUTER_API_KEY (
    echo ❌ Error: OPENROUTER_API_KEY environment variable not set
    echo.
    echo Please set your OpenRouter API key:
    echo   set OPENROUTER_API_KEY=your_api_key_here
    echo.
    pause
    exit /b 1
)

echo ✅ OpenRouter API Key found
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Error: Python is not installed or not in PATH
    echo.
    echo Please install Python from https://www.python.org/
    echo.
    pause
    exit /b 1
)

echo ✅ Python found
echo.

REM Check if required packages are installed
echo 🔄 Checking dependencies...
python -c "import httpx" >nul 2>&1
if errorlevel 1 (
    echo ⚠️  Installing httpx...
    pip install httpx >nul 2>&1
    if errorlevel 1 (
        echo ❌ Error: Failed to install httpx
        pause
        exit /b 1
    )
    echo ✅ httpx installed
)

python -c "import langchain" >nul 2>&1
if errorlevel 1 (
    echo ⚠️  Installing langchain dependencies...
    pip install -q -r requirements.txt
    if errorlevel 1 (
        echo ❌ Error: Failed to install requirements
        pause
        exit /b 1
    )
    echo ✅ Dependencies installed
)

echo.
echo 🔄 Fetching models from OpenRouter API...
echo.

REM Run the fetch script
python scripts\fetch_models.py

if errorlevel 1 (
    echo.
    echo ❌ Error: Failed to fetch models
    pause
    exit /b 1
)

echo.
echo ═══════════════════════════════════════════════════════════
echo ✅ Models configuration updated successfully!
echo ═══════════════════════════════════════════════════════════
echo.
echo 📝 Next steps:
echo   1. Review src/config/models_config.py
echo   2. Check models_capable.json for full model details
echo   3. Update your code to use supported models
echo.

pause
exit /b 0
