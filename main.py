import asyncio
import logging
import uuid
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import os
import re
from telethon import TelegramClient
from newspaper import Article, Config
from background import keep_alive

user_agent = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124  Safari/537.36'

config = Config()
config.browser_user_agent = user_agent

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Инициализация бота
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GIGACHAT_AUTH_KEY = os.getenv('GIGACHAT_AUTH_KEY')
GIGACHAT_SCOPE = os.getenv('GIGACHAT_SCOPE', 'GIGACHAT_API_PERS')

API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
client = TelegramClient('session_name', API_ID, API_HASH)

bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
channel_texts = ""
MIN_TEXT_LEN = 20
MAX_TEXT_LEN = 3000
MAX_EXAMPLES = 5
MIN_EXAMPLES = 3
MAX_POST_LIMIT = 500


# FSM States для диалога
class PostGeneration(StatesGroup):
    waiting_for_examples = State()
    waiting_for_link = State()


async def get_gigachat_token(auth_key: str, scope: str) -> str:
    """
    Получение access token для GigaChat API
    
    Args:
        auth_key: Authorization key в формате Base64
        scope: Область доступа (GIGACHAT_API_PERS)
    
    Returns:
        Access token для работы с API
    """
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json',
        'RqUID': str(uuid.uuid4()),
        'Authorization': f'Basic {auth_key}'
    }

    data = {'scope': scope}

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data,
                                    ssl=False) as response:
                if response.status == 200:
                    result = await response.json()
                    return result['access_token']
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Ошибка получения токена: {response.status} - {error_text}"
                    )
                    raise Exception(
                        f"Не удалось получить токен: {response.status}")
    except Exception as e:
        logger.error(f"Ошибка при запросе токена: {e}")
        raise


async def generate_post_gigachat(prompt: str) -> str:
    """
    Генерация стилизованного поста через GigaChat API
    
    Args:
        prompt: Примеры откуда брать стиль и текст для перефразирования
    
    Returns:
        Сгенерированный текст поста
    """
    try:
        # Получаем access token
        access_token = await get_gigachat_token(GIGACHAT_AUTH_KEY,
                                                GIGACHAT_SCOPE)

        # URL для запроса к GigaChat
        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }

        # Системный промпт для форматирования поста
        system_prompt = """Ты — опытный копирайтер. Твоя задача — переписать исходный текст таким образом, чтобы он соответствовал лексике и стилю примеров ниже.\n#### Инструкция по выполнению задания\n1. Проанализируй исходный текст, выделив основную мысль.\n2. Пересмотри структуру текста, адаптируя ее под стилистику примеров.\n3. Изменяй стилистику изложения согласно стилю примеров.\n4. Сохраняй ясность и убедительность оригинальной версии, избегая повторений и лишних слов.\n#### Критерии качества\n- Ясность и точность передачи ключевой информации\n- Соответствие заявленному виду текста и стилю\n- Сохранение привлекательности и воздействия оригинального текста\n- Грамотность и соответствие языковым нормам\n#### Формат ответа\n- Перепиши исходный текст в стилистике примеров.\n- Приведи измененный текст, придерживаясь критериев качества."""

        payload = {
            "model":
            "GigaChat-2-Max",
            "messages": [{
                "role": "system",
                "content": system_prompt
            }, {
                "role": "user",
                "content": f"{prompt}"
            }],
            "stream":
            False,
            "repetition_penalty":
            1.1,
            "max_tokens":
            1024
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url,
                                    json=payload,
                                    headers=headers,
                                    ssl=False) as response:
                if response.status == 200:
                    result = await response.json()
                    generated_text = result['choices'][0]['message']['content']
                    return generated_text
                else:
                    error_text = await response.text()
                    logger.error(
                        f"Ошибка GigaChat API: {response.status} - {error_text}"
                    )
                    return "❌ Извините, произошла ошибка при генерации поста. Попробуйте еще раз."

    except Exception as e:
        logger.error(f"Ошибка при генерации поста: {e}")
        return f"❌ Ошибка: {str(e)}"


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await message.answer(
        "👋 Привет! Я бот для стилизации новостей в стиле выбранного канала.\n\n"
        "Используй команду /post чтобы создать новый пост.\n Введи id канала через @, пример - @AlfaBank, потом ссылку на новость.\n"
        "Команды:\n"
        "/post - Создать пост\n"
        "/help - Помощь")


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    await message.answer(
        "📖 Как использовать бота:\n\n"
        "1️⃣ Отправь команду /post\n"
        "2️⃣ Введи канал для копирования стиля, потом исходную ссылку на пост\n"
        "3️⃣ Получи стилизованный пост!\n\n")


@dp.message(Command("post"))
async def cmd_post(message: types.Message, state: FSMContext):
    """Обработчик команды /post"""
    await state.set_state(PostGeneration.waiting_for_examples)
    await message.reply(
        "✍️ Напиши id канала через @, можно с ключевым словом через хештег:\n\n"
        " Рекомендуемые:\n"
        "• @AlfaBank\n"
        "• @alfa_investments\n"
        "• @alfa_investments#чтокупить\n"
        "• @aaaredmarketing\n"
        "Выбор непредсказуемого канала даст непредсказуемый результат!")


@dp.message(PostGeneration.waiting_for_examples)
async def process_channel(message: types.Message, state: FSMContext):
    """Обработка постов из канала для стилизации"""
    examples = ""
    counter = 0
    global channel_texts
    keyword = None

    # Проверяем, что название канала адекватное
    if not re.match(
            "^[@][A-z0-9]*([#][A-zабвгдежзийклмнопрстуфзцчшщэюя_0-9]*)?",
            message.text):
        await message.answer(
            "❌ Извините, странное название канала или ключевые слова, попробуем ещё!"
        )
        await state.clear()
        return

    # Отрезаем ключевое слово или тег
    if '#' in message.text:
        channel, keyword = message.text.split('#')
    else:
        channel = message.text
    try:
        async for post in client.iter_messages(channel, limit=MAX_POST_LIMIT):
            if not post or not post.text:
                continue
            if len(post.text) > MIN_TEXT_LEN and (
                    not keyword or keyword.lower() in post.text.lower()):
                counter += 1
                examples += f"\nПример {counter}: " + post.raw_text + '\n'
            if counter > MAX_EXAMPLES:
                break
    # Обрабатываем ошибку, если нет такого канала
    except ValueError:
        pass
    # Собралось недостаточно постов для примеров в промпте
    if counter < MIN_EXAMPLES:
        await message.answer(
            "❌ Извините, не читается канал или мало постов с такими ключевыми словами, попробуем другой источник!"
        )
        await state.clear()
        return
    # Сохранили примеры для промпта
    channel_texts = examples
    await message.reply(
        "✍️ Дай ссылку на оригинальный текст:\n\n"
        "Например:\n"
        " • https://news.ru/society/gotovlyu-fyddzhyn-po-domashnemu-kefirnoe-testo-i-rublenoe-myaso-sozdayut-kavkazskij-shedevr\n"
    )
    await state.set_state(PostGeneration.waiting_for_link)


@dp.message(PostGeneration.waiting_for_link)
async def process_article(message: types.Message, state: FSMContext):
    """Обработка поста и генерация нового текста по примерам"""
    if await state.get_state() != PostGeneration.waiting_for_link:
        return
    try:
        article = Article(message.text)
        article.download()
        article.parse()
    except:
        await message.answer(
            "❌ Извините, почему-то не распарсился текст, видимо спецсимволы, попробуем другой источник!")
        await state.clear()
        return

    # Проверили, что текст минимально адекватен
    if len(article.text) < MIN_TEXT_LEN:
        await message.answer(
            "❌ Извините, не распарсился текст, попробуем другой источник!")
        await state.clear()
        return

    if len(article.text) > MAX_TEXT_LEN:
        await message.answer(
            "❌ Извините, очень длинный текст, попробуем другой источник!")
        await state.clear()
        return

    # Показываем пользователю распаршенный текст
    wait_message = await message.answer(
        "Проверьте пожалуйста, как распарсился исходный текст, иногда он не распаршивается верно: \n\n"
        + article.text)

    prompt = channel_texts + "\nИсходный текст: " + article.text
    # Генерируем пост через GigaChat
    post_text = await generate_post_gigachat(prompt)

    # Отправляем сгенерированный пост
    await message.answer(post_text)

    # Предлагаем создать еще один пост
    await message.answer("\n✅ Пост готов!\n\n"
                         "Хотите создать еще один? Используйте /post")

    # Сбрасываем состояние
    await state.clear()


async def main():
    """Запуск бота"""
    logger.info("Бот запускается...")

    # Проверка наличия необходимых переменных окружения
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не установлен!")
        return

    if not GIGACHAT_AUTH_KEY:
        logger.error("GIGACHAT_AUTH_KEY не установлен!")
        return

    try:
        # Запуск polling
        await client.start()
        keep_alive()
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
