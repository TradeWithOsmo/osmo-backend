"""Market data package"""

from .prices import get_current_price, subscribe_to_price_updates

__all__ = ['get_current_price', 'subscribe_to_price_updates']
