import asyncio
import logging
import uuid
import aiohttp
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv
import os

# Загрузка переменных окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Инициализация бота
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
GIGACHAT_AUTH_KEY = os.getenv('GIGACHAT_AUTH_KEY')
GIGACHAT_SCOPE = os.getenv('GIGACHAT_SCOPE', 'GIGACHAT_API_PERS')

bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


# FSM States для диалога
class PostGeneration(StatesGroup):
    waiting_for_topic = State()


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
    
    data = {
        'scope': scope
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, data=data, ssl=False) as response:
                if response.status == 200:
                    result = await response.json()
                    return result['access_token']
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка получения токена: {response.status} - {error_text}")
                    raise Exception(f"Не удалось получить токен: {response.status}")
    except Exception as e:
        logger.error(f"Ошибка при запросе токена: {e}")
        raise


async def generate_post_gigachat(prompt: str) -> str:
    """
    Генерация текста поста через GigaChat API
    
    Args:
        prompt: Тема поста от пользователя
    
    Returns:
        Сгенерированный текст поста
    """
    try:
        # Получаем access token
        access_token = await get_gigachat_token(GIGACHAT_AUTH_KEY, GIGACHAT_SCOPE)
        
        # URL для запроса к GigaChat
        url = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Authorization': f'Bearer {access_token}'
        }
        
        # Системный промпт для форматирования поста
        system_prompt = """Ты - профессиональный копирайтер для социальных сетей. 
Создавай посты с:
- Привлекательным заголовком с эмодзи
- Структурированным текстом с абзацами
- Эмодзи для визуального разделения
- Призывом к действию в конце
- Длиной 200-300 слов"""
        
        payload = {
            "model": "GigaChat",
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": f"Напиши пост на тему: {prompt}"
                }
            ],
            "stream": False,
            "repetition_penalty": 1.1,
            "max_tokens": 1024
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, headers=headers, ssl=False) as response:
                if response.status == 200:
                    result = await response.json()
                    generated_text = result['choices'][0]['message']['content']
                    return generated_text
                else:
                    error_text = await response.text()
                    logger.error(f"Ошибка GigaChat API: {response.status} - {error_text}")
                    return "❌ Извините, произошла ошибка при генерации поста. Попробуйте еще раз."
                    
    except Exception as e:
        logger.error(f"Ошибка при генерации поста: {e}")
        return f"❌ Ошибка: {str(e)}"


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    await message.answer(
        "👋 Привет! Я бот для генерации постов с помощью GigaChat.\n\n"
        "Используй команду /post чтобы создать новый пост.\n\n"
        "Команды:\n"
        "/post - Создать пост\n"
        "/help - Помощь"
    )


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    await message.answer(
        "📖 Как использовать бота:\n\n"
        "1️⃣ Отправь команду /post\n"
        "2️⃣ Введи тему для поста\n"
        "3️⃣ Получи готовый пост!\n\n"
        "Бот создаст структурированный пост с эмодзи, "
        "заголовком и призывом к действию."
    )


@dp.message(Command("post"))
async def cmd_post(message: types.Message, state: FSMContext):
    """Обработчик команды /post"""
    await state.set_state(PostGeneration.waiting_for_topic)
    await message.answer(
        "✍️ Напиши тему для поста:\n\n"
        "Например:\n"
        "• Польза медитации\n"
        "• Советы по продуктивности\n"
        "• Здоровое питание"
    )


@dp.message(PostGeneration.waiting_for_topic)
async def process_topic(message: types.Message, state: FSMContext):
    """Обработка темы поста и генерация текста"""
    topic = message.text
    
    # Отправляем сообщение о генерации
    wait_message = await message.answer("⏳ Генерирую пост, подождите...")
    
    # Генерируем пост через GigaChat
    post_text = await generate_post_gigachat(topic)
    
    # Удаляем сообщение ожидания
    await wait_message.delete()
    
    # Отправляем сгенерированный пост
    await message.answer(post_text)
    
    # Предлагаем создать еще один пост
    await message.answer(
        "\n✅ Пост готов!\n\n"
        "Хотите создать еще один? Используйте /post"
    )
    
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
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == '__main__':
    asyncio.run(main())
