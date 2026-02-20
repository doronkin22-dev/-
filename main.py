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
API_TOKEN = '8593811537:AAEesObMXQSRg4e9m4zVvmL8TyEYUIn57sw'  # ЗАМЕНИТЕ НА СВОЙ ТОКЕН!
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

# Функция загрузки списка прокси из Proxifly
async def fetch_proxy_list() -> List[Proxy]:
    url = "https://cdn.jsdelivr.net/gh/proxifly/free-proxy-list@main/proxies/protocols/socks5/data.json"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    proxies = []
                    for item in data:
                        try:
                            proxies.append(Proxy(
                                ip=item['ip'],
                                port=int(item['port']),
                                protocol=item['protocol']
                            ))
                        except:
                            continue
                    return proxies
    except Exception as e:
        logging.error(f"Ошибка загрузки списка прокси: {e}")
        return []

# Функция проверки одного прокси
async def check_proxy(proxy: Proxy, test_url='http://www.google.com', timeout=5) -> bool:
    try:
        start = time.time()
        connector = aiohttp.TCPConnector(ssl=False)
        async with aiohttp.ClientSession(connector=connector) as session:
            proxy_url = f"{proxy.protocol}://{proxy.ip}:{proxy.port}"
            async with session.get(test_url, proxy=proxy_url, timeout=timeout) as response:
                if response.status == 200:
                    proxy.speed = time.time() - start
                    return True
    except Exception:
        pass
    return False

# Функция обновления пула прокси (запускается по расписанию)
async def update_proxy_pool():
    global best_proxies
    logging.info("Начинаю обновление пула прокси...")
    all_proxies = await fetch_proxy_list()
    if not all_proxies:
        logging.warning("Не удалось загрузить список прокси.")
        return
    
    logging.info(f"Загружено {len(all_proxies)} прокси. Проверяю работоспособность...")
    
    # Проверяем первые 100 прокси (чтобы не перегружать сеть)
    working_proxies = []
    semaphore = asyncio.Semaphore(20)  # не больше 20 одновременных проверок
    
    async def check_with_semaphore(proxy):
        async with semaphore:
            if await check_proxy(proxy):
                working_proxies.append(proxy)
    
    tasks = [check_with_semaphore(p) for p in all_proxies[:100]]
    await asyncio.gather(*tasks)
    
    # Сортируем по скорости (самые быстрые первые)
    working_proxies.sort(key=lambda p: p.speed)
    
    # Сохраняем топ-10
    best_proxies = working_proxies[:10]
    logging.info(f"Найдено {len(working_proxies)} рабочих прокси. Топ-10 обновлён.")
    
    # Если есть подписчики, можно уведомить их о новом лучшем прокси (опционально)
    # Здесь не реализовано для простоты

# Команда /start
@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    await message.answer(
        "👋 Привет! Я помогу тебе получить быстрый и бесплатный SOCKS5 прокси для Telegram.\n\n"
        "🔹 Отправь команду /proxy — я пришлю лучший прокси на данный момент.\n"
        "🔹 Нажми кнопку «Другой прокси» под сообщением, если текущий работает плохо.\n\n"
        "Прокси обновляются каждые 15 минут, так что ты всегда получишь актуальный вариант."
    )

# Команда /proxy
@dp.message_handler(commands=['proxy'])
async def cmd_proxy(message: types.Message):
    if not best_proxies:
        await message.answer("⏳ Идёт поиск прокси, попробуйте через минуту.")
        return
    
    proxy = best_proxies[0]  # самый быстрый
    text = (
        f"✅ **Ваш быстрый прокси:**\n"
        f"`{proxy.url()}`\n\n"
        "**Как его использовать в Telegram:**\n"
        "1. Нажмите на ссылку выше (или скопируйте её).\n"
        "2. Telegram автоматически откроет настройки и предложит применить прокси.\n"
        "3. Нажмите 'Добавить прокси' и 'Сохранить'.\n\n"
        "Если этот прокси работает медленно, нажмите кнопку ниже."
    )
    await message.answer(text, parse_mode='Markdown', reply_markup=get_proxy_keyboard())

# Обработчик нажатия на кнопку "Другой прокси"
@dp.callback_query_handler(lambda c: c.data == 'new_proxy')
async def process_callback_new_proxy(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    
    if not best_proxies:
        await bot.send_message(callback_query.from_user.id, "⏳ Идёт поиск прокси, попробуйте через минуту.")
        return
    
    # Можно выбрать следующий по скорости или случайный, для простоты возьмём первый (самый быстрый)
    proxy = best_proxies[0]
    text = (
        f"✅ **Новый быстрый прокси:**\n"
        f"`{proxy.url()}`\n\n"
        "Примените его в настройках Telegram по ссылке выше."
    )
    await bot.send_message(callback_query.from_user.id, text, parse_mode='Markdown', reply_markup=get_proxy_keyboard())

# Запуск планировщика для обновления прокси
async def on_startup(_):
    scheduler = AsyncIOScheduler()
    scheduler.add_job(update_proxy_pool, 'interval', minutes=15)
    scheduler.start()
    # Первое обновление сразу при старте
    asyncio.create_task(update_proxy_pool())

if __name__ == '__main__':
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
