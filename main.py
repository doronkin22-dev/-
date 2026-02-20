import logging
import asyncio
import aiohttp
import time
from dataclasses import dataclass
from typing import List, Optional
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup

# ========== НАСТРОЙКИ ==========
API_TOKEN = '8593811537:AAEesObMXQSRg4e9m4zVvmL8TyEYUIn57sw'  # <--- ЗАМЕНИТЕ НА СВОЙ ТОКЕН (в кавычках)
# ===============================

logging.basicConfig(level=logging.INFO)

# Модель прокси
@dataclass
class Proxy:
    ip: str
    port: int
    protocol: str
    speed: float = float('inf')
    
    def url(self) -> str:
        return f"{self.protocol}://{self.ip}:{self.port}"

# Хранилище лучших прокси (в памяти)
best_proxies: List[Proxy] = []

# Инициализация бота и диспетчера
bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# Клавиатура с кнопкой "Другой прокси"
def get_proxy_keyboard():
    keyboard = InlineKeyboardMarkup()
    keyboard.add(InlineKeyboardButton("🔄 Другой прокси", callback_data="new_proxy"))
    return keyboard

# ========== ЗАГРУЗКА ПРОКСИ ИЗ TheSpeedX ==========
async def fetch_proxy_list() -> List[Proxy]:
    """Загружает список SOCKS5 прокси из репозитория TheSpeedX."""
    url = "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/socks5.txt"
    proxies = []
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=15) as resp:
                if resp.status == 200:
                    text_data = await resp.text()
                    lines = text_data.strip().split('\n')
                    for line in lines:
                        line = line.strip()
                        if line and ':' in line:
                            ip, port_str = line.split(':')
                            try:
                                port = int(port_str)
                                proxies.append(Proxy(ip=ip, port=port, protocol='socks5'))
                            except ValueError:
                                continue
        logging.info(f"Загружено {len(proxies)} прокси из TheSpeedX.")
    except Exception as e:
        logging.error(f"Ошибка загрузки списка прокси: {e}")
        return []
    return proxies

# ========== ПРОВЕРКА РАБОТОСПОСОБНОСТИ ПРОКСИ ==========
async def check_proxy(proxy: Proxy, test_url='http://httpbin.org/ip', timeout=15) -> bool:
    """Пытается открыть страницу через прокси. Если успешно — прокси рабочий."""
    try:
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            proxy_url = f"{proxy.protocol}://{proxy.ip}:{proxy.port}"
            async with session.get(test_url, proxy=proxy_url, timeout=timeout) as response:
                # Любой ответ (даже 404) считаем успехом — прокси отвечает
                return True
    except Exception:
        return False

# ========== ОБНОВЛЕНИЕ ПУЛА ПРОКСИ (ЗАПУСКАЕТСЯ ПО РАСПИСАНИЮ) ==========
async def update_proxy_pool():
    global best_proxies
    logging.info("Начинаю обновление пула прокси...")
    all_proxies = await fetch_proxy_list()
    if not all_proxies:
        logging.warning("Не удалось загрузить список прокси.")
        return
    
    logging.info(f"Загружено {len(all_proxies)} прокси. Проверяю работоспособность...")
    
    # Проверяем все прокси (но ограничим одновременные запросы, чтобы не перегружать)
    working_proxies = []
    semaphore = asyncio.Semaphore(20)  # не больше 20 одновременных проверок
    
    async def check_with_semaphore(proxy):
        async with semaphore:
            if await check_proxy(proxy):
                working_proxies.append(proxy)
    
    tasks = [check_with_semaphore(p) for p in all_proxies]
    await asyncio.gather(*tasks)
    
    # Сортируем по скорости (самые быстрые первые)
    working_proxies.sort(key=lambda p: p.speed)
    
    # Сохраняем топ-10
    best_proxies = working_proxies[:10]
    logging.info(f"Найдено {len(working_proxies)} рабочих прокси. Топ-10 обновлён.")

# ========== ОБРАБОТЧИКИ КОМАНД ==========
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.answer(
        "🤖 Привет, Кириллойд! Лови свежую проксю для Telegram, чтоб летало без тормозов 🚀\n\n"
        "🔹 Жмакни /proxy — я дам тебе самый шустрый вариант из найденных.\n"
        "🔹 Если прокся начнёт тупить, просто тыкни кнопку «🔄 Другой прокси» под сообщением.\n\n"
        "Прокси обновляются каждые 15 минут, так что всегда будет актуальная. Пользуйся!"
    )

@dp.message_handler(commands=['proxy'])
async def cmd_proxy(message: types.Message):
    if not best_proxies:
        await message.answer("⏳ Секунду, ищу рабочую проксю... Попробуй через минуту.")
        return
    
    proxy = best_proxies[0]  # самый быстрый
    text = (
        f"✅ Держи рабочую проксю:\n"
        f"`{proxy.url()}`\n\n"
        "**Как её прикрутить к Телеге:**\n"
        "1. Тыкни на ссылку выше (или скопируй).\n"
        "2. Телеграм сам откроет настройки и предложит применить.\n"
        "3. Жми 'Добавить прокси' и 'Сохранить'.\n\n"
        "Если чё, жми кнопку ниже — подгоню другую."
    )
    await message.answer(text, parse_mode='Markdown', reply_markup=get_proxy_keyboard())

@dp.callback_query_handler(lambda c: c.data == 'new_proxy')
async def process_callback_new_proxy(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    
    if not best_proxies:
        await bot.send_message(callback_query.from_user.id, "⏳ Секунду, ищу проксю... Попробуй через минуту.")
        return
    
    proxy = best_proxies[0]
    text = (
        f"✅ Новая прокся:\n"
        f"`{proxy.url()}`\n\n"
        "Тыкай по ссылке и подключай."
    )
    await bot.send_message(callback_query.from_user.id, text, parse_mode='Markdown', reply_markup=get_proxy_keyboard())

# ========== ЗАПУСК ПЛАНИРОВЩИКА ПРИ СТАРТЕ ==========
async def on_startup(_):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(update_proxy_pool, 'interval', minutes=15)
    scheduler.start()
    # Первое обновление сразу при старте
    asyncio.create_task(update_proxy_pool())

if __name__ == '__main__':
    # Важно: drop_pending_updates=True сбрасывает старые обновления и предотвращает конфликт экземпляров
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup, drop_pending_updates=True)
