import asyncio
import aiohttp
import os
import time
from datetime import datetime
from io import BytesIO
from urllib.parse import quote, urlencode, urlparse, urlunparse, parse_qs

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram import F
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramConflictError, TelegramBadRequest
from PIL import Image

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise Exception("BOT_TOKEN не найден!")

SCREENSHOTONE_ACCESS_KEY = os.getenv("SCREENSHOTONE_ACCESS_KEY", "FhUlYo63VR0gXA")

TARGET_URL = os.getenv("TARGET_URL") or os.getenv("URL")
if not TARGET_URL:
    raise Exception("TARGET_URL или URL не найден в переменных окружения!")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

session: aiohttp.ClientSession | None = None

keyboard = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="Получить расписание", callback_data="get_schedule")]
])

async def make_screenshot(url: str) -> BytesIO:
    timestamp = int(time.time() * 1000)
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)
    query_params['_t'] = [str(timestamp)]
    new_query = urlencode(query_params, doseq=True)
    url_with_cache_bust = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
    
    encoded_url = quote(url_with_cache_bust, safe='')
    api_url = (
        f"https://api.screenshotone.com/take"
        f"?access_key={SCREENSHOTONE_ACCESS_KEY}"
        f"&url={encoded_url}"
        f"&format=jpg"
        f"&block_ads=true"
        f"&block_cookie_banners=true"
        f"&block_banners_by_heuristics=true"
        f"&block_trackers=true"
        f"&block_chats=true"
        f"&delay=0"
        f"&timeout=60"
        f"&wait_until=networkidle2"
        f"&wait_until=networkidle0"
        f"&wait_until=domcontentloaded"
        f"&wait_until=load"
        f"&response_type=by_format"
        f"&image_quality=80"
    )

    headers = {
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'
    }

    async with session.get(api_url, headers=headers) as resp:
        if resp.status != 200:
            error_text = await resp.text()
            raise Exception(f"ScreenshotOne ошибка {resp.status}: {error_text[:200]}")
        
        content_type = resp.headers.get('Content-Type', '')
        
        if 'image' not in content_type:
            error_text = await resp.text()
            raise Exception(f"ScreenshotOne вернул не изображение. Content-Type: {content_type}, Ответ: {error_text[:200]}")
        
        buf = BytesIO(await resp.read())
        buf.seek(0)
        return buf

def crop_remove_top_20(img_bytes: BytesIO) -> BytesIO:
    img = Image.open(img_bytes)
    w, h = img.size
    cropped = img.crop((0, int(h * 0.20), w, h))
    out = BytesIO()
    cropped.save(out, "PNG")
    out.seek(0)
    return out

@dp.message(Command("start"))
async def start(m: types.Message):
    msg = await m.answer("Получаю расписание...")
    try:
        raw = await make_screenshot(TARGET_URL)
        final = crop_remove_top_20(raw)
        final.seek(0)

        await m.answer_photo(
            photo=BufferedInputFile(final.read(), filename="schedule.png"),
            reply_markup=keyboard
        )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"Ошибка: {str(e)}")

@dp.callback_query(F.data == "get_schedule")
async def get_schedule(cb: types.CallbackQuery):
    try:
        await cb.answer()
    except TelegramBadRequest:
        pass
    msg = await cb.message.answer("Получаю расписание...")
    try:
        raw = await make_screenshot(TARGET_URL)
        final = crop_remove_top_20(raw)
        final.seek(0)

        await cb.message.answer_photo(
            photo=BufferedInputFile(final.read(), filename="schedule.png"),
            reply_markup=keyboard
        )
        await msg.delete()
    except Exception as e:
        await msg.edit_text(f"Ошибка: {str(e)}")

async def main():
    global session
    try:
        while True:
            try:
                if session is None or session.closed:
                    session = aiohttp.ClientSession()
                print("Бот запущен")
                print(f"Используется URL: {TARGET_URL[:50]}...")
                await dp.start_polling(bot, drop_pending_updates=True)
            except TelegramConflictError as e:
                print(f"Конфликт: другой экземпляр бота запущен. Ожидание 10 секунд...")
                print(f"Ошибка: {e}")
                if session and not session.closed:
                    await session.close()
                await asyncio.sleep(10)
            except Exception as e:
                print(f"Неожиданная ошибка: {e}")
                if session and not session.closed:
                    await session.close()
                await asyncio.sleep(5)
    finally:
        if session and not session.closed:
            await session.close()
        if bot.session and not bot.session.closed:
            await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
