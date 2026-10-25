#!/usr/bin/env python3
"""O'qitish to'plamini joriy kalit so'zlar ro'yxati bilan o'lchaydi.

Ishlatish::

    python3 o_qitish/baholash.py
    python3 o_qitish/baholash.py --threshold 2.5
    python3 o_qitish/baholash.py --xato 25      # ko'proq xato ko'rsatadi

Skript repo ichidagi ``telegram_scanner`` modullaridan foydalanadi, lekin
bazaga tegmaydi: ro'yxat ``kalit-sozlar-tavsiya.txt`` dan o'qiladi.

Baholash tartibi bot bilan bir xil (``filters.evaluate``):

    1. Emoji / stiker bor  -> haydovchi belgisi, BLOK
    2. Ball >= chegara     -> mijoz xabari, O'TADI
    3. Aks holda           -> o'tkazib yuboriladi

Ya'ni "mijoz" xabari o'tishi, "haydovchi" va "boshqa" xabarlari esa
o'tmasligi kerak.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "telegram_scanner"))

from matcher import contains_emoji, parse_weighted_entries, score_text  # noqa: E402

DATA = Path(__file__).resolve().parent / "qitish-matnlari.tsv"
WORDS = ROOT / "kalit-sozlar-tavsiya.txt"

MIJOZ = "mijoz"
HAYDOVCHI = "haydovchi"
BOSHQA = "boshqa"


def load_dataset(path: Path = DATA, allow_duplicates: bool = False) -> list[tuple[str, str]]:
    """``[(yorliq, matn), ...]`` — yorliq: mijoz / haydovchi / boshqa."""
    rows: list[tuple[str, str]] = []
    seen: dict[str, str] = {}
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) != 2:
            raise ValueError(f"{path.name}:{line_no}: yorliq va matn TAB bilan ajratilsin")
        label, text = parts[0].strip(), parts[1].strip()
        if label not in (MIJOZ, HAYDOVCHI, BOSHQA):
            raise ValueError(f"{path.name}:{line_no}: noma'lum yorliq: {label}")
        if not text:
            raise ValueError(f"{path.name}:{line_no}: matn bo'sh")
        if text in seen and not allow_duplicates:
            raise ValueError(
                f"{path.name}:{line_no}: takror xabar (avval {seen[text]} qatorda): {text}"
            )
        seen[text] = f"{line_no}"
        rows.append((label, text))
    return rows


def load_words(path: Path = WORDS) -> list[tuple[str, float]]:
    return parse_weighted_entries(path.read_text(encoding="utf-8"))


def verdict(text: str, words, threshold: float) -> tuple[bool, str, float]:
    """Bot qabul qiladimi: ``(o'tadi, sabab, ball)``."""
    if contains_emoji(text):
        return False, "emoji", 0.0
    result = score_text(text, words, threshold=threshold)
    if result.is_match:
        return True, "ball", result.score
    return False, "ball", result.score


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="O'qitish to'plamini o'lchash")
    parser.add_argument("--threshold", type=float, default=1.75)
    parser.add_argument("--xato", type=int, default=12, help="nechta xato ko'rsatilsin")
    args = parser.parse_args(argv)

    rows = load_dataset()
    words = load_words()
    total = {MIJOZ: 0, HAYDOVCHI: 0, BOSHQA: 0}
    passed = {MIJOZ: 0, HAYDOVCHI: 0, BOSHQA: 0}
    errors: list[tuple[str, str, str, float]] = []

    for label, text in rows:
        total[label] += 1
        ok, reason, score = verdict(text, words, args.threshold)
        if ok:
            passed[label] += 1
        # Xato: mijoz o'tmadi, yoki haydovchi/boshqa o'tib ketdi.
        if (label == MIJOZ and not ok) or (label != MIJOZ and ok):
            errors.append((label, text, reason, score))

    print(f"Ro'yxat: {len(words)} yozuv | to'plam: {len(rows)} xabar | "
          f"chegara: {args.threshold:g}\n")
    header = "Yorliq    Jami  O'tdi   Foiz   Izoh"
    print(header)
    for label in (MIJOZ, HAYDOVCHI, BOSHQA):
        tot, pas = total[label], passed[label]
        if label == MIJOZ:
            print(f"{label:<10}{tot:>6}{pas:>7}{pas * 100 / tot:>7.1f}%   qancha topildi")
        else:
            print(f"{label:<10}{tot:>6}{pas:>7}{pas * 100 / tot:>7.1f}%   xato (0% bo'lsin)")
    mijoz_ok = passed[MIJOZ] / total[MIJOZ] * 100
    print(f"\nAniqlik: mijoz {mijoz_ok:.1f}% | "
          f"haydovchi xatosi {passed[HAYDOVCHI]}/{total[HAYDOVCHI]} | "
          f"boshqa xatosi {passed[BOSHQA]}/{total[BOSHQA]}")

    if errors:
        print(f"\nXatolar ({len(errors)} ta, {args.xato} tasi ko'rsatiladi):")
        for label, text, reason, score in errors[: args.xato]:
            kind = "O'TMADI" if label == MIJOZ else "O'TIB KETDI"
            print(f"  [{label:<9}] {kind:<11} ball {score:>5.2f}  {text}")
    # Qaysi yozuvlar xatoga ko'proq sabab bo'lyapti — ro'yxatni tuzatish uchun.
    counter: dict[str, int] = {}
    for label, text, _reason, _score in errors:
        result = score_text(text, words, threshold=args.threshold)
        for word in list(result.positives) + list(result.negatives):
            counter[word] = counter.get(word, 0) + 1
    if counter:
        print("\nXatolarda qatnashgan yozuvlar:")
        for word, count in sorted(counter.items(), key=lambda kv: -kv[1])[:15]:
            print(f"  {count:>3}x  {word}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
