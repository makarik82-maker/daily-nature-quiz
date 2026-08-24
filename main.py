import os
import json
from datetime import datetime
from gigachat import GigaChat
import telebot

# Получаем ключи ТОЛЬКО из переменных окружения (GitHub Secrets)
GIGACHAT_CREDENTIALS = os.environ['GIGACHAT_CREDENTIALS']
TELEGRAM_BOT_TOKEN = os.environ['TELEGRAM_BOT_TOKEN']
TELEGRAM_CHANNEL_ID = os.environ['TELEGRAM_CHANNEL_ID']

def get_today_topic():
    """Определяем тему по номеру дня в году"""
    today = datetime.now()
    day_of_year = today.timetuple().tm_yday
    
    topics = ['природа', 'планеты', 'животные']
    topic_index = day_of_year % 3
    
    return topics[topic_index]

def generate_quiz_question(topic):
    """Генерируем вопрос для квиза через Гигачат"""
    
    prompt = f"""Ты - эксперт по {topic}. Создай один вопрос для викторины.

ТРЕБОВАНИЯ:
1. Вопрос должен быть основан ТОЛЬКО на реальных фактах
2. Не придумывай несуществующие факты
3. Вопрос должен быть интересным и познавательным
4. Ровно 4 варианта ответа
5. Только один правильный ответ

ФОРМАТ ОТВЕТА (строго JSON):
{{
    "question": "текст вопроса",
    "options": ["вариант 1", "вариант 2", "вариант 3", "вариант 4"],
    "correct_answer": "точный текст правильного ответа из options"
}}

Тема: {topic}

Ответь ТОЛЬКО JSON, без дополнительного текста."""

    giga = GigaChat(credentials=GIGACHAT_CREDENTIALS, verify_ssl=False)
    response = giga.chat(prompt)
    answer_text = response.choices[0].message.content
    
    try:
        quiz_data = json.loads(answer_text)
        return quiz_data
    except json.JSONDecodeError:
        print("Ошибка парсинга JSON от Гигачата:")
        print(answer_text)
        return None

# Тестовый запуск (для отладки на GitHub Actions)
if __name__ == "__main__":
    topic = get_today_topic()
    print(f"Сегодня тема: {topic}")
    quiz = generate_quiz_question(topic)
    if quiz:
        print(json.dumps(quiz, ensure_ascii=False, indent=2))
    else:
        print("Не удалось сгенерировать вопрос")
