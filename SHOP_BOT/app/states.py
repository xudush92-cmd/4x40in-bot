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


class SellerAdStates(StatesGroup):
    """E'lon qo'shish ustasi (Phase 3)."""

    waiting_category = State()
    waiting_title = State()
    waiting_description = State()
    waiting_price = State()
    waiting_contact = State()
    waiting_photos = State()
    preview = State()


class AdminTextStates(StatesGroup):
    """Bot matnini tahrirlash (Phase 8)."""

    waiting_text = State()
