"""Inline tugmalar uchun callback_data fabrikalari (aiogram CallbackData).

Eslatma: Telegram callback_data 64 baytdan oshmasligi kerak — shuning uchun
maydonlar qisqa nomlangan.
"""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData


class AdminCB(CallbackData, prefix="adm"):
    """Boshqaruv paneli navigatsiyasi: `adm:<action>:<value>`."""

    action: str
    value: str = "-"


class NavCB(CallbackData, prefix="nav"):
    """Umumiy navigatsiya (orqaga, bekor qilish)."""

    to: str = "menu"


class GroupCB(CallbackData, prefix="grp"):
    """Guruhlar bo'limi.

    action: list | card | settings | feats | toggle | interval | jitter |
            limit | quiet | protect | pause | delete | delete_confirm |
            refresh | matrix | add | cats | matrix_page
    group_id: 0 — guruh tanlanmagan (ro'yxat/matritsa uchun)
    value: sahifa raqami yoki qo'shimcha parametr
    """

    action: str
    group_id: int = 0
    value: str = "0"


class FeatureCB(CallbackData, prefix="feat"):
    """Funksiya tumbleri: `feat:<group_id>:<feature>:<enabled>:<origin>:<page>`.

    origin — qaysi ekrandan bosilgani (feats | matrix | settings), shunda
    javobdan keyin o'sha ekran qayta chiziladi.
    """

    group_id: int = 0
    feature: str = "posting"
    enabled: bool = True
    origin: str = "feats"
    page: int = 0


class CategoryCB(CallbackData, prefix="cat"):
    """Toifalar bo'limi.

    action: list | card | create | name | group | setgroup | rename |
            interval | order | up | down | active | moderation | delete | delete_confirm
    category_id: 0 — tanlanmagan
    value: sahifa raqami yoki qo'shimcha ma'lumot
    """

    action: str
    category_id: int = 0
    value: str = "0"

class SellerCB(CallbackData, prefix="slr"):
    """Sotuvchilar bo'limi (admin).

    action: list | card | add | search | filter | grant | grant_tariff |
            extend | status | block | unblock | verify | note | delete |
            delete_confirm | subs | profile
    """

    action: str
    seller_id: int = 0
    value: str = "-"


class TariffCB(CallbackData, prefix="trf"):
    """Tariflar bo'limi (admin).

    action: list | card | create | rename | desc | price | days | ads |
            photos | active | trial | up | down | delete | delete_confirm
    """

    action: str
    tariff_id: int = 0
    value: str = "-"


class SellerPanelCB(CallbackData, prefix="sp"):
    """Sotuvchi paneli (sotuvchining o'zi)."""

    action: str = "menu"
    value: str = "-"
