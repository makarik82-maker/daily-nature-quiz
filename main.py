import os
import sys
import json
import uuid
import logging
import urllib3
from datetime import datetime, timezone
from pathlib import Path

import requests

# Подавляем предупреждения о непроверенных HTTPS
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ──────────────────────────── Настройки ──────────────────────────

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID", "")
GIGACHAT_CREDENTIALS = os.environ.get("GIGACHAT_CREDENTIALS", "")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
VERIFY_SSL = False

# ──────────────────────── GigaChat Token ─────────────────────────

def get_gigachat_token() -> str | None:
    """Получает OAuth-токен GigaChat."""
    if not GIGACHAT_CREDENTIALS:
        logger.error("GIGACHAT_CREDENTIALS не задан!")
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
        logger.info("✅ Токен GigaChat получен успешно")
        return token
    except Exception as e:
        logger.error("Ошибка получения токена GigaChat: %s", e)
        return None

# ──────────────────────── Определение темы ────────────────────────

def get_today_topic() -> str:
    """Определяем тему по номеру дня в году"""
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
1. Вопрос должен быть основан ТОЛЬКО на реальных научных фактах
2. Не придумывай несуществующие факты или данные
3. Вопрос должен быть интересным, познавательным и не слишком очевидным
4. Ровно 4 варианта ответа (a, b, c, d)
5. Только один правильный ответ
6. Формулируй варианты ответа примерно одинаковой длины

ФОРМАТ ОТВЕТА (строго JSON без дополнительного текста):
{{
    "question": "текст вопроса",
    "options": ["вариант A", "вариант B", "вариант C", "вариант D"],
    "correct_answer": "точный текст правильного ответа из options"
}}

Тема: {topic}

Ответь ТОЛЬКО JSON, без пояснений и дополнительного текста."""

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
        
        # Пробуем распарсить JSON
        try:
            quiz_data = json.loads(answer_text)
            logger.info("✅ Вопрос сгенерирован: %s", quiz_data.get("question", "")[:50])
            return quiz_data
        except json.JSONDecodeError:
            logger.error("Не удалось распарсить JSON от GigaChat: %s", answer_text[:200])
            return None
    
    except Exception as e:
        logger.error("Ошибка генерации вопроса через GigaChat: %s", e)
        return None

# ──────────────────────── Отправка опроса в Telegram ─────────────

def send_quiz_to_telegram(quiz_data: dict) -> bool:
    """Отправляет опрос в режиме викторины в Telegram-канал"""
    
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        logger.error("TELEGRAM_BOT_TOKEN или TELEGRAM_CHANNEL_ID не заданы!")
        return False
    
    # Находим индекс правильного ответа
    try:
        correct_index = quiz_data['options'].index(quiz_data['correct_answer'])
    except ValueError:
        logger.error("Правильный ответ не найден в списке вариантов!")
        return False
    
    url = f"{TELEGRAM_API}/sendPoll"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "question": quiz_data['question'],
        "options": json.dumps(quiz_data['options']),
        "type": "quiz",
        "correct_option_id": correct_index,
        "is_anonymous": False,
        "explanation": f"Правильный ответ: {quiz_data['correct_answer']}",
    }

    try:
        resp = requests.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        logger.info("✅ Опрос успешно отправлен в %s", TELEGRAM_CHANNEL_ID)
        return True
    
    except Exception as e:
        logger.error("❌ Ошибка отправки опроса: %s", e)
        return False

# ──────────────────────────── Main ─────────────────────────────────

def main():
    logger.info("🚀 Запуск Daily Nature Quiz Bot — %s", datetime.now(timezone.utc).isoformat())
    
    # Получаем токен GigaChat
    access_token = get_gigachat_token()
    if not access_token:
        logger.error("Не удалось получить токен GigaChat. Завершение.")
        sys.exit(1)
    
    # Определяем тему дня
    topic = get_today_topic()
    logger.info("📅 Сегодняшняя тема: %s", topic)
    
    # Генерируем вопрос
    quiz = generate_quiz_question(topic, access_token)
    
    if not quiz:
        logger.error("Не удалось сгенерировать вопрос")
        sys.exit(1)
    
    # Отправляем в Telegram
    success = send_quiz_to_telegram(quiz)
    
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
