import os
import sys
import json
import uuid
import logging
import urllib3
from datetime import datetime, timezone
from pathlib import Path

import requests

# Подавляем предупреждения о непроверенных HTTPS-запросах
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ──────────────────────────── Настройки ───────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")
GIGACHAT_CREDENTIALS = os.environ.get("GIGACHAT_CREDENTIALS", "")
UNSPLASH_ACCESS_KEY = os.environ.get("UNSPLASH_ACCESS_KEY", "")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
VERIFY_SSL = False

# ──────────────────────── GigaChat Token ──────────────────────────

def get_gigachat_token() -> str | None:
    """Получает OAuth-токен GigaChat."""
    if not GIGACHAT_CREDENTIALS:
        logger.error("❌ GIGACHAT_CREDENTIALS не задан в секретах GitHub!")
        return None
    
    url = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "RqUID": str(uuid.uuid4()),
        "Authorization": f"Basic {GIGACHAT_CREDENTIALS}",
    }
    data = {"scope": "GIGACHAT_API_PERS"}

    try:
        response = requests.post(url, headers=headers, data=data, verify=VERIFY_SSL, timeout=30)
        response.raise_for_status()
        token = response.json().get("access_token")
        logger.info("✅ Токен GigaChat успешно получен")
        return token
    except Exception as e:
        logger.error("❌ Ошибка получения токена GigaChat: %s", e)
        return None

# ──────────────────────── Определение темы ────────────────────────

def get_today_topic() -> str:
    """Определяем тему по номеру дня в году (циклически)"""
    today = datetime.now(timezone.utc)
    day_of_year = today.timetuple().tm_yday
    
    topics = ['природа', 'планеты', 'животные']
    topic_index = day_of_year % 3
    
    return topics[topic_index]

# ──────────────────────── Генерация вопроса ───────────────────────

def generate_quiz_question(topic: str, access_token: str) -> dict | None:
    """Генерирует вопрос для викторины через GigaChat API"""
    
    if not access_token:
        logger.error("Нет токена для доступа к GigaChat")
        return None

    prompt = f"""Ты — эксперт по {topic}. Создай ОДИН вопрос для викторины в Telegram.

ТРЕБОВАНИЯ:
1. Вопрос должен быть основан ТОЛЬКО на реальных научных фактах.
2. Не придумывай несуществующие факты или данные.
3. Вопрос должен быть интересным, познавательным и не слишком очевидным.
4. Ровно 4 варианта ответа.
5. Только один правильный ответ.
6. Формулируй варианты ответа примерно одинаковой длины.
7. В конце добавь строку IMAGE_KEYWORD: [одно ключевое слово на английском для поиска фото]

ФОРМАТ ОТВЕТА (строго JSON без дополнительного текста, без markdown-оберток):
{{
    "question": "Текст вопроса?",
    "options": ["Вариант А", "Вариант Б", "Вариант В", "Вариант Г"],
    "correct_answer": "Точный текст правильного ответа из списка options",
    "image_keyword": "nature"
}}

Тема: {topic}

Ответь ТОЛЬКО JSON."""

    url = "https://api.giga.chat/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {access_token}",
    }
    
    payload = {
        "model": "GigaChat-2",
        "messages": [
            {"role": "system", "content": "Ты — эксперт по научным фактам. Отвечаешь строго в формате JSON."},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": 600,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, verify=VERIFY_SSL, timeout=30)
        response.raise_for_status()
        
        result = response.json()
        answer_text = result["choices"][0]["message"]["content"].strip()
        
        # Очищаем ответ от возможных markdown-оберток
        if answer_text.startswith("```json"):
            answer_text = answer_text[7:-3].strip()
        elif answer_text.startswith("```"):
            answer_text = answer_text[3:-3].strip()
        
        try:
            quiz_data = json.loads(answer_text)
            logger.info("✅ Вопрос сгенерирован: '%s'", quiz_data.get("question", "")[:50])
            return quiz_data
        except json.JSONDecodeError:
            logger.error("❌ Не удалось распарсить JSON от GigaChat. Ответ: %s", answer_text[:200])
            return None
    
    except Exception as e:
        logger.error("❌ Ошибка генерации вопроса через GigaChat: %s", e)
        return None

# ──────────────────────── Поиск фото на Unsplash ──────────────────

def search_photo_on_unsplash(keyword: str, topic: str) -> str | None:
    """Ищет и скачивает фото с Unsplash по ключевому слову"""
    
    if not UNSPLASH_ACCESS_KEY:
        logger.warning("️ UNSPLASH_ACCESS_KEY не задан — пропускаем поиск фото")
        return None
    
    # Используем keyword из вопроса или тему как fallback
    search_query = keyword if keyword else topic
    
    url = "https://api.unsplash.com/photos/random"
    params = {
        "query": search_query,
        "orientation": "landscape",
        "client_id": UNSPLASH_ACCESS_KEY,
    }
    
    try:
        logger.info("🔍 Ищу фото на Unsplash по запросу: %s", search_query)
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        
        data = response.json()
        image_url = data["urls"]["regular"]
        photographer = data["user"]["name"]
        
        # Скачиваем фото
        img_response = requests.get(image_url, timeout=15)
        img_response.raise_for_status()
        
        # Сохраняем во временный файл
        temp_file = Path("temp_quiz_photo.jpg")
        with open(temp_file, "wb") as f:
            f.write(img_response.content)
        
        logger.info("✅ Фото загружено с Unsplash (автор: %s)", photographer)
        return str(temp_file)
    
    except Exception as e:
        logger.warning("⚠️ Ошибка загрузки фото с Unsplash: %s", e)
        return None

# ──────────────────────── Отправка опроса с фото ──────────────────

def send_quiz_with_photo(quiz_data: dict, photo_path: str | None) -> bool:
    """Отправляет опрос с фото или без в Telegram-канал"""
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        logger.error("❌ TELEGRAM_BOT_TOKEN или TELEGRAM_CHANNEL_ID не заданы!")
        return False
    
    try:
        correct_index = quiz_data['options'].index(quiz_data['correct_answer'])
    except ValueError:
        logger.error(" Правильный ответ '%s' не найден в списке вариантов", 
                     quiz_data['correct_answer'])
        return False
    
    # Формируем текст с вопросом для отправки с фото
    question_text = f" <b>{quiz_data['question']}</b>\n\n"
    
    if photo_path and Path(photo_path).exists():
        # Отправляем фото с подписью и опросом
        url = f"{TELEGRAM_API}/sendPhoto"
        
        try:
            with open(photo_path, "rb") as photo_file:
                files = {"photo": photo_file}
                data = {
                    "chat_id": TELEGRAM_CHANNEL_ID,
                    "caption": question_text,
                    "parse_mode": "HTML",
                }
                
                logger.info("📤 Отправляю фото с вопросом...")
                resp = requests.post(url, files=files, data=data, timeout=30)
                
                if resp.status_code != 200:
                    logger.error(" Ошибка отправки фото: %s", resp.text)
                    # Пробуем отправить без фото
                    return send_quiz_without_photo(quiz_data)
        
        except Exception as e:
            logger.error("❌ Ошибка при отправке фото: %s", e)
            return send_quiz_without_photo(quiz_data)
        
        finally:
            # Удаляем временный файл
            try:
                Path(photo_path).unlink()
            except:
                pass
    
    # Отправляем опрос
    return send_quiz_poll(quiz_data, correct_index)

def send_quiz_without_photo(quiz_data: dict) -> bool:
    """Отправляет вопрос текстом + опрос (fallback)"""
    logger.info("📤 Отправляю вопрос текстом (без фото)...")
    
    url = f"{TELEGRAM_API}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": f"🧩 <b>{quiz_data['question']}</b>",
        "parse_mode": "HTML",
    }
    
    try:
        resp = requests.post(url, json=payload, timeout=30)
        if resp.status_code != 200:
            logger.error("❌ Ошибка отправки текста: %s", resp.text)
            return False
        return True
    except Exception as e:
        logger.error("❌ Ошибка: %s", e)
        return False

def send_quiz_poll(quiz_data: dict, correct_index: int) -> bool:
    """Отправляет опрос в режиме викторины"""
    
    url = f"{TELEGRAM_API}/sendPoll"
    
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "question": quiz_data['question'],
        "options": quiz_data['options'],  
        "type": "quiz",
        "correct_option_id": correct_index,
        "is_anonymous": True,  # Обязательно для каналов
        "explanation": f"✅ Правильный ответ: {quiz_data['correct_answer']}",
        "open_period": 7 * 24 * 60 * 60,  # Опрос открыт 7 дней
    }

    try:
        logger.info("📤 Отправляю опрос...")
        resp = requests.post(url, json=payload, timeout=30)
        
        if resp.status_code != 200:
            logger.error("❌ Telegram API вернул ошибку: %s", resp.text)
            return False
        
        logger.info("✅ Опрос успешно отправлен в канал!")
        return True
    
    except Exception as e:
        logger.error("❌ Исключение при отправке опроса: %s", e)
        return False

# ──────────────────────────── Main ─────────────────────────────────

def main():
    logger.info("🚀 Запуск Daily Nature Quiz Bot — %s", datetime.now(timezone.utc).isoformat())
    
    # 1. Получаем токен GigaChat
    access_token = get_gigachat_token()
    if not access_token:
        logger.error("🛑 Завершение работы: не удалось получить токен GigaChat.")
        sys.exit(1)
    
    # 2. Определяем тему дня
    topic = get_today_topic()
    logger.info("📅 Сегодняшняя тема: %s", topic.upper())
    
    # 3. Генерируем вопрос
    quiz = generate_quiz_question(topic, access_token)
    
    if not quiz:
        logger.error(" Завершение работы: не удалось сгенерировать вопрос.")
        sys.exit(1)
    
    # 4. Ищем фото (если есть ключ Unsplash)
    photo_path = None
    image_keyword = quiz_data.get("image_keyword") if isinstance(quiz_data, dict) else None
    photo_path = search_photo_on_unsplash(image_keyword, topic)
    
    # 5. Отправляем в Telegram (с фото или без)
    success = send_quiz_with_photo(quiz, photo_path)
    
    if success:
        logger.info("🎉 Миссия выполнена успешно!")
        sys.exit(0)
    else:
        logger.error(" Завершение работы с ошибкой отправки.")
        sys.exit(1)


if __name__ == "__main__":
    main()
