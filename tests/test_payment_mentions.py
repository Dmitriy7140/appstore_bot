import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from services.payment_mentions import name_payment_mentions


class PaymentMentionTests(unittest.IsolatedAsyncioTestCase):
    async def test_existing_api_payment_templates_use_the_same_named_link(self):
        bot = SimpleNamespace(get_chat=AsyncMock(return_value=SimpleNamespace(first_name="Иван")))
        for line in ["💬 📧 123", "💬 id123", "💬 @buyer · id123"]:
            result = await name_payment_mentions(bot, "💳 <b>Оплата App Store</b>\n" + line)
            self.assertIn('<a href="tg://user?id=123">Иван</a>', result)

    async def test_numeric_link_uses_full_name_and_keeps_target(self):
        bot = SimpleNamespace(get_chat=AsyncMock(return_value=SimpleNamespace(first_name="Иван <", last_name="& Петров", username="buyer")))
        text = '<a href="tg://user?id=123">123</a>'
        result = await name_payment_mentions(bot, text + " " + text)
        self.assertEqual(result, '<a href="tg://user?id=123">Иван &lt; &amp; Петров</a> <a href="tg://user?id=123">Иван &lt; &amp; Петров</a>')
        bot.get_chat.assert_awaited_once_with(123)

    async def test_named_mentions_and_unrelated_messages_do_not_make_calls(self):
        bot = SimpleNamespace(get_chat=AsyncMock())
        text = '<a href="tg://user?id=123">Имя</a> <code>123</code> receipt@example.com'
        self.assertEqual(await name_payment_mentions(bot, text), text)
        bot.get_chat.assert_not_called()

    async def test_missing_name_and_unavailable_profile_do_not_break_delivery(self):
        bot = SimpleNamespace(get_chat=AsyncMock(side_effect=[SimpleNamespace(username="buyer"), RuntimeError("unavailable")]))
        text = '<a href="tg://user?id=123">123</a> <a href="tg://user?id=456">id456</a>'
        self.assertEqual(await name_payment_mentions(bot, text), '<a href="tg://user?id=123">@buyer</a> <a href="tg://user?id=456">Покупатель</a>')
