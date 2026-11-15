#!/usr/bin/env python3
"""Offline aggregate report for opt-in group timings; no message contents."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    # Nearest-rank percentile.
    from math import ceil
    return values[max(0, ceil(p * len(values)) - 1)]


def summarize(directory: Path, cutoff: datetime, now: datetime):
    groups = defaultdict(lambda: {"source": [], "filter": [], "pre_send": [],
                                  "send": [], "total": [], "matched": 0, "attempts": 0,
                                  "failed": 0, "stages": Counter()})
    seen_times = []
    for path in sorted(directory.glob('owner_*.jsonl*')):
        try:
            with path.open(encoding='utf-8') as f:
                for line in f:
                    try:
                        row = json.loads(line)
                        stamp = datetime.fromisoformat(row['logged_at_utc'].replace('Z', '+00:00'))
                        if stamp < cutoff or stamp > now or stamp.tzinfo is None:
                            continue
                        stage = row['stage']
                        if stage not in ('group_evaluation', 'group_notification'):
                            continue
                        key = (int(row['owner_id']), int(row['chat_id']))
                        entry = groups[key]
                        if stage == 'group_evaluation':
                            source = row.get('source_to_receive_ms')
                            if isinstance(source, (int, float)):
                                entry['source'].append(source)
                            entry['filter'].append(float(row['filter_ms']))
                            entry['matched'] += bool(row.get('matched'))
                            entry['stages'][row.get('filter_stage', 'other')] += 1
                        else:
                            entry['pre_send'].append(float(row['before_send_ms']))
                            entry['send'].append(float(row['send_ms']))
                            source = row.get('source_to_receive_ms')
                            if isinstance(source, (int, float)):
                                entry['total'].append(float(source) + float(row['before_send_ms']) + float(row['send_ms']))
                            entry['attempts'] += 1
                            entry['failed'] += not bool(row.get('success'))
                        seen_times.append(stamp)
                    except (ValueError, KeyError, TypeError, json.JSONDecodeError):
                        continue
        except OSError:
            continue
    return groups, seen_times


def fmt(values):
    if not values:
        return 'yo‘q'
    return f"n={len(values)}, median={percentile(values, .5):.0f}, p95={percentile(values, .95):.0f}, max={max(values):.0f} ms"


def main():
    parser = argparse.ArgumentParser(description='Tanlangan guruhlar timing hisoboti')
    parser.add_argument('--hours', type=float, default=1)
    parser.add_argument('--show-ids', action='store_true', help='Faqat mahalliy tekshiruv uchun shaxsiy IDlarni ko‘rsatadi')
    select = parser.add_mutually_exclusive_group()
    select.add_argument('--list-owner', type=int, help='Faqat shu egasining faol guruhlarini mahalliy terminalda ko‘rsatadi')
    select.add_argument('--list-admin', action='store_true', help='ADMIN_ID uchun mahalliy guruhlar')
    parser.add_argument('--db', help='Standartdan boshqa baza yo‘li; faqat --list-owner bilan')
    args = parser.parse_args()
    if not 0 < args.hours <= 168:
        parser.error('--hours 0 dan katta va 168 dan oshmasligi kerak')
    from config import BASE_DIR
    if args.list_owner is not None or args.list_admin:
        import sqlite3
        from config import DB_NAME, ADMIN_ID
        owner_id = ADMIN_ID if args.list_admin else args.list_owner
        if owner_id <= 0:
            parser.error('--list-owner musbat ID bo‘lishi kerak')
        path = Path(args.db or DB_NAME).resolve()
        if not path.is_file():
            parser.error('Baza topilmadi; servisning SCANNER_DB_PATH sozlamasini tekshiring')
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as conn:
            rows = conn.execute(
                "SELECT chat_id, title, input_value FROM user_groups "
                "WHERE owner_user_id=? AND is_active=1 AND status='ok' AND chat_id IS NOT NULL "
                "ORDER BY id", (owner_id,)
            ).fetchall()
        print('Mahalliy shaxsiy ma’lumot — ulashishdan oldin tekshiring:')
        for chat, title, original in rows:
            name = (title or original or 'Guruh').replace('\n', ' ').replace('\r', ' ')
            print(f'{owner_id}:{chat}  {name}')
        print('Jami:', len(rows))
        return
    if args.db:
        parser.error('--db faqat guruh ro‘yxati bilan')
    now = datetime.now(timezone.utc)
    groups, times = summarize(BASE_DIR / 'diagnostics' / 'group_trials', now - timedelta(hours=args.hours), now)
    print('Guruhlar:', len(groups))
    if times:
        print('Mavjud yozuvlar UTC:', min(times).isoformat(), '—', max(times).isoformat())
    else:
        print('Tanlangan oraliqda yozuv yo‘q.')
    for n, ((owner, chat), entry) in enumerate(sorted(groups.items()), 1):
        label = f'G{n}' + (f' (owner={owner}, chat={chat})' if args.show_ids else '')
        print(f'\n{label}: filtrlangan={len(entry["filter"])}, mos={entry["matched"]}, yuborish urinishlari={entry["attempts"]}, xato={entry["failed"]}')
        print('  Telegram vaqti → handler:', fmt(entry['source']))
        print('  Filtr:', fmt(entry['filter']))
        print('  Handler → yuborish boshlanishi:', fmt(entry['pre_send']))
        print('  Bot API yuborish:', fmt(entry['send']))
        print('  Telegram vaqti → Bot API javobi:', fmt(entry['total']))
        print('  Filtr bosqichlari:', ', '.join(f'{key}={value}' for key, value in sorted(entry['stages'].items())))
    print('\nEslatma: faqat yozilgan hodisalar; rotatsiya sabab oraliq to‘liq bo‘lmasligi mumkin.')
    print('Telegram vaqti → handler qiymati VPS soatiga bog‘liq; Bot API qabul qilishi telefon ekranida ko‘rinishini kafolatlamaydi.')


if __name__ == '__main__':
    main()
