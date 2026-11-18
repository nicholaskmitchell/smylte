"""Outbound notifications, through the owner's signal-bot."""
from __future__ import annotations

from .signal import SignalSender
from .transport import MAX_MESSAGE_CHARS, SendResult, clip

__all__ = ["MAX_MESSAGE_CHARS", "SendResult", "SignalSender", "clip"]
