"""FSM holatlari (Redis'da saqlanadi — restartga chidamli)."""

from aiogram.fsm.state import State, StatesGroup


class AdminSettingsStates(StatesGroup):
    """Global sozlamalarni tahrirlash."""

    waiting_support_contact = State()
    waiting_interval = State()


class AdminGroupStates(StatesGroup):
    """Guruhlar bo'limi: sozlamalarni qo'lda kiritish (Phase 1)."""

    waiting_interval = State()
    waiting_jitter = State()
    waiting_limit = State()
    waiting_quiet = State()


class AdminCategoryStates(StatesGroup):
    """Toifalar bo'limi (Phase 1)."""

    waiting_name = State()
    waiting_rename = State()
    waiting_interval = State()
    waiting_description = State()


class SellerApplicationStates(StatesGroup):
    """Shaxsiy sotuvchilik arizasi: ism → aloqa → preview."""

    waiting_name = State()
    waiting_contact = State()
    preview = State()


class AdminApplicationStates(StatesGroup):
    """Adminning erkin rad sababini kiritishi (tarif/chek FSMidan alohida)."""

    waiting_reason = State()


class AdminSellerStates(StatesGroup):
    """Sotuvchilar bo'limi (Phase 2)."""

    waiting_user_id = State()
    waiting_name = State()
    waiting_phone = State()
    waiting_contact = State()
    waiting_note = State()
    waiting_search = State()
    waiting_days = State()
    waiting_ads_limit = State()
    # Profilni tahrirlash (qo'shish jarayonidan alohida — to'qnashmasligi uchun)
    editing_name = State()
    editing_phone = State()
    editing_contact = State()
    editing_note = State()


class AdminTariffStates(StatesGroup):
    """Tariflar bo'limi (Phase 2)."""

    waiting_name = State()
    waiting_description = State()
    waiting_price = State()
    waiting_days = State()
    waiting_ads = State()
    waiting_photos = State()


class SellerAdStates(StatesGroup):
    """E'lon qo'shish ustasi va tahrirlash (Phase 3).

    Bitta holatlar guruhi ham usta, ham tahrirlash uchun ishlatiladi:
    ajratish FSM ma'lumotidagi `flow` (`wizard` | `edit`) orqali bo'ladi.
    """

    waiting_category = State()
    waiting_title = State()
    waiting_description = State()
    waiting_price = State()
    waiting_contact = State()
    waiting_photos = State()
    preview = State()


class FreeAdStates(StatesGroup):
    """Bepul e'lon: bitta surat+caption → shaxsiy ko'rib chiqish → admin."""

    waiting_photo = State()
    preview = State()


class AdminModerationStates(StatesGroup):
    """Moderatsiya bo'limi (Phase 3)."""

    choosing_reason = State()   # tayyor sabab tanlanmoqda
    waiting_reason = State()    # qo'lda yozilgan sabab


class SellerPaymentStates(StatesGroup):
    """Sotuvchi kartani olgandan keyin chek rasmini yuboradi (Phase 5)."""

    waiting_receipt = State()


class AdminPaymentStates(StatesGroup):
    """Admin karta rekviziti yoki chek rad sababini kiritadi (Phase 5)."""

    waiting_method_name = State()
    waiting_card = State()
    waiting_holder = State()
    waiting_bank = State()
    waiting_note = State()
    waiting_currency = State()
    waiting_edit = State()
    waiting_reject_reason = State()


class AdminPolicyStates(StatesGroup):
    """Phase 6: guruh qoidalari, ruxsat va foydalanuvchi qidiruvi."""

    waiting_value = State()
    waiting_permission_user = State()
    waiting_permission_kind = State()
    waiting_permission_days = State()
    waiting_permission_reason = State()
    confirming_permission = State()
    waiting_user_search = State()
    waiting_manual_reason = State()
    confirming_manual_action = State()


class AdminCounterStates(StatesGroup):
    """Phase 7: har guruh sanoqchisi, kanal va qo'lda hisob tuzatish."""

    waiting_number = State()
    waiting_channel = State()
    waiting_user = State()
    waiting_adjust = State()


class AdminReferralStates(StatesGroup):
    """Referal bonus qiymati, minimal chek va kunlik limitni kiritish."""

    waiting_value = State()


class AdminOpsStates(StatesGroup):
    """Super admin tomonidan Telegram ID va rol tanlash."""

    waiting_user_id = State()
    waiting_role = State()


class AdminBroadcastStates(StatesGroup):
    """Broadcast qoralamasi: matn yoki rasm, ixtiyoriy caption; tezlik soni."""

    waiting_payload = State()
    waiting_rate = State()


class AdminTextStates(StatesGroup):
    """Bot matnini tahrirlash (Phase 8)."""

    waiting_text = State()
