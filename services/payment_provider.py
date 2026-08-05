"""Intentionally disabled legacy direct-payment interface.

The bot only sends users to the TMA.  Payment creation and provider webhooks
are owned outside this process, so importing this module must never load a
bank/payment SDK or start a payment server.
"""


async def create_payment(*_args, **_kwargs):
    raise RuntimeError("Direct payments are disabled in this bot; use the TMA")


async def start_webhook_server(*_args, **_kwargs):
    raise RuntimeError("Payment webhooks are disabled in this bot")


__all__ = ["create_payment", "start_webhook_server"]
