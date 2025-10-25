
# ArzonUching — Telegram бот дешёвых авиабилетов (UZS) + Payme (UZ) сервисный сбор

## Возможности
- ТОП‑3 самых дешёвых вариантов бесплатно (UZS)
- После оплаты сервисного сбора (50 000 сум, Payme) — показать ещё 7+ вариантов, фильтры и ссылки на покупку (Aviasales/Travelpayouts)
- Покупка билета происходит на стороне партнёра (Aviasales). Вам начисляется 1–3% партнёрка + сервисный сбор 50 000 сум

## Технологии
- Python 3.11, Aiogram 3, FastAPI (webhook), Aiohttp
- Render (gunicorn + uvicorn)
- Payme (UZ) интеграция через библиотеку `paytechuz` (stub настроек, потребуется мерчант ID/секрет)

## Переменные окружения (.env)
```env
BOT_TOKEN=123456:ABCDEF...            # BotFather
WEBHOOK_SECRET=change_me              # Любая строка для защиты webhook url
BASE_URL=https://YOUR-RENDER-APP.onrender.com

# Travelpayouts / Aviasales
TRAVELPAYOUTS_TOKEN=tp_api_token_here
AFFILIATE_MARKER=your_partner_marker

# Payme (UZ) — мерчант-данные (примерные названия, уточните у Payme)
PAYME_MERCHANT_ID=YOUR_MERCHANT_ID
PAYME_SECRET_KEY=YOUR_SECRET
SERVICE_FEE_AMOUNT=50000              # 50 000 сум
CURRENCY=UZS
```

## Локальный запуск (polling)
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```
В отдельном терминале можно запустить polling без вебхуков:
```bash
python app/polling.py
```

## Деплой на Render (webhook)
1. Создайте Web Service на Render, Python 3.11
2. Добавьте переменные окружения из `.env`
3. Команда запуска (Render): прописана в `render.yaml`/`Procfile`
4. После старта, установите webhook:
   ```
   https://api.telegram.org/bot<YOUR_BOT_TOKEN>/setWebhook?url=<BASE_URL>/bot/<WEBHOOK_SECRET>
   ```

## Payme (UZ) примечания
- Процесс оплаты реализован через `paytechuz` (единый провайдер для Payme/Click). Для продакшн нужны реальные merchant_id/secret и настройка уведомлений.
- Обработка уведомлений Payme доступна по адресу: `POST /payme/webhook`
- Документация Payme (UZ): developer.help.paycom.uz

## Лицензия
MIT
