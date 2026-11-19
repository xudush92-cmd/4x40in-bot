"""Admin uchun faqat o'qiladigan kalit so'zlar namunaviy tekshiruvi."""
from matcher import match_keywords, score_text


def build_keyword_audit(entries, mode, threshold, required):
    """Har bir kalitni xabar sifatida amaldagi barcha kalitlar bilan tekshiradi.

    Bu yakka kalit namunalari, barcha mumkin bo'lgan xabarlar emas.
    """
    entries = list(entries)
    lines = [
        "KALIT SO'ZLAR TEKSHIRUVI",
        f"Rejim: {'ball' if mode == 'weight' else 'kalitlar soni'}",
        f"Jami namuna: {len(entries)}",
        f"Admin chegarasi: {threshold:g} ball" if mode == "weight" else f"Admin sharti: {required} ta kalit",
        "Har bir kalitning o'zi namuna xabar sifatida barcha kalitlar bilan tekshirildi.",
        "Bu barcha xabarlar yoki yozilish variantlarining to'liq tekshiruvi emas.",
        "Guruh, emoji, sessiya va yuborish tekshirilmaydi. Boshqa foydalanuvchining chegarasi farq qilishi mumkin.",
        "Kalit yoki vazn o'zgartirilmagan.",
        "",
    ]
    risks = 0
    for index, (word, weight, strict) in enumerate(entries, 1):
        safe_word = str(word).replace('\n', ' ').replace('\r', ' ')
        lines.append(f"{index}. Namuna: {safe_word} | kalit vazni: {weight:+g} | aniq: {'ha' if strict else 'yoq'}")
        if mode == "weight":
            result = score_text(word, entries, threshold=threshold)
            positives = ', '.join(f'{w} ({v:+g})' for w, v in result.positives.items()) or 'yoq'
            negatives = ', '.join(f'{w} ({v:+g})' for w, v in result.negatives.items()) or 'yoq'
            lines.append(f"  Ball: {result.score:g}/{threshold:g} — {'OTDI' if result.is_match else 'OTMADI'}")
            lines.append(f"  Musbat: {positives}")
            lines.append(f"  Manfiy: {negatives}")
            if weight > 0 and result.negatives:
                risks += 1
                lines.append("  DIQQAT: musbat namuna manfiy kalit bilan ham mos keldi; sababni tekshiring.")
            elif weight > 0 and not result.is_match:
                lines.append("  IZOH: musbat kalitning o'zi chegaraga yetmadi; boshqa kalitlar bilan o'tishi mumkin.")
            elif weight < 0 and result.is_match:
                lines.append("  DIQQAT: manfiy namuna chegaradan o'tdi; kontekstga qarab tekshiring.")
        else:
            words = [entry[0] for entry in entries]
            strict_words = [entry[0] for entry in entries if entry[2]]
            result = match_keywords(word, words, required, strict_words=strict_words)
            lines.append(f"  Topildi: {result.matched_count}/{required} — {'OTDI' if result.is_match else 'OTMADI'}")
            lines.append(f"  Kalitlar: {', '.join(result.matched_words) or 'yoq'}")
            lines.append("  IZOH: son rejimida vaznlar musbat/manfiy sifatida hisoblanmaydi.")
        lines.append("")
    lines.insert(3, f"Manfiy kalit bilan ham mos tushgan musbat namunalar: {risks}" if mode == 'weight' else "Son rejimida manfiy ball qo'llanmaydi.")
    return '\n'.join(lines)
