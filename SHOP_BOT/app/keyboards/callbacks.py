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


class GuideCB(CallbackData, prefix="guide"):
    """Shaxsiy chat yo'riqnomasi; sahifa rolga qarab serverda tanlanadi."""

    page: str = "home"


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


class PolicyCB(CallbackData, prefix="pol"):
    """Posbon/tozalovchi/ruxsatlar: amal, guruh ID (0=global), parametr."""

    action: str
    group_id: int = 0
    value: str = "-"


class CounterCB(CallbackData, prefix="mine"):
    """Foydalanuvchining shaxsiy sanoqchi sahifasi (boshqa odamga ID yo'q)."""

    action: str
    group_id: int = 0


class CounterAdminCB(CallbackData, prefix="acnt"):
    """Admin sanoqchi amallari (group_id=0: umumiy kanallar)."""

    action: str
    group_id: int = 0
    value: str = "-"


class ReferralAdminCB(CallbackData, prefix="ref"):
    """Phase 8: referal siyosati va statistika."""

    action: str
    value: str = "-"


class TextCB(CallbackData, prefix="txt"):
    """Phase 8: matnlar ro'yxati, preview, tahrir va reset."""

    action: str
    key: str = "-"
    page: int = 0


class ErrorCB(CallbackData, prefix="err"):
    """Phase 8: xato jurnali; value=holat/filtr, error_id=yozuv."""

    action: str
    error_id: int = 0
    value: str = "open"
    page: int = 0


class AdminOpsCB(CallbackData, prefix="aops"):
    """Super admin: qo'shish, rol, o'chirish va amallar tarixi."""

    action: str
    admin_id: int = 0
    value: str = "-"
    page: int = 0


class StatsCB(CallbackData, prefix="st8"):
    """Kunlik/haftalik/oylik grafiklar va guruh CSV hisobotlari."""

    action: str
    group_id: int = 0
    days: int = 7
    page: int = 0


class BroadcastCB(CallbackData, prefix="bcast"):
    """Phase 8: tarqatish qoralamasi, preview, tasdiq, pauza va audit."""

    action: str
    broadcast_id: int = 0
    target: str = "all"


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


class PaymentCB(CallbackData, prefix="pay"):
    """Phase 5: admin rekvizitlari, chek navbati va qarorlari.

    target_id — chek yoki karta ID; value — sahifa/filtr yoki maydon kaliti.
    """

    action: str
    target_id: int = 0
    value: str = "0"


class SellerPanelCB(CallbackData, prefix="sp"):
    """Sotuvchi paneli (sotuvchining o'zi)."""

    action: str = "menu"
    value: str = "-"


class AdCB(CallbackData, prefix="ad"):
    """📢 E'lonlar (sotuvchi tomoni).

    action: list | card | new | edit | preview | send | pause | resume |
            delete | delete_confirm | stats | filter | photos | photo_del |
            e_title | e_desc | e_price | e_contact | e_cat |
            wiz_cat | wiz_back | wiz_skip | wiz_done | wiz_send | wiz_cancel |
            c_type
    ad_id: e'lon ID (usta boshida 0 — hali yaratilmagan)
    value: sahifa|filtr yoki qo'shimcha parametr
    """

    action: str
    ad_id: int = 0
    value: str = "-"


class PostingCB(CallbackData, prefix="pst"):
    """Phase 4: group (guruh toifalari) | queue | up | down | send.

    `target_id` group/category/ad ID; up/down.value = category_id|page.
    """

    action: str
    target_id: int = 0
    value: str = "0"


class ModCB(CallbackData, prefix="mod"):
    """✅ Moderatsiya (admin tomoni).

    action: list | card | approve | reject | reason | history | ads | ads_card |
            pause | resume | delete | delete_confirm | filter | page
    ad_id: e'lon ID
    value: sahifa|filtr yoki sabab kaliti
    """

    action: str
    ad_id: int = 0
    value: str = "-"
