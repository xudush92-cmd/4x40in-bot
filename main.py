import asyncio
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError

from brain import TradingBrain
from auditor import Auditor
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


async def start_system():
    brain = TradingBrain()
    auditor = Auditor()

    bot = None
    if _telegram_configured():
        bot = Bot(token=TELEGRAM_TOKEN)
        print("📡 Telegram bot ulandi.")
        await connection_test(bot)
    else:
        print("ℹ️ Telegram sozlanmagan — TELEGRAM_TOKEN va CHAT_ID kiriting (config.py yoki environment).")

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

                # Faqat haqiqiy signallarni (BUY/SELL) Telegramga jo'natamiz
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


async def connection_test(bot: Bot):
    """Vaqtinchalik ulanish testi — tizim ishga tushganda chaqiriladi."""
    try:
        me = await bot.get_me()
        print(f"🔎 Bot ma'lumoti: @{me.username} (id={me.id})")
    except TelegramError as e:
        print(f"⚠️ Bot get_me xatosi: {e}")
        return
    try:
        await bot.send_message(
            chat_id=CHAT_ID,
            text="4x40IN Tizimi aloqaga chiqdi. Aloqa sifati: 100%",
        )
        print("✅ Telegram ulanish testi muvaffaqiyatli — xabar yuborildi.")
    except TelegramError as e:
        print(f"⚠️ Telegram ulanish testi xatosi: {e}")


if __name__ == "__main__":
    asyncio.run(start_system())
