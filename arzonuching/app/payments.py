
# arzonuching/app/payments.py
import os

# Сумма сервисного сбора (оставь свою, если нужна другая)
SERVICE_FEE_AMOUNT = 5000

# Интеграция Payme временно отключена (на Render без paytechuz)
PAYME_ENABLED = False

def create_service_fee_invoice(order_id: str, amount: int = SERVICE_FEE_AMOUNT) -> dict:
    """
    Заглушка: возвращает, что Payme выключен.
    В будущем, когда вернём paytechuz, заменим эту функцию реальной.
    """
    return {
        "status": "disabled",
        "message": "Payme integration is disabled on this server",
        "pay_url": ""
    }
