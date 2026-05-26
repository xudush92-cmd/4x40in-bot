"""
panels/user/handlers.py — USER bo'sh router (placeholder).

V1 redesign:
────────────
Foydalanuvchi (USER) funksiyalari ikki alohida panelga taqsimlandi:
- panels/poster/  — POSTER (e'lon beruvchi) handlerlari
- panels/customer/ — CUSTOMER (mijoz) handlerlari

Bu fayl — eski importlarni buzmaslik uchun bo'sh router. Keyinchalik
butunlay olib tashlanishi mumkin.
"""

from __future__ import annotations

from aiogram import Router

router = Router(name="user_legacy")
