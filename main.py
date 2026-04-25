import asyncio
from brain import TradingBrain
from auditor import Auditor
from config import REPORT_DAY, REPORT_TIME
from datetime import datetime

async def start_system():
    brain = TradingBrain()
    auditor = Auditor()
    print("✅ 4x40IN Tizimi o't oldi. Bozor kuzatilmoqda...")

    last_report_date = None

    while True:
        now = datetime.now()
        if now.weekday() <= 4: # Ish kunlari
            results = await brain.full_scan()
            print(f"\n--- TAHLIL: {now.strftime('%H:%M')} ---")
            for tf, data in results.items():
                print(f"{tf}: {data['dir']} ({data['conf']}%)")
                auditor.log_result(tf, data['dir'])

        if (now.weekday() == REPORT_DAY
                and now.strftime("%H:%M") == REPORT_TIME
                and last_report_date != now.date()):
            path = auditor.export_weekly_report()
            last_report_date = now.date()
            print(f"\n📊 Haftalik JSON hisobot saqlandi: {path}")

        await asyncio.sleep(60)

if __name__ == "__main__":
    asyncio.run(start_system())
    