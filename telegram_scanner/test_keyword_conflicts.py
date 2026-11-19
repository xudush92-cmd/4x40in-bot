import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

os.environ.setdefault('ADMIN_ID', '777')
os.environ.setdefault('API_ID', '1')
os.environ.setdefault('API_HASH', 'x')
os.environ.setdefault('BOT_TOKEN', '1:x')

import bot
from keyword_conflicts import preview_entries, find_conflicts, format_conflicts


def accepted(_):
    return None


class ConflictTests(unittest.TestCase):
    def test_new_negative_flags_existing_positive_with_real_score(self):
        old = [('odam bor', 3., 0)]
        new, changed = preview_entries(old, [('odamkk', -5.)], accepted)
        result = find_conflicts(old, new, changed, 3)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][0], 'odam bor')
        self.assertEqual(result[0][2].score, -2)
        self.assertIn('odamkk (-5)', format_conflicts(result, 3))
        self.assertEqual(old, [('odam bor', 3., 0)])

    def test_new_positive_flags_existing_negative(self):
        old = [('odamkk', -5., 0)]
        new, changed = preview_entries(old, [('odam bor', 3.)], accepted)
        self.assertEqual(find_conflicts(old, new, changed, 3)[0][2].score, -2)

    def test_strict_negative_no_conflict(self):
        old = [('odamkk', -5., 1)]
        new, changed = preview_entries(old, [('odam bor', 3.)], accepted)
        self.assertEqual(find_conflicts(old, new, changed, 3), [])

    def test_batch_and_updated_weight_preview(self):
        old = [('odamkk', -4., 0)]
        new, changed = preview_entries(old, [('odamkk', -5.), ('odam bor', 3.)], accepted)
        self.assertEqual(new[0], ('odamkk', -5., 0))
        self.assertEqual(find_conflicts(old, new, changed, 3)[0][2].score, -2)

    def test_duplicate_default_does_not_change(self):
        old = [('odamkk', -5., 0)]
        new, changed = preview_entries(old, [('odamkk', 1.)], accepted)
        self.assertEqual(old, new)
        self.assertFalse(changed)


class HandlerTests(unittest.IsolatedAsyncioTestCase):
    async def test_conflict_waits_without_writing(self):
        msg = SimpleNamespace(text='-5 odamkk', chat=SimpleNamespace(type='private', id=777), from_user=SimpleNamespace(id=777), answer=AsyncMock(), answer_document=AsyncMock())
        state = SimpleNamespace(clear=AsyncMock(), update_data=AsyncMock(), set_state=AsyncMock())
        with patch.object(bot, 'get_keywords_weighted', return_value=[('odam bor', 3., 0)]), patch.object(bot, 'get_match_mode', return_value='weight'), patch.object(bot, 'get_user_score_threshold', return_value=3), patch.object(bot, 'add_keyword_checked') as add:
            await bot.save_new_phrase(msg, state)
        add.assert_not_called()
        state.set_state.assert_awaited_once_with(bot.AddPhrase.waiting_conflict_confirmation)
        msg.answer_document.assert_awaited_once()

    async def test_snapshot_change_blocks_save(self):
        state = SimpleNamespace(get_data=AsyncMock(return_value={'keyword_token': 'abc', 'keyword_snapshot': [], 'keyword_mode': 'weight', 'keyword_threshold': 3, 'pending_keywords': [('odamkk', -5)]}), clear=AsyncMock())
        cb = SimpleNamespace(data='wconf:save:abc', from_user=SimpleNamespace(id=777), message=SimpleNamespace(answer=AsyncMock()), answer=AsyncMock())
        with patch.object(bot, 'get_keywords_weighted', return_value=[('odam bor', 3., 0)]), patch.object(bot, 'add_keyword_checked') as add:
            await bot.words_conflict_decision(cb, state)
        add.assert_not_called()
        state.clear.assert_awaited_once()

    async def test_confirm_applies_pending_keywords(self):
        snapshot = [('odam bor', 3., 0)]
        state = SimpleNamespace(get_data=AsyncMock(return_value={'keyword_token': 'abc', 'keyword_snapshot': [list(r) for r in snapshot], 'keyword_mode': 'weight', 'keyword_threshold': 3, 'pending_keywords': [('odamkk', -5)]}), clear=AsyncMock())
        cb = SimpleNamespace(data='wconf:save:abc', from_user=SimpleNamespace(id=777), message=SimpleNamespace(answer=AsyncMock()), answer=AsyncMock())
        with patch.object(bot, 'get_keywords_weighted', return_value=snapshot), patch.object(bot, 'get_match_mode', return_value='weight'), patch.object(bot, 'get_user_score_threshold', return_value=3), patch.object(bot, '_apply_new_phrases', new_callable=AsyncMock) as apply:
            await bot.words_conflict_decision(cb, state)
        apply.assert_awaited_once_with(cb.message, state, [('odamkk', -5)])

    async def test_old_button_cannot_confirm_new_preview(self):
        state = SimpleNamespace(get_data=AsyncMock(return_value={'keyword_token': 'new'}), clear=AsyncMock())
        cb = SimpleNamespace(data='wconf:save:old', answer=AsyncMock())
        with patch.object(bot, '_apply_new_phrases', new_callable=AsyncMock) as apply:
            await bot.words_conflict_decision(cb, state)
        apply.assert_not_awaited()
        state.clear.assert_not_awaited()

    async def test_cancel_never_saves(self):
        state = SimpleNamespace(get_data=AsyncMock(return_value={'keyword_token': 'abc'}), clear=AsyncMock())
        cb = SimpleNamespace(data='wconf:cancel:abc', message=SimpleNamespace(answer=AsyncMock()), answer=AsyncMock())
        with patch.object(bot, 'add_keyword_checked') as add:
            await bot.words_conflict_decision(cb, state)
        add.assert_not_called()
        state.clear.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
