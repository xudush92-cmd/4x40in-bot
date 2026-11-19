"""Kalitlar qo'shilishidan oldin namunaviy, faqat o'qiladigan tekshiruv."""
from matcher import canonical_entry, display_entry, score_text


def preview_entries(existing, additions, reject_reason):
    """Qo'shish handleridagi takror, vazn va strict qoidalarini modellashtiradi."""
    result = [tuple(row) for row in existing]
    changed = set()
    for word, weight in additions:
        if reject_reason(word):
            continue
        canonical = canonical_entry(word)
        found = next((i for i, row in enumerate(result) if canonical_entry(row[0]) == canonical), None)
        if found is None:
            result.append((display_entry(word), max(-10., min(10., float(weight))), 0))
            changed.add(canonical)
        elif weight != 1.0:
            old = result[found]
            updated = (old[0], max(-10., min(10., float(weight))), old[2])
            if updated != old:
                changed.add(canonical)
            result[found] = updated
    return result, changed


def find_conflicts(existing, proposed, changed, threshold):
    """Yangi/o'zgargan musbat namunalar va mavjud musbat namunalarni solishtiradi.

    Faqat real scorer chiqargan manfiy mosliklar ko'rsatiladi.
    """
    if not changed:
        return []
    conflicts = []
    for word, weight, _strict in proposed:
        if weight <= 0:
            continue
        before = score_text(word, existing, threshold=threshold)
        after = score_text(word, proposed, threshold=threshold)
        sample_changed = canonical_entry(word) in changed
        introduced = {k: v for k, v in after.negatives.items()
                      if canonical_entry(k) in changed or k not in before.negatives or before.negatives[k] != v}
        negatives = after.negatives if sample_changed else introduced
        if negatives:
            conflicts.append((word, before, after, negatives))
    return conflicts


def format_conflicts(conflicts, threshold):
    lines = ["KALITLAR ZIDDIYATI — NAMUNAVIY TEKSHIRUV",
             f"Admin chegarasi: {threshold:g}",
             "Kalitlar saqlangandan keyingi real ball ko'rsatilgan.",
             "Har bir musbat kalitning o'zi namuna sifatida tekshirildi; barcha xabar va imlo variantlari qamrab olinmaydi.", ""]
    for i, (sample, before, after, negatives) in enumerate(conflicts, 1):
        lines.extend([f"{i}. Namuna: {sample}",
                      "  Aloqador manfiy: " + ', '.join(f'{w} ({v:+g})' for w, v in negatives.items()),
                      "  Barcha musbat: " + (', '.join(f'{w} ({v:+g})' for w, v in after.positives.items()) or 'yoq'),
                      "  Barcha manfiy: " + (', '.join(f'{w} ({v:+g})' for w, v in after.negatives.items()) or 'yoq'),
                      f"  Oldin: {before.score:g}; keyin: {after.score:g}/{threshold:g} — {'OTDI' if after.is_match else 'OTMADI'}", ""])
    return '\n'.join(lines)
