#!/usr/bin/env python
"""
Simple runner script for the Osmo Agent chat interface.
Usage: python run_chat.py
"""

import asyncio
import sys


async def main():
    """Main entry point for the chat interface."""
    try:
        from src.main import ChatInterface

        chat = ChatInterface()
        await chat.start()
    except ImportError as e:
        print(f"❌ Error: Missing required module: {e}")
        print("   Run: pip install -r requirements.txt")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\nGoodbye! 👋")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
