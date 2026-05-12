"""main.py — 4x40IN Asosiy tizim."""

import asyncio
from datetime import timedelta
from telegram import Bot, Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

from brain import TradingBrain
from auditor import Auditor
from keep_alive import keep_alive
from config import TELEGRAM_TOKEN, CHAT_ID, SIGNAL_COOLDOWN_MIN, PRICE_CHANGE_PCT
from sessions import (
    now_tashkent,
    ny_session_window,
    is_ny_session_active,
    format_ny_session_info,
)


def _telegram_configured():
    return (
        TELEGRAM_TOKEN
        and CHAT_ID
        and len(TELEGRAM_TOKEN) > 10
        and len(str(CHAT_ID)) > 3
    )


def _format_signal(tf, data, now):
    """Telegram uchun signal xabari."""
    tp    = f"{data['tp']:.2f}"    if data['tp']    is not None else "—"
    sl    = f"{data['sl']:.2f}"    if data['sl']    is not None else "—"
    entry = f"{data['entry']:.2f}" if data['entry'] is not None else "—"
    direction = "BUY" if "BUY" in data['dir'] else ("SELL" if "SELL" in data['dir'] else "WAIT")
    # FIX: now ni argument sifatida beramiz (oldin argumentsiz chaqirilganda
    # funksiya ichida yangi 'now' yaratilardi — inconsistency)
    session = "🟢 NY ochiq" if is_ny_session_active(now) else "🔴 NY yopiq"

    votes = data.get("votes", {})
    vote_lines = ""
    if votes:
        icons = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}
        vote_lines = "\n" + "  ".join(
            f"{icons.get(v,'⚪')} {k}" for k, v in votes.items()
        )

    return (
        f"🔔 4x40IN SIGNAL\n"
        f"💎 Gold (XAUUSD)\n"
        f"⏱️ Timeframe: {tf}\n"
        f"📈 Yo'nalish: {direction}\n"
        f"🎯 Kirish: {entry}\n"
        f"✅ TP: {tp}\n"
        f"🛡️ SL: {sl}\n"
        f"📊 Ishonch: {data['conf']}%"
        f"{vote_lines}\n"
        f"🕒 {now.strftime('%Y-%m-%d %H:%M')} (Toshkent)\n"
        f"{session}"
    )


def _format_full_report(results, now):
    """To'liq tahlil hisoboti."""
    lines = [
        "📊 JORIY BOZOR TAHLILI — Gold (XAUUSD)",
        f"🕒 Vaqt: {now.strftime('%Y-%m-%d %H:%M')} (Toshkent)",
        "",
    ]

    for tf in ["D1", "H4", "H1", "M30"]:
        d = results.get(tf, {})
        direction = d.get("dir", "↔️ WAIT")
        conf      = d.get("conf", 0)
        entry     = d.get("entry")
        tp        = d.get("tp")
        sl        = d.get("sl")
        ind       = d.get("indicators", {})
        votes     = d.get("votes", {})
        reason    = d.get("reason", "")

        lines.append(f"⏱️ {tf}  →  {direction}   (ishonch {conf}%)")

        if entry is not None:
            tp_str = f"{tp:.2f}" if tp else "—"
            sl_str = f"{sl:.2f}" if sl else "—"
            lines.append(f"   Kirish: {entry:.2f}   TP: {tp_str}   SL: {sl_str}")

        if tf == "D1" and ind:
            lines.append(
                f"   EMA50={ind.get('EMA50','?')}  EMA200={ind.get('EMA200','?')}  RSI21={ind.get('RSI21',ind.get('RSI14','?'))}"
            )
        elif tf == "H4" and ind:
            lines.append(
                f"   EMA20={ind.get('EMA20','?')}  EMA50={ind.get('EMA50','?')}  RSI14={ind.get('RSI14','?')}"
            )
            lines.append(
                f"   MACD={ind.get('MACD','?')}  sig={ind.get('MACDsig','?')}  hist={ind.get('MACDh','?')}"
            )
        elif tf == "H1" and ind:
            lines.append(
                f"   EMA9={ind.get('EMA9','?')}  EMA21={ind.get('EMA21','?')}  RSI14={ind.get('RSI14','?')}"
            )
            lines.append(
                f"   STOCHk={ind.get('STOCHk','?')}  STOCHd={ind.get('STOCHd','?')}"
            )
        elif tf == "M30" and ind:
            lines.append(
                f"   STOCHk={ind.get('STOCHk','?')}  RSI7={ind.get('RSI7','?')}"
            )
            lines.append(
                f"   MACD={ind.get('MACD','?')}  sig={ind.get('MACDsig','?')}"
            )

        if votes:
            icons = {"BUY": "🟢", "SELL": "🔴", "NEUTRAL": "⚪"}
            vote_str = "  ".join(f"{icons.get(v,'⚪')}{k}" for k, v in votes.items())
            lines.append(f"   Ovozlar: {vote_str}")

        if reason:
            lines.append(f"   ⚠️ {reason}")

        lines.append("")

    lines.append(format_ny_session_info(now))
    return "\n".join(lines).rstrip()


async def send_telegram(bot: Bot, text: str):
    if bot is None:
        return
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text)
    except TelegramError as e:
        print(f"⚠️ Telegram xatosi: {e}")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name if update.effective_user else "Trader"
    # FIX: now ni oldindan olamiz va barcha funksiyalarga bir xil vaqtni beramiz
    now = now_tashkent()
    extra = ""
    if not is_ny_session_active(now):
        open_t, _ = ny_session_window(now)
        extra = f"\n🇺🇸 NY sessiyasi {open_t.strftime('%H:%M')} (Toshkent)da boshlanadi."
    else:
        extra = "\n🇺🇸 NY sessiyasi hozir OCHIQ — eng aktiv vaqt!"
    await update.message.reply_text(
        f"Salom {name}! 4x40IN tizimi aloqada.\n"
        f"{extra}\n\n"
        "Buyruqlar:\n"
        "/signal — joriy bozor tahlili\n"
        "/session — NY sessiyasi vaqti\n"
        "/status — tizim holati"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now  = now_tashkent()
    days = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya']
    text = (
        "✅ Tizim ishlamoqda\n"
        f"🕒 {now.strftime('%Y-%m-%d %H:%M')} (Toshkent)\n"
        f"📅 {days[now.weekday()]}\n\n"
        + format_ny_session_info(now)
    )
    await update.message.reply_text(text)


async def cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = now_tashkent()
    await update.message.reply_text(format_ny_session_info(now))


async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Tahlil boshlandi, kuting...")
    brain: TradingBrain = context.application.bot_data["brain"]
    try:
        results = await brain.full_scan()
    except Exception as e:
        await update.message.reply_text(f"⚠️ Tahlilda xato: {e}")
        return
    text = _format_full_report(results, now_tashkent())
    await update.message.reply_text(text)


def _should_send(prev: dict | None, direction: str, entry: float, now) -> tuple[bool, str]:
    if prev is None:
        return True, "birinchi signal"
    if prev["dir"] != direction:
        return True, f"yo'nalish o'zgardi ({prev['dir']} → {direction})"
    cooldown = timedelta(minutes=SIGNAL_COOLDOWN_MIN)
    elapsed  = now - prev["at"]
    if elapsed < cooldown:
        mins = int((cooldown - elapsed).total_seconds() / 60) + 1
        return False, f"cooldown ({mins} daq qoldi)"
    if prev["entry"] and abs(entry - prev["entry"]) / prev["entry"] < PRICE_CHANGE_PCT:
        return False, f"narx o'zgarmagan ({prev['entry']} → {entry})"
    return True, "cooldown tugadi va narx o'zgardi"


async def trading_loop(bot: Bot, brain: TradingBrain, auditor: Auditor):
    print("✅ 4x40IN ishga tushdi. Bozor kuzatilmoqda...")
    last_session_notify_date = None
    was_session_active = is_ny_session_active(now_tashkent())
    last_signals: dict[str, dict] = {}

    async def _audit_send(text: str):
        await send_telegram(bot, text)

    while True:
        now = now_tashkent()

        # NY sessiyasi yangi ochilganda xabar
        active_now = is_ny_session_active(now)
        if active_now and not was_session_active and last_session_notify_date != now.date():
            open_t, close_t = ny_session_window(now)
            await send_telegram(
                bot,
                "🇺🇸🟢 NY SESSIYASI OCHILDI!\n"
                f"🕒 {open_t.strftime('%H:%M')} – {close_t.strftime('%H:%M')} (Toshkent)\n"
                "💎 Oltinda yuqori volatillik davri — diqqat bilan kuzating."
            )
            last_session_notify_date = now.date()
        was_session_active = active_now

        # Faqat ish kunlari (Du–Ju)
        if now.weekday() <= 4:
            try:
                results = await brain.full_scan()
                print(f"\n--- {now.strftime('%H:%M')} ---")

                # Auditor: ochiq signallarni tekshirish
                closed = auditor.update_open_signals(results, now)
                for c in closed:
                    print(f"   📒 #{c['id']} {c['tf']} {c['direction']} → {c['outcome'].upper()}")

                for tf, data in results.items():
                    direction = "BUY" if "BUY" in data['dir'] else (
                        "SELL" if "SELL" in data['dir'] else "WAIT"
                    )
                    print(f"{tf}: {data['dir']} ({data['conf']}%) "
                          f"entry={data['entry']} tp={data['tp']} sl={data['sl']}")

                    if direction == "WAIT" or data['entry'] is None:
                        continue

                    prev = last_signals.get(tf)
                    send_it, reason = _should_send(prev, direction, data['entry'], now)
                    if send_it:
                        await send_telegram(bot, _format_signal(tf, data, now))
                        last_signals[tf] = {
                            "dir": direction, "entry": data['entry'], "at": now
                        }
                        sid = auditor.record_signal(tf, data, results, now)
                        print(f"   📤 {tf} #{sid} yuborildi — {reason}")
                    else:
                        print(f"   ⏸️ {tf} o'tkazildi — {reason}")

            except Exception as e:
                print(f"⚠️ Skanerlash xatosi: {e}")

        # Auditor hisobotlar
        try:
            await auditor.maybe_send_reports(_audit_send, now)
        except Exception as e:
            print(f"⚠️ Auditor xatosi: {e}")

        await asyncio.sleep(60)


async def start_system():
    keep_alive()
    print("🌐 Keep-alive server yoqildi (port 5000).")

    if not _telegram_configured():
        print("❌ Telegram sozlanmagan — Replit Secrets ga TELEGRAM_TOKEN va TELEGRAM_CHAT_ID kiriting.")
        return

    brain   = TradingBrain()
    auditor = Auditor()

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.bot_data["brain"] = brain
    application.add_handler(CommandHandler("start",   cmd_start))
    application.add_handler(CommandHandler("status",  cmd_status))
    application.add_handler(CommandHandler("session", cmd_session))
    application.add_handler(CommandHandler("signal",  cmd_signal))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    print("📡 Telegram bot ulandi.")

    bot = application.bot
    try:
        me = await bot.get_me()
        print(f"🔎 Bot: @{me.username}")
    except TelegramError as e:
        print(f"⚠️ Bot xatosi: {e}")

    now = now_tashkent()
    await send_telegram(
        bot,
        "✅ 4x40IN ishga tushdi.\n"
        f"🕒 {now.strftime('%Y-%m-%d %H:%M')} (Toshkent)\n\n"
        + format_ny_session_info(now)
        + "\n\n/signal — darhol tahlil olish"
    )

    try:
        await trading_loop(bot, brain, auditor)
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(start_system())
