
from __future__ import annotations
import os
from typing import Optional
from paytechuz import PayTech
from paytechuz.providers import PaymeProvider

MERCHANT_ID = os.getenv("PAYME_MERCHANT_ID", "")
SECRET_KEY  = os.getenv("PAYME_SECRET_KEY", "")
SERVICE_FEE_AMOUNT = int(os.getenv("SERVICE_FEE_AMOUNT", "50000"))
CURRENCY = os.getenv("CURRENCY", "UZS")

# Инициализация Payme провайдера (через PayTechUZ)
payme = PayTech(
    provider=PaymeProvider(
        merchant_id=MERCHANT_ID,
        secret_key=SECRET_KEY,
        test_mode=True if os.getenv("PAYME_TEST","1") == "1" else False,
    )
)

def create_service_fee_invoice(user_id: int, description: str = "ArzonUching: расширенный поиск") -> dict:
    """Создаёт инвойс на 50 000 сум и возвращает ссылку для оплаты.
    На проде добавьте ваши order_id/transaction_id и callback_url.
    """
    order_id = f"svc_{user_id}"
    # В некоторых интеграциях Payme требует сумму в тийинах/центах. Здесь оставляем в сумах как пример.
    link = payme.generate_payment_link(amount=SERVICE_FEE_AMOUNT, order_id=order_id, description=description)
    return {
        "order_id": order_id,
        "amount": SERVICE_FEE_AMOUNT,
        "currency": CURRENCY,
        "pay_link": link,
    }
