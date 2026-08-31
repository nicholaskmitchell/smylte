"""Outbound notifications. Telegram is the first (and for now only) transport."""
from __future__ import annotations

from .telegram import MAX_MESSAGE_CHARS, SendResult, TelegramSender, clip, escape_html

__all__ = ["MAX_MESSAGE_CHARS", "SendResult", "TelegramSender", "clip", "escape_html"]
