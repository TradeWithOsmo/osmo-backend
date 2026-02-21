#!/usr/bin/env python
"""
Simple runner script for the Osmo Agent API.
Usage: python run_chat.py
"""

import os
import sys

import uvicorn


def main() -> None:
    try:
        host = os.getenv("HOST", "0.0.0.0")
        port = int(os.getenv("PORT", "8000"))
        uvicorn.run("src.main:app", host=host, port=port, reload=False)
    except ImportError as e:
        print(f"Error: Missing required module: {e}")
        print("Run: pip install -r requirements.txt")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nShutdown requested")
        sys.exit(0)
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()