"""Telethon sessiyalarini shifrlab saqlash (Fernet).

Kalit SESSION_ENCRYPTION_KEY muhit o'zgaruvchisidan olinadi.
Bo'lmasa, BOT_TOKEN dan hosil qilinadi (ishlaydi, lekin serverda
alohida SESSION_ENCRYPTION_KEY qo'yish tavsiya etiladi).
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _get_key() -> bytes:
    raw = os.getenv("SESSION_ENCRYPTION_KEY", "").strip()
    if raw:
        try:
            # Tayyor Fernet kalit bo'lsa — o'zini ishlatamiz
            Fernet(raw.encode())
            return raw.encode()
        except Exception:
            pass
        return base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest())
    # Zaxira: BOT_TOKEN dan (kalit almashtirilsa sessiyalar o'qilmay qoladi!)
    token = os.getenv("BOT_TOKEN", "scanner-default")
    return base64.urlsafe_b64encode(
        hashlib.sha256(f"session:{token}".encode()).digest()
    )


_FERNET = Fernet(_get_key())


def encrypt_session(session_str: str) -> str:
    if not session_str:
        return ""
    return _FERNET.encrypt(session_str.encode()).decode()


def decrypt_session(session_enc: str) -> str:
    if not session_enc:
        return ""
    try:
        return _FERNET.decrypt(session_enc.encode()).decode()
    except (InvalidToken, Exception):
        return ""
