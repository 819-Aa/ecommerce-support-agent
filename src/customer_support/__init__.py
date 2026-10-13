"""Offline-first customer support demo used by the ecommerce agent."""

from customer_support.store import (
    create_support_ticket,
    get_order_status,
    initialize_database,
    refund_eligibility,
)

__all__ = [
    "create_support_ticket",
    "get_order_status",
    "initialize_database",
    "refund_eligibility",
]
