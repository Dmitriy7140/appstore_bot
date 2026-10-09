import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from services.payment_mentions import name_payment_mentions
from services.two_pay_api_client import get_daily_sales, TwoPayApiError


class PlaystationSalesTests(unittest.IsolatedAsyncioTestCase):
    async def test_ps_api_contract_matches_source_and_day(self):
        for source in ('site', 'tma'):
            response = dict(field='ps_codes', source=source, sales_count=2, sales_rub=1234,
                            period_started_at='2026-08-23T00:00:00+03:00',
                            period_ended_at='2026-08-24T00:00:00+03:00')
            request = AsyncMock(return_value=response)
            with patch('services.two_pay_api_client._request', request):
                sales = await get_daily_sales('ps_codes', date(2026,8,24), source=source)
            self.assertEqual((sales.field,sales.source,sales.sales_count,sales.sales_rub),('ps_codes',source,2,1234))
            self.assertEqual(request.await_args.kwargs['json_body'],dict(field='ps_codes',source=source,period_end_date='2026-08-24'))
            with patch('services.two_pay_api_client._request', AsyncMock(return_value=dict(response,field='appstore_tr'))):
                with self.assertRaises(TwoPayApiError):
                    await get_daily_sales('ps_codes',date(2026,8,24),source=source)

    async def test_ps_tma_title_and_named_link_are_idempotent(self):
        bot=SimpleNamespace(get_chat=AsyncMock(return_value=SimpleNamespace(first_name='Иван',last_name='Петров')))
        message='💳 <b>Оплата Playstation кода (сайт)</b>\nНоминал: <b>10 $</b>\n💬 📧 123\n✅ Код: <code>TEST</code>'
        result=await name_payment_mentions(bot,message)
        self.assertIn('Оплата Playstation кода (TMA)',result)
        self.assertIn('<a href="tg://user?id=123">Иван Петров</a>',result)
        self.assertEqual(await name_payment_mentions(bot,result),result)
        bot.get_chat.assert_awaited_once_with(123)

    async def test_ps_site_email_preserves_site_source(self):
        bot=SimpleNamespace(get_chat=AsyncMock())
        message='💳 <b>Оплата Playstation кода (сайт)</b>\n💬 📧 buyer@example.com'
        self.assertEqual(await name_payment_mentions(bot,message),message)
        bot.get_chat.assert_not_called()
