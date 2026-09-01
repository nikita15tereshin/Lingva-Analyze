import os
from openai import OpenAI

API_KEY = os.getenv("LLM_API_KEY")

client = OpenAI(
    base_url='https://api.tokenrouter.com/v1',
    api_key=API_KEY if API_KEY else "sk-yqac6Kh00DXYuuM2yCg5CxvbJyU3lFW277WQfmnA2jFO8rV3",
)

def analyze_semantic_context_stream(word: str, sentence: str, expected_region: str):
    """
    Генератор, который отправляет запрос в LLM и возвращает ответ чанками (потоком).
    """
    prompt = f"""
    Ты эксперт по региональным вариантам немецкого языка (Германия, Австрия, Швейцария).
    
    Проанализируй использование слова '{word}' в следующем предложении:
    "{sentence}"
    
    Задачи:
    1. Подтверди, характерно ли использование этого слова в данном контексте для региона '{expected_region}'.
    2. Укажи стандартный немецкий эквивалент (Bundesdeutsches Hochdeutsch).
    3. Если здесь наблюдается семантический сдвиг, подробно объясни его.
    
    Ответь кратко, академическим стилем, подходящим для лингвистической диссертации.
    """
    
    messages = [
        {"role": "system", "content": "You are an intelligent linguistic assistant, please reply concisely."},
        {"role": "user", "content": prompt}
    ]
    
    print(f"🚀 [LLM Stream] Запрос для слова: '{word}' отправлен...")
    
    try:
        # Включаем stream=True и убираем таймаут, чтобы ждать столько, сколько нужно
        response = client.chat.completions.create(
            model="moonshotai/kimi-k3-free",
            messages=messages,
            temperature=0.3,
            stream=True 
        )
        
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
                
    except Exception as e:
        print(f"❌ [LLM Stream] Ошибка: {str(e)}")
        yield f"\n\n⚠️ Ошибка при обращении к нейросети: {str(e)}"