import asyncio
from datetime import datetime
from telegram import Bot, Update
from telegram.error import TelegramError
from telegram.ext import Application, CommandHandler, ContextTypes

from brain import TradingBrain
from auditor import Auditor
from keep_alive import keep_alive
from config import REPORT_DAY, REPORT_TIME, TELEGRAM_TOKEN, CHAT_ID


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
    direction = "BUY" if "BUY" in data['dir'] else ("SELL" if "SELL" in data['dir'] else "WAIT")
    return (
        "🔔 4x40IN SIGNAL\n"
        "💎 Instrument: Gold (XAUUSD)\n"
        f"⏱️ Timeframe: {tf}\n"
        f"📈 Direction: {direction}\n"
        f"🎯 TP: {tp} | 🛡️ SL: {sl}\n"
        f"📊 Confidence: {data['conf']}% | 🕒 Time: {now.strftime('%H:%M')}"
    )


async def send_telegram(bot: Bot, text: str):
    if bot is None:
        return
    try:
        await bot.send_message(chat_id=CHAT_ID, text=text)
    except TelegramError as e:
        print(f"⚠️ Telegram xatosi: {e}")


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Salom! Men 4x40IN savdo botiman.\n"
        "Tizim tirik va bozorni kuzatmoqda. Ish kunlarida (Du–Ju) sizga signallar yuboraman."
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    await update.message.reply_text(
        f"✅ Tizim ishlamoqda.\n"
        f"🕒 Hozirgi vaqt: {now.strftime('%Y-%m-%d %H:%M')}\n"
        f"📅 Bugun: {['Du','Se','Ch','Pa','Ju','Sh','Ya'][now.weekday()]}"
    )


async def trading_loop(bot: Bot):
    brain = TradingBrain()
    auditor = Auditor()

    print("✅ 4x40IN Tizimi o't oldi. Bozor kuzatilmoqda...")
    last_report_date = None

    while True:
        now = datetime.now()
        if now.weekday() <= 4:  # Ish kunlari
            results = await brain.full_scan()
            print(f"\n--- TAHLIL: {now.strftime('%H:%M')} ---")
            for tf, data in results.items():
                print(f"{tf}: {data['dir']} ({data['conf']}%) "
                      f"entry={data['entry']} tp={data['tp']} sl={data['sl']}")
                auditor.log_result(tf, data['dir'])

                if "BUY" in data['dir'] or "SELL" in data['dir']:
                    await send_telegram(bot, _format_signal(tf, data, now))

        if (now.weekday() == REPORT_DAY
                and now.strftime("%H:%M") == REPORT_TIME
                and last_report_date != now.date()):
            path = auditor.export_weekly_report()
            last_report_date = now.date()
            msg = f"📊 Haftalik JSON hisobot saqlandi: {path}"
            print("\n" + msg)
            await send_telegram(bot, msg)

        await asyncio.sleep(60)


async def start_system():
    keep_alive()
    print("🌐 Keep-alive web server yoqildi (port 5000).")

    if not _telegram_configured():
        print("ℹ️ Telegram sozlanmagan — TELEGRAM_TOKEN va CHAT_ID kiriting.")
        return

    application = Application.builder().token(TELEGRAM_TOKEN).build()
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("status", cmd_status))

    await application.initialize()
    await application.start()
    await application.updater.start_polling(drop_pending_updates=True)
    print("📡 Telegram bot ulandi va buyruqlarni qabul qilishga tayyor.")

    bot = application.bot
    await connection_test(bot)

    try:
        await trading_loop(bot)
    finally:
        await application.updater.stop()
        await application.stop()
        await application.shutdown()


async def connection_test(bot: Bot):
    """Vaqtinchalik ulanish testi — tizim ishga tushganda chaqiriladi."""
    try:
        me = await bot.get_me()
        print(f"🔎 Bot ma'lumoti: @{me.username} (id={me.id})")
    except TelegramError as e:
        print(f"⚠️ Bot get_me xatosi: {e}")
        return
    await send_telegram(bot, "4x40IN Tizimi aloqaga chiqdi. Aloqa sifati: 100%")


if __name__ == "__main__":
    asyncio.run(start_system())
