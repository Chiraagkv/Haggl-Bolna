"""Owner notifications (ticket #36). A stub: it writes the message to the event log and the
server log. Swap `send` for WhatsApp/SMS later; nothing else needs to change.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app import orders

log = logging.getLogger("dalaal.notify")


def send(session: Session, order_id: int, text: str, kind: str = "summary") -> None:
    log.info("notify order %s: %s", order_id, text)
    orders.emit(session, order_id, "notify", {"kind": kind, "text": text})
