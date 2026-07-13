"""QR-code login flow for Yangjibao.

Flow: GET /qr_code → show QR → poll /qr_code_state/{id}
  state 1 = pending, 2 = confirmed (get token), 3 = expired
"""
import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import qrcode
import io
import base64
from app.yangjibao.client import YangjibaoClient

logger = logging.getLogger(__name__)


class QRStatus(str, Enum):
    PENDING = "pending"
    SCANNED = "scanned"      # Not used by real API, kept for UI
    CONFIRMED = "confirmed"
    EXPIRED = "expired"
    FAILED = "failed"


@dataclass
class QRLoginSession:
    qr_id: str
    qr_url: str
    qr_image_base64: str = ""
    status: QRStatus = QRStatus.PENDING
    access_token: Optional[str] = None
    expires_in: int = 300
    created_at: float = field(default_factory=asyncio.get_event_loop().time)


class QRLoginManager:
    """QR login session manager for Yangjibao."""

    def __init__(self):
        self._active_session: Optional[QRLoginSession] = None

    @property
    def active_session(self) -> Optional[QRLoginSession]:
        if self._active_session:
            loop = asyncio.get_event_loop()
            elapsed = loop.time() - self._active_session.created_at
            if elapsed > self._active_session.expires_in:
                self._active_session = None
        return self._active_session

    async def start_login(self) -> QRLoginSession:
        """Start QR login: get QR code from Yangjibao, generate image."""
        client = YangjibaoClient()  # No token yet
        qr_data = await client.get_qr_code()

        qr_id = qr_data["qr_id"]
        qr_url = qr_data["qr_url"]

        # Generate QR code PNG as base64
        qr = qrcode.QRCode(version=1, box_size=10, border=2)
        qr.add_data(qr_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode()

        self._active_session = QRLoginSession(
            qr_id=qr_id,
            qr_url=qr_url,
            qr_image_base64=qr_b64,
        )
        logger.info(f"Yangjibao QR login started: qr_id={qr_id[:20]}...")
        return self._active_session

    async def poll_status(self) -> QRLoginSession:
        """Poll QR scan status. Returns updated session."""
        if not self._active_session:
            raise ValueError("No active QR login session")

        session = self._active_session

        # Check expiry
        loop = asyncio.get_event_loop()
        if loop.time() - session.created_at > session.expires_in:
            session.status = QRStatus.EXPIRED
            return session

        try:
            client = YangjibaoClient()
            result = await client.check_qr_status(session.qr_id)
            state = result.get("state", "")

            if state == "confirmed":
                session.status = QRStatus.CONFIRMED
                session.access_token = result.get("access_token", "")
                logger.info("Yangjibao QR login confirmed!")
            elif state == "expired":
                session.status = QRStatus.EXPIRED
            elif state == "pending":
                session.status = QRStatus.PENDING
            else:
                logger.warning(f"Unknown QR state: {state}")

        except Exception as e:
            logger.error(f"QR poll failed: {e}")
            session.status = QRStatus.FAILED

        return session

    def reset(self):
        self._active_session = None


qr_manager = QRLoginManager()
