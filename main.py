"""
Main entry point for Osmo Backend API
Redirects to websocket.main for actual application
"""

from websocket.main import app

__all__ = ['app']
