import asyncio
from telegram import Bot, Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

from brain import TradingBrain
from auditor import Auditor
from keep_alive import keep_alive
from config import REPORT_DAY, REPORT_TIME, TELEGRAM_TOKEN, CHAT_ID
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
        and not TELEGRAM_TOKEN.startswith("PUT_YOUR")
        and not str(CHAT_ID).startswith("PUT_YOUR")
    )


def _format_signal(tf, data, now):
    tp = f"{data['tp']:.2f}" if data['tp'] is not None else "—"
    sl = f"{data['sl']:.2f}" if data['sl'] is not None else "—"
    entry = f"{data['entry']:.2f}" if data['entry'] is not None else "—"
    direction = "BUY" if "BUY" in data['dir'] else ("SELL" if "SELL" in data['dir'] else "WAIT")
    session = "🟢 NY ochiq" if is_ny_session_active(now) else "🔴 NY yopiq"
    return (
        "🔔 4x40IN SIGNAL\n"
        "💎 Instrument: Gold (XAUUSD)\n"
        f"⏱️ Timeframe: {tf}\n"
        f"📈 Yo'nalish: {direction}\n"
        f"🎯 Kirish: {entry}\n"
        f"✅ Maqsad (TP): {tp}\n"
        f"🛡️ Stop (SL): {sl}\n"
        f"📊 Ishonch: {data['conf']}%\n"
        f"🕒 Vaqt: {now.strftime('%Y-%m-%d %H:%M')} (Toshkent)\n"
        f"{session}"
    )


def _format_full_report(results, now):
    lines = [
        "📊 JORIY BOZOR TAHLILI — Gold (XAUUSD)",
        f"🕒 Vaqt: {now.strftime('%Y-%m-%d %H:%M')} (Toshkent)",
        "",
    ]
    for tf, d in results.items():
        direction = d["dir"]
        lines.append(f"⏱️ {tf}  →  {direction}   (ishonch {d['conf']}%)")
        if d.get("entry") is not None:
            entry = f"{d['entry']:.2f}"
            tp = f"{d['tp']:.2f}" if d.get('tp') is not None else "—"
            sl = f"{d['sl']:.2f}" if d.get('sl') is not None else "—"
            lines.append(f"   Kirish: {entry}   TP: {tp}   SL: {sl}")
        ind = d.get("indicators") or {}
        if ind:
            lines.append(
                f"   EMA20={ind['EMA20']}   EMA50={ind['EMA50']}   "
                f"RSI={ind['RSI14']}   STOCHk={ind['STOCHk']}"
            )
            lines.append(f"   MACD={ind['MACD']}   signal={ind['MACDsig']}")
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
    name = (update.effective_user.first_name or "Xudaynazar") if update.effective_user else "Xudaynazar"
    open_t, _ = ny_session_window()
    extra = ""
    if not is_ny_session_active():
        extra = f"\n🇺🇸 Amerika (NY) sessiyasi {open_t.strftime('%H:%M')} (Toshkent vaqti)da boshlanadi."
    else:
        extra = "\n🇺🇸 Amerika (NY) sessiyasi hozir OCHIQ — eng aktiv vaqt!"
    await update.message.reply_text(
        f"Salom {name}! Tizim aloqada, bozorni tahlil qilyapman..."
        f"{extra}\n\n"
        "Buyruqlar:\n"
        "/signal — joriy bozor tahlilini darhol olish\n"
        "/session — Amerika (NY) sessiyasi vaqti\n"
        "/status — tizim holati"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = now_tashkent()
    days = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya']
    text = (
        "✅ Tizim ishlamoqda — bozor kuzatilmoqda.\n"
        f"🕒 Hozirgi vaqt: {now.strftime('%Y-%m-%d %H:%M')} (Toshkent)\n"
        f"📅 Bugun: {days[now.weekday()]}\n\n"
        + format_ny_session_info(now)
    )
    await update.message.reply_text(text)


async def cmd_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = now_tashkent()
    open_t, close_t = ny_session_window(now)
    days = ['Du', 'Se', 'Ch', 'Pa', 'Ju', 'Sh', 'Ya']
    text = (
        "🇺🇸 AMERIKA (NEW YORK) SESSIYASI\n"
        f"🕒 Hozir Toshkent: {now.strftime('%Y-%m-%d %H:%M')}\n\n"
        + format_ny_session_info(now)
        + "\n\n"
        f"📅 {days[open_t.weekday()]} kuni:\n"
        f"   • Boshlanish: {open_t.strftime('%H:%M')} (Toshkent)\n"
        f"   • Tugash:     {close_t.strftime('%H:%M')} (Toshkent)\n"
        "ℹ️ NY sessiyasi — Oltin bozorida eng faol va katta hajmli vaqt."
    )
    await update.message.reply_text(text)


async def cmd_signal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Bozor tahlili boshlandi, biroz kuting...")
    brain: TradingBrain = context.application.bot_data["brain"]
    try:
        results = await brain.full_scan()
    except Exception as e:
        await update.message.reply_text(f"⚠️ Tahlilda xato yuz berdi: {e}")
        return
    text = _format_full_report(results, now_tashkent())
    await update.message.reply_text(text)


async def trading_loop(bot: Bot, brain: TradingBrain):
    auditor = Auditor()

    print("✅ 4x40IN Tizimi o't oldi. Bozor kuzatilmoqda...")
    last_report_date = None
    last_session_notify_date = None
    was_session_active = is_ny_session_active(now_tashkent())

    while True:
        now = now_tashkent()

        # NY sessiyasi yangi ochilganda — eslatma yuborish
        active_now = is_ny_session_active(now)
        if active_now and not was_session_active and last_session_notify_date != now.date():
            open_t, close_t = ny_session_window(now)
            await send_telegram(
                bot,
                "🇺🇸🟢 AMERIKA (NY) SESSIYASI ENDIGINA OCHILDI!\n"
                f"🕒 {open_t.strftime('%H:%M')} – {close_t.strftime('%H:%M')} (Toshkent vaqti)\n"
                "💎 Oltinda yuqori volatil davr — signallarni diqqat bilan kuzating."
            )
            last_session_notify_date = now.date()
        was_session_active = active_now

        if now.weekday() <= 4:  # Ish kunlari (Du–Ju)
            try:
                results = await brain.full_scan()
                print(f"\n--- TAHLIL: {now.strftime('%H:%M')} (Toshkent) ---")
                for tf, data in results.items():
                    print(f"{tf}: {data['dir']} ({data['conf']}%) "
                          f"entry={data['entry']} tp={data['tp']} sl={data['sl']}")
                    auditor.log_result(tf, data['dir'])
                    if "BUY" in data['dir'] or "SELL" in data['dir']:
                        await send_telegram(bot, _format_signal(tf, data, now))
            except Exception as e:
                print(f"⚠️ Skanerlash xatosi: {e}")

        if (now.weekday() == REPORT_DAY
                and now.strftime("%H:%M") == REPORT_TIME
                and last_report_date != now.date()):
            try:
                path = auditor.export_weekly_report()
                last_report_date = now.date()
                msg = (
                    "📊 HAFTALIK HISOBOT TAYYOR\n"
                    f"💾 Saqlandi: {path}\n"
                    f"🕒 {now.strftime('%Y-%m-%d %H:%M')} (Toshkent)"
                )
                print("\n" + msg)
                await send_telegram(bot, msg)
            except Exception as e:
                print(f"⚠️ Hisobot xatosi: {e}")

        await asyncio.sleep(60)


async def start_system():
    keep_alive()
    print("🌐 Keep-alive web server yoqildi (port 5000).")

    if not _telegram_configured():
        print("ℹ️ Telegram sozlanmagan — TELEGRAM_TOKEN va CHAT_ID kiriting.")
        return

    brain = TradingBrain()

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.bot_data["brain"] = brain
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("status", cmd_status))
    application.add_handler(CommandHandler("session", cmd_session))
    application.add_handler(CommandHandler("signal", cmd_signal))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    print("📡 Telegram bot ulandi va buyruqlarni qabul qilishga tayyor.")

    bot = application.bot
    try:
        me = await bot.get_me()
        print(f"🔎 Bot ma'lumoti: @{me.username} (id={me.id})")
    except TelegramError as e:
        print(f"⚠️ Bot get_me xatosi: {e}")

    now = now_tashkent()
    await send_telegram(
        bot,
        "✅ 4x40IN Tizimi aloqaga chiqdi.\n"
        f"🕒 {now.strftime('%Y-%m-%d %H:%M')} (Toshkent vaqti)\n\n"
        + format_ny_session_info(now)
        + "\n\n/signal yuborib darhol tahlil oling."
    )

    try:
        await trading_loop(bot, brain)
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


if __name__ == "__main__":
    asyncio.run(start_system())
