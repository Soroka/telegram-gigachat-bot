import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import os
import urllib.parse as urlparse
from telethon import TelegramClient
from newspaper import Article, Config
from background import keep_alive
import openai

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
OPENAI_CLIENT = openai.OpenAI(api_key=os.environ.get("OPENAI"), )

API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
client = TelegramClient('session_name', API_ID, API_HASH)

bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
channel_texts = ""
MIN_TEXT_LEN = 20
MAX_TEXT_LEN = 5000
MAX_EXAMPLES = 5
MIN_EXAMPLES = 3
MAX_POST_LIMIT = 500
CHANNEL = "@AlfaBank"
TOPIC = "спорт"


# FSM States для диалога
class PostGeneration(StatesGroup):
    waiting_for_text = State()
    waiting_for_generation = State()


async def generate_post_openai(prompt: str) -> str:
    """
    Генерация стилизованного поста через GigaChat API
    
    Args:
        prompt: Примеры откуда брать стиль и текст для перефразирования
    
    Returns:
        Сгенерированный текст поста
    """
    try:
        # Системный промпт для форматирования поста
        system_prompt = """Ты — опытный копирайтер. Твоя задача — переписать исходный текст таким образом, чтобы он соответствовал лексике и стилю примеров ниже.\n#### Инструкция по выполнению задания\n1. Проанализируй исходный текст, выделив основную мысль.\n2. Пересмотри структуру текста, адаптируя ее под стилистику примеров.\n3. Изменяй стилистику изложения согласно стилю примеров.\n4. Сохраняй ясность и убедительность оригинальной версии, избегая повторений и лишних слов.\n#### Критерии качества\n- Ясность и точность передачи ключевой информации\n- Соответствие заявленному виду текста и стилю\n- Сохранение привлекательности и воздействия оригинального текста\n- Грамотность и соответствие языковым нормам\n#### Формат ответа\n- Перепиши исходный текст в стилистике примеров.\n- Приведи измененный текст, придерживаясь критериев качества."""
        generated_text = openai_client.responses.create(
            model="gpt-4o",
            instructions=system_prompt,
            input=prompt,
        )
        return generated_text.output_text

    except Exception as e:
        logger.error(f"Ошибка при генерации поста: {e}")
        return f"❌ Ошибка: {str(e)}"


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await message.answer(
        "👋 Привет! Я бот для стилизации новостей в стиле  канала @AlfaBank на тему спорта.\n\n"
        "Команды для стилизации:\n"
        "/rewrite - Стилизовать пост, полученный через ссылку или текст сообщения\n"
        "/help - Помощь")


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    await message.answer(
        "📖 Как использовать бота:\n\n"
        "1️⃣ Отправьте команду /rewrite\n"
        "2️⃣ Введите исходную ссылку на пост или текст сообщения\n"
        "3️⃣ Получите стилизованный пост!\n\n")


async def collect_examples(channel, keyword):
    """Обработка постов из канала для стилизации"""
    examples = ""
    counter = 0
    global channel_texts

    async for post in client.iter_messages(channel, limit=MAX_POST_LIMIT):
        if not post or not post.text:
            continue
        if len(post.text) > MIN_TEXT_LEN and (not keyword or keyword.lower()
                                              in post.text.lower()):
            counter += 1
            examples += f"\nПример {counter}: " + post.raw_text + '\n'
        if counter > MAX_EXAMPLES:
            break
    # Сохранили примеры для промпта
    channel_texts = examples


@dp.message(PostGeneration.waiting_for_generation)
async def post_generation(message, state):
    """Генерация поста полученным текстом"""

    if await state.get_state() != PostGeneration.waiting_for_generation:
        return

    text = message.text
    if urlparse.urlparse(text).scheme:
        try:
            article = Article(message.text)
            article.download()
            article.parse()
            text = article.text
        except:
            await message.answer(
                "❌ Извините, почему-то не распарсился текст, видимо спецсимволы, попробуем другой источник!"
            )
            await state.clear()
            return

    if len(text) > MAX_TEXT_LEN:
        await message.answer(
            "❌ Извините, очень длинный текст, попробуем другой источник!")
        await state.clear()
        return

    # Показываем пользователю распаршенный текст
    await message.answer(
        "***Проверьте пожалуйста, как распарсился исходный текст, иногда он не распаршивается верно***: \n\n"
        + text)

    prompt = channel_texts + "\nИсходный текст: " + text
    # Генерируем пост через GigaChat
    try:
        # Системный промпт для форматирования поста
        system_prompt = """Ты — опытный копирайтер. Твоя задача — переписать исходный текст таким образом, чтобы он соответствовал лексике и стилю примеров ниже.\n#### Инструкция по выполнению задания\n1. Проанализируй исходный текст, выделив основную мысль.\n2. Пересмотри структуру текста, адаптируя ее под стилистику примеров.\n3. Изменяй стилистику изложения согласно стилю примеров.\n4. Сохраняй ясность и убедительность оригинальной версии, избегая повторений и лишних слов.\n#### Критерии качества\n- Ясность и точность передачи ключевой информации\n- Соответствие заявленному виду текста и стилю\n- Сохранение привлекательности и воздействия оригинального текста\n- Грамотность и соответствие языковым нормам\n#### Формат ответа\n- Перепиши исходный текст в стилистике примеров.\n- Приведи измененный текст, придерживаясь критериев качества."""
        generated_text = OPENAI_CLIENT.responses.create(
            model="gpt-4o",
            instructions=system_prompt,
            input=prompt,
        )
        # Отправляем сгенерированный пост
        await message.answer(generated_text.output_text)

    except Exception as e:
        logger.error(f"Ошибка при генерации поста: {e}")
        await message.answer(f"❌ Ошибка: {str(e)}")

    # Предлагаем создать еще один пост
    await message.answer("\n✅ Пост готов!\n\n"
                         "Хотите стилизовать еще один? Используйте /rewrite")

    # Сбрасываем состояние

    await state.clear()


@dp.message(Command("rewrite"))
async def cmd_rewrite_from_text(message: types.Message, state: FSMContext):
    """Обработчик команды /rewrite"""
    await collect_examples(CHANNEL, TOPIC)
    await message.reply(
        "✍️ Дайте пожалуйста оригинальный текст или ссылку для перефразирования:\n\n"
        "Например:\n\n"
        "- Иван Иваныч с Марией Петровной 25 июля решили приготовить кавскзаский пирог\n"
        "или: \n"
        "- https://news.ru/society/gotovlyu-fyddzhyn-po-domashnemu-kefirnoe-testo-i-rublenoe-myaso-sozdayut-kavkazskij-shedevr"
    )
    await state.set_state(PostGeneration.waiting_for_generation)


async def main():
    """Запуск бота"""
    logger.info("Бот запускается...")

    # Проверка наличия необходимых переменных окружения
    if not TELEGRAM_TOKEN:
        logger.error("TELEGRAM_TOKEN не установлен!")
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
