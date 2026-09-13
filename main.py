import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery

from config import (
    TELEGRAM_BOT_TOKEN, TELEGRAM_ADMIN_ID, COVER_LETTER,
    TARGET_QUERIES, HH_AREA_MOSCOW, HH_AREA_SPB, MAX_RESULTS_PER_QUERY
)
from hh_client import HHClient
from db import init_db, mark_seen, was_seen, response_status, save_response, stats

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hh-autopilot")

dp = Dispatcher()
hh = HHClient()
pending = {}

class LoginState(StatesGroup):
    waiting_code = State()

def admin(uid: int) -> bool:
    return bool(TELEGRAM_ADMIN_ID and uid == TELEGRAM_ADMIN_ID)

def apply_keyboard(vacancy_id: str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Откликнуться", callback_data=f"apply:{vacancy_id}")],
        [InlineKeyboardButton(text="Пропустить", callback_data=f"skip:{vacancy_id}")]
    ])

@dp.message(Command("start"))
async def start(message: Message):
    if not admin(message.from_user.id):
        return
    logged = await hh.is_logged_in()
    await message.answer(
        "HH Autopilot Alex запущен.\n"
        f"HH: {'авторизован' if logged else 'не авторизован'}\n\n"
        "/login — войти в HH\n"
        "/search — поиск целевых вакансий\n"
        "/stats — статистика\n\n"
        "Можно просто прислать ссылку на вакансию hh.ru."
    )

@dp.message(Command("login"))
async def login(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return
    await message.answer("Запрашиваю код авторизации у HH…")
    result = await hh.login_step1_send_phone()
    if result == "code_sent":
        await state.set_state(LoginState.waiting_code)
        await message.answer("HH отправил код. Пришли сюда только цифры кода.")
    elif result == "already_logged_in":
        await message.answer("Ты уже авторизован в HH.")
    elif result == "error:captcha":
        await message.answer("HH показал CAPTCHA. Автоматически её не обходим.")
    else:
        await message.answer(f"Не удалось начать вход: {result}")

@dp.message(LoginState.waiting_code)
async def login_code(message: Message, state: FSMContext):
    if not admin(message.from_user.id):
        return
    code = (message.text or "").strip()
    if not code.isdigit():
        await message.answer("Нужны только цифры кода.")
        return
    result = await hh.login_step2_enter_code(code)
    if result == "success":
        await state.clear()
        await message.answer("Готово. HH-сессия сохранена. Теперь пришли одну ссылку на вакансию.")
    elif result == "wrong_code":
        await message.answer("HH считает код неверным. Пришли новый код.")
    elif result == "error:captcha":
        await message.answer("HH показал CAPTCHA. Здесь останавливаемся — обходить её не будем.")
    else:
        await message.answer(f"Авторизация не подтверждена: {result}")

@dp.message(Command("stats"))
async def stats_cmd(message: Message):
    if not admin(message.from_user.id):
        return
    s = stats()
    await message.answer(
        f"Отклики: {s['sent']}\n"
        f"Ошибки/неподтверждённые: {s['failed']}\n"
        f"Всего записей: {s['total']}"
    )

@dp.message(Command("search"))
async def search_cmd(message: Message):
    if not admin(message.from_user.id):
        return
    if not await hh.is_logged_in():
        await message.answer("Сначала /login")
        return

    await message.answer("Ищу свежие управленческие вакансии…")
    shown = 0
    for area in [HH_AREA_MOSCOW, HH_AREA_SPB]:
        for q in TARGET_QUERIES:
            results = await hh.search(q, area=area, limit=MAX_RESULTS_PER_QUERY)
            if results and results[0].get("error") == "captcha":
                await message.answer("HH показал CAPTCHA во время поиска. Поиск остановлен.")
                return
            for v in results:
                if was_seen(v["id"]):
                    continue
                mark_seen(v["id"])
                pending[v["id"]] = v
                shown += 1
                await message.answer(
                    f"{v['title']}\n{v.get('company') or 'Компания не распознана'}\n{v['url']}",
                    reply_markup=apply_keyboard(v["id"])
                )
                if shown >= 20:
                    await message.answer("Показал первые 20 новых подходящих вакансий.")
                    return
    await message.answer(f"Готово. Новых вакансий: {shown}")

@dp.message(F.text.contains("hh.ru/vacancy/"))
async def vacancy_link(message: Message):
    if not admin(message.from_user.id):
        return
    if not await hh.is_logged_in():
        await message.answer("Сначала /login")
        return

    url = (message.text or "").strip()
    v = await hh.get_vacancy(url)
    if not v:
        await message.answer("Не смог распознать ссылку на вакансию.")
        return
    if v.get("error") == "captcha":
        await message.answer("HH показал CAPTCHA. Автоматически её не обходим.")
        return
    if response_status(v["id"]) == "sent":
        await message.answer("На эту вакансию уже был подтверждённый отклик.")
        return

    pending[v["id"]] = v
    desc = (v.get("description") or "").replace("\n", " ")
    if len(desc) > 500:
        desc = desc[:500] + "…"
    await message.answer(
        f"{v['title']}\n"
        f"{v['company']}\n\n"
        f"{desc}\n\n"
        f"Сопроводительное письмо:\n{COVER_LETTER}",
        reply_markup=apply_keyboard(v["id"])
    )

@dp.callback_query(F.data.startswith("skip:"))
async def skip_cb(cb: CallbackQuery):
    if not admin(cb.from_user.id):
        return
    vid = cb.data.split(":", 1)[1]
    pending.pop(vid, None)
    await cb.answer("Пропущено")
    await cb.message.edit_reply_markup(reply_markup=None)

@dp.callback_query(F.data.startswith("apply:"))
async def apply_cb(cb: CallbackQuery):
    if not admin(cb.from_user.id):
        return
    vid = cb.data.split(":", 1)[1]
    v = pending.get(vid)
    if not v:
        await cb.answer("Карточка устарела", show_alert=True)
        return
    if response_status(vid) == "sent":
        await cb.answer("Уже откликались", show_alert=True)
        return

    await cb.answer("Отправляю…")
    result = await hh.apply(v, COVER_LETTER)
    if result in ("sent", "already_applied"):
        save_response(vid, v["title"], v["company"], "sent")
        await cb.message.answer(f"Подтверждено HH: отклик отправлен.\n{v['url']}")
        await cb.message.edit_reply_markup(reply_markup=None)
    elif result == "captcha":
        save_response(vid, v["title"], v["company"], "failed")
        await cb.message.answer("HH показал CAPTCHA. Отклик не считаю отправленным.")
    else:
        save_response(vid, v["title"], v["company"], "failed")
        await cb.message.answer(
            f"HH не подтвердил отправку: {result}\n"
            "Я не отмечаю это как успешный отклик."
        )

async def main():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is empty")
    if not TELEGRAM_ADMIN_ID:
        raise RuntimeError("TELEGRAM_ADMIN_ID is empty")

    init_db()
    await hh.start()
    bot = Bot(TELEGRAM_BOT_TOKEN)
    try:
        await dp.start_polling(bot)
    finally:
        await hh.stop()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
