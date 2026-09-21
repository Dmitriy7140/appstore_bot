import asyncio
import logging
import sqlite3
import tempfile
import unittest
from contextlib import ExitStack, closing
from datetime import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.methods import CopyMessage
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from commands import announce, announcement_builder as builder
from commands.menulink import menu_link_destinations
from keyboards.webapp_buttons import WEB_APP_URL
from repository.sqlite_storage import SQLiteFsmStorage, SQLiteRepository
from services.announcement_posts import MAX_BUTTONS, PROMO_CALLBACK_PREFIX, post_markup, valid_button_url
from services.notification_service import Mailer
from services.scheduler import _send_scheduled_announcement


class AnnouncementBuilderTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "bot.sqlite3"
        self.repository = SQLiteRepository(self.path)
        await self.repository.open()
        self.state = FSMContext(SQLiteFsmStorage(self.repository), StorageKey(bot_id=1, chat_id=3, user_id=3))
        self.bot = SimpleNamespace(copy_message=AsyncMock(return_value=SimpleNamespace(message_id=900)))
        self.callback = SimpleNamespace(
            data="", message=AsyncMock(), from_user=SimpleNamespace(id=3), answer=AsyncMock(), bot=self.bot,
        )
        self.patches = ExitStack()
        for module in (announce, builder):
            self.patches.enter_context(patch.object(module, "get_repository", return_value=self.repository))
        self.patches.enter_context(patch.object(builder, "ADMIN_IDS", [3]))
        self.patches.enter_context(patch("services.scheduler.get_repository", return_value=self.repository))

    async def asyncTearDown(self):
        self.patches.close()
        await self.repository.close()
        self.temp_dir.cleanup()

    def message(self, text="Пост", *, message_id=20, reply_markup=None, caption=None):
        return SimpleNamespace(
            text=text, caption=caption, content_type="text" if text else "photo",
            chat=SimpleNamespace(id=3), message_id=message_id,
            reply_markup=reply_markup, answer=AsyncMock(), bot=self.bot,
        )

    async def begin(self, *, mode="scheduled", markup=None):
        await self.state.set_data({"delivery_mode": mode, "weekday": 5, "send_time": "14:10"})
        await announce.announce_get_message(self.message(reply_markup=markup), self.state)

    async def root(self):
        data = await self.state.get_data()
        return data["post_drafts"][data["root_post_id"]]

    async def add_type(self, kind):
        await builder.choose_button_type(self.callback, self.state)
        self.callback.data = f"ann_build_type:{kind}"
        await builder.select_button_type(self.callback, self.state)

    async def finish_and_preview(self):
        await builder.finish_buttons(self.callback, self.state)
        self.callback.data = "announce_all"
        await announce.announce_get_audience(self.callback, self.state)

    async def test_no_buttons_preserves_input_markup_and_only_saves_after_preview_confirmation(self):
        markup = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="Исходная ссылка", url="https://example.com/?a=1&b=2"),
        ]])
        await self.begin(markup=markup)
        root = await self.root()
        self.assertEqual(await self.state.get_state(), builder.AnnounceState.buttons.state)
        await self.finish_and_preview()
        preview = self.bot.copy_message.call_args.kwargs
        self.assertEqual(preview["reply_markup"], markup)
        self.assertEqual((preview["from_chat_id"], preview["message_id"]), (3, 20))
        self.assertNotIn("parse_mode", preview)
        self.assertNotIn("caption", preview)
        self.assertIsNone(await self.repository.get_announcement_post(root["id"]))
        self.assertEqual(await self.repository.list_schedules(), [])
        await announce.announce_confirm(self.callback, self.state, Mock(), Mock())
        saved = (await self.repository.list_schedules())[0]
        self.assertEqual(saved["post_id"], root["id"])
        self.assertEqual(await self.repository.get_announcement_post(root["id"]), root)

    async def test_all_button_types_and_nested_promotion_survive_restart_and_schedule_deletion(self):
        await self.begin()
        await self.add_type("menu")
        destination = menu_link_destinations()[0]
        self.callback.data = f"ann_build_menu:{destination.callback_data}"
        await builder.select_menu(self.callback, self.state)
        await builder.receive_title(self.message("Открыть меню"), self.state)
        await self.add_type("url")
        await builder.receive_url(self.message("https://example.com/sale?a=1&b=2"), self.state)
        await builder.receive_title(self.message("Наш сайт"), self.state)
        await self.add_type("tma")
        await builder.default_title(self.callback, self.state)
        await self.add_type("promo")
        self.assertEqual(await self.state.get_state(), builder.AnnounceState.promotion_message.state)
        await builder.receive_promotion(self.message(None, message_id=30, caption="Условия со ссылкой"), self.state)
        await builder.receive_title(self.message("Открыть акцию"), self.state)
        await self.add_type("tma")
        await builder.default_title(self.callback, self.state)
        # Promotions themselves can open another prewritten post.
        await self.add_type("promo")
        await builder.receive_promotion(self.message("Подробности", message_id=40), self.state)
        await builder.default_title(self.callback, self.state)
        await builder.finish_buttons(self.callback, self.state)
        await builder.finish_buttons(self.callback, self.state)
        root = await self.root()
        rows = root["reply_markup"]["inline_keyboard"]
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0][0]["callback_data"], destination.callback_data)
        self.assertEqual(rows[1][0]["url"], "https://example.com/sale?a=1&b=2")
        self.assertEqual(rows[2][0]["web_app"]["url"], WEB_APP_URL)
        promo_callback = rows[3][0]["callback_data"]
        self.assertLessEqual(len(promo_callback.encode()), 64)
        await self.finish_and_preview()
        expected_markup = self.bot.copy_message.call_args.kwargs["reply_markup"]
        await announce.announce_confirm(self.callback, self.state, Mock(), Mock())
        schedule = (await self.repository.list_schedules())[0]

        await self.repository.close()
        await self.repository.open()
        mailer = Mailer(self.bot, logging.getLogger(__name__), rate=10000)
        await mailer.start()
        try:
            with (
                patch("services.scheduler.TEST_MODE", False),
                patch("services.scheduler.get_audience", AsyncMock(return_value=[71, 72])),
            ):
                await _send_scheduled_announcement(schedule["id"], mailer)
        finally:
            await mailer.stop()
        deliveries = self.bot.copy_message.call_args_list[-2:]
        self.assertEqual([call.kwargs["chat_id"] for call in deliveries], [71, 72])
        self.assertTrue(all(call.kwargs["reply_markup"] == expected_markup for call in deliveries))
        await self.repository.delete_schedule(schedule["id"])
        self.callback.from_user.id = 71  # Non-admin, outside every constructor state.
        self.callback.data = promo_callback
        await builder.open_promotion(self.callback, self.state)
        promo = self.bot.copy_message.call_args.kwargs
        self.assertEqual((promo["chat_id"], promo["message_id"]), (71, 30))
        self.assertEqual(promo["reply_markup"].inline_keyboard[0][0].web_app.url, WEB_APP_URL)
        self.callback.data = promo["reply_markup"].inline_keyboard[1][0].callback_data
        await builder.open_promotion(self.callback, self.state)
        self.assertEqual(self.bot.copy_message.call_args.kwargs["message_id"], 40)

    async def test_immediate_delivery_uses_preview_keyboard_and_persists_promotion(self):
        await self.begin(mode="now")
        await self.add_type("promo")
        await builder.receive_promotion(self.message("Акция", message_id=30), self.state)
        await builder.default_title(self.callback, self.state)
        await builder.finish_buttons(self.callback, self.state)
        root = await self.root()
        await self.finish_and_preview()
        preview_markup = self.bot.copy_message.call_args.kwargs["reply_markup"]
        mailer = Mailer(self.bot, logging.getLogger(__name__), rate=10000)
        await mailer.start()
        try:
            with patch.object(announce, "TEST_MODE", True), patch.object(announce, "ADMIN_IDS", [71]):
                await announce.announce_confirm(self.callback, self.state, mailer, Mock())
        finally:
            await mailer.stop()
        actual = self.bot.copy_message.call_args.kwargs
        self.assertEqual(actual["reply_markup"], preview_markup)
        self.assertEqual(actual["chat_id"], 71)
        promo_id = root["reply_markup"]["inline_keyboard"][0][0]["callback_data"].removeprefix(PROMO_CALLBACK_PREFIX)
        self.assertIsNotNone(await self.repository.get_announcement_post(promo_id))
        self.assertEqual(await self.repository.list_schedules(), [])

    async def test_preview_promotion_is_admin_only_and_cancel_does_not_publish(self):
        await self.begin()
        await self.add_type("promo")
        await builder.receive_promotion(self.message("Черновик", message_id=30), self.state)
        await builder.default_title(self.callback, self.state)
        await builder.finish_buttons(self.callback, self.state)
        root = await self.root()
        self.callback.data = root["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
        self.bot.copy_message.reset_mock()
        self.callback.from_user.id = 71
        await builder.open_promotion(self.callback, self.state)
        self.bot.copy_message.assert_not_awaited()
        self.callback.from_user.id = 3
        await builder.open_promotion(self.callback, self.state)
        self.assertEqual(self.bot.copy_message.call_args.kwargs["message_id"], 30)
        await announce.announce_cancel(self.callback, self.state)
        self.bot.copy_message.reset_mock()
        await builder.open_promotion(self.callback, self.state)
        self.bot.copy_message.assert_not_awaited()
        self.assertIsNone(await self.repository.get_announcement_post(root["id"]))

    async def test_limits_invalid_link_and_undo_keep_constructor_usable(self):
        await self.begin()
        await self.add_type("url")
        for value in ("example.com", "javascript:alert(1)", "https://", "https://bad url", "https://x:bad", "https://[broken"):
            await builder.receive_url(self.message(value), self.state)
            self.assertEqual(await self.state.get_state(), builder.AnnounceState.button_url.state)
        await builder.receive_url(self.message("https://example.com"), self.state)
        await builder.receive_title(self.message("x" * 65), self.state)
        self.assertEqual(await self.state.get_state(), builder.AnnounceState.button_title.state)
        await builder.default_title(self.callback, self.state)
        data = await self.state.get_data()
        post = data["post_drafts"][data["root_post_id"]]
        post["reply_markup"]["inline_keyboard"] = [
            [{"text": f"Кнопка {i}", "url": "https://example.com"}] for i in range(MAX_BUTTONS)
        ]
        await self.state.update_data(post_drafts=data["post_drafts"])
        await builder.show_buttons(self.callback.message, self.state)
        markup = self.callback.message.answer.call_args.kwargs["reply_markup"]
        self.assertNotIn("ann_build_add", [button.callback_data for row in markup.inline_keyboard for button in row])
        await builder.choose_button_type(self.callback, self.state)
        self.assertEqual(await self.state.get_state(), builder.AnnounceState.buttons.state)
        self.assertEqual(sum(map(len, post_markup(post).inline_keyboard)), 100)
        await builder.undo_button(self.callback, self.state)
        await self.add_type("tma")
        await builder.default_title(self.callback, self.state)
        self.assertEqual(sum(map(len, post_markup(await self.root()).inline_keyboard)), 100)

    async def test_preview_failure_or_editing_prevents_saving_without_new_preview(self):
        await self.begin()
        await builder.finish_buttons(self.callback, self.state)
        self.callback.data = "announce_all"
        self.bot.copy_message.side_effect = TelegramBadRequest(
            method=CopyMessage(chat_id=3, from_chat_id=3, message_id=20), message="Message not found",
        )
        await announce.announce_get_audience(self.callback, self.state)
        await announce.announce_confirm(self.callback, self.state, Mock(), Mock())
        self.assertEqual(await self.repository.list_schedules(), [])
        self.bot.copy_message.side_effect = None
        await announce.announce_get_audience(self.callback, self.state)
        await announce.edit_draft_buttons(self.callback, self.state)
        await announce.announce_confirm(self.callback, self.state, Mock(), Mock())
        self.assertEqual(await self.repository.list_schedules(), [])
        await self.finish_and_preview()
        await announce.announce_confirm(self.callback, self.state, Mock(), Mock())
        self.assertEqual(len(await self.repository.list_schedules()), 1)

    async def test_cancelled_or_removed_promotion_is_not_persisted(self):
        await self.begin()
        await self.add_type("promo")
        await builder.receive_promotion(self.message("Лишняя акция", message_id=30), self.state)
        await builder.default_title(self.callback, self.state)
        data = await self.state.get_data()
        abandoned_id = data["builder_stack"][-1]["post_id"]
        await builder.cancel_builder(self.callback, self.state)
        await self.finish_and_preview()
        await announce.announce_confirm(self.callback, self.state, Mock(), Mock())
        self.assertIsNone(await self.repository.get_announcement_post(abandoned_id))

    async def test_schema_v2_upgrade_preserves_schedules_without_buttons(self):
        await self.repository.put_schedule(
            weekday=5, send_time=time(14, 10), audience="all", source_chat_id=3,
            source_message_id=20, created_by=3,
        )
        await self.repository.close()
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("ALTER TABLE scheduled_announcements DROP COLUMN post_id")
            connection.execute("DROP TABLE announcement_posts")
            connection.execute("PRAGMA user_version = 2")
            connection.commit()
        await self.repository.open()
        schedules = await self.repository.list_schedules()
        self.assertEqual(len(schedules), 1)
        self.assertEqual(schedules[0]["source_message_id"], 20)
        self.assertIsNone(schedules[0]["post_id"])

    async def test_deleted_schedule_rolls_back_new_posts_and_saved_posts_are_immutable(self):
        await self.begin()
        root = await self.root()
        with self.assertRaises(LookupError):
            await self.repository.put_schedule(
                weekday=5, send_time=time(14, 10), audience="all", source_chat_id=3,
                source_message_id=20, created_by=3, schedule_id=999,
                post_id=root["id"], posts=[root],
            )
        self.assertIsNone(await self.repository.get_announcement_post(root["id"]))
        await self.repository.save_announcement_posts([root], 3)
        root["source_message_id"] = 21
        with self.assertRaises(ValueError):
            await self.repository.save_announcement_posts([root], 3)
        self.assertEqual((await self.repository.get_announcement_post(root["id"]))["source_message_id"], 20)


class ButtonUrlTest(unittest.TestCase):
    def test_accepts_telegram_and_web_links(self):
        for url in ("tg://resolve?domain=telegram", "https://example.com/акция?a=1&b=2", "http://example.com"):
            self.assertTrue(valid_button_url(url))


if __name__ == "__main__":
    unittest.main()
