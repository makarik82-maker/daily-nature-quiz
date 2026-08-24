import os
import sys
import json
import uuid
import logging
import urllib3
from datetime import datetime, timezone

import requests

# Подавляем предупреждения о непроверенных HTTPS-запросах
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ──────────────────────────── Настройки ───────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")
GIGACHAT_CREDENTIALS = os.environ.get("GIGACHAT_CREDENTIALS", "")

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
        logger.error(" Нет токена для доступа к GigaChat")
        return None

    prompt = f"""Ты — эксперт по {topic}. Создай ОДИН вопрос для викторины в Telegram.

ТРЕБОВАНИЯ:
1. Вопрос должен быть основан ТОЛЬКО на реальных научных фактах.
2. Не придумывай несуществующие факты или данные.
3. Вопрос должен быть интересным, познавательным и не слишком очевидным.
4. Ровно 4 варианта ответа.
5. Только один правильный ответ.
6. Формулируй варианты ответа примерно одинаковой длины.

ФОРМАТ ОТВЕТА (строго JSON без дополнительного текста, без markdown-оберток):
{{
    "question": "Текст вопроса?",
    "options": ["Вариант А", "Вариант Б", "Вариант В", "Вариант Г"],
    "correct_answer": "Точный текст правильного ответа из списка options"
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
        "max_tokens": 500,
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

# ──────────────────────── Отправка опроса в Telegram ─────────────

def send_quiz_to_telegram(quiz_data: dict) -> bool:
    """Отправляет опрос в режиме викторины в Telegram-канал"""
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        logger.error("❌ TELEGRAM_BOT_TOKEN или TELEGRAM_CHANNEL_ID не заданы!")
        return False
    
    try:
        correct_index = quiz_data['options'].index(quiz_data['correct_answer'])
    except ValueError:
        logger.error("❌ Правильный ответ '%s' не найден в списке вариантов: %s", 
                     quiz_data['correct_answer'], quiz_data['options'])
        return False
    
    url = f"{TELEGRAM_API}/sendPoll"
    
    # ВАЖНО: Для каналов Telegram опросы могут быть ТОЛЬКО анонимными!
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "question": quiz_data['question'],
        "options": quiz_data['options'],  
        "type": "quiz",
        "correct_option_id": correct_index,
        "is_anonymous": True,  # ← ОБЯЗАТЕЛЬНО True для каналов
        "explanation": f"✅ Правильный ответ: {quiz_data['correct_answer']}",
        "open_period": 7 * 24 * 60 * 60,  # Опрос открыт 7 дней
    }

    try:
        logger.info("📤 Отправляю опрос в канал...")
        
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
        logger.error("🛑 Завершение работы: не удалось сгенерировать вопрос.")
        sys.exit(1)
    
    # 4. Отправляем в Telegram
    success = send_quiz_to_telegram(quiz)
    
    if success:
        logger.info("🎉 Миссия выполнена успешно!")
        sys.exit(0)
    else:
        logger.error(" Завершение работы с ошибкой отправки.")
        sys.exit(1)


if __name__ == "__main__":
    main()
