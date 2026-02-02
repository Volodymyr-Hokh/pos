"""Telegram bot integration for order notifications"""
import httpx
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


async def send_telegram_message(text: str, chat_id: str = None) -> bool:
    """Send a message via Telegram bot.

    Args:
        text: Message text (supports HTML formatting)
        chat_id: Optional chat ID, defaults to TELEGRAM_CHAT_ID from config

    Returns:
        True if message was sent successfully, False otherwise
    """
    token = TELEGRAM_BOT_TOKEN
    target_chat = chat_id or TELEGRAM_CHAT_ID

    if not token or not target_chat:
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": target_chat,
        "text": text,
        "parse_mode": "HTML"
    }

    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, timeout=10)
            return response.status_code == 200
    except Exception as e:
        print(f"Telegram send error: {e}")
        return False


def format_order_message(order: dict) -> str:
    """Format order data into a nice Telegram message.

    Args:
        order: Order dictionary with order details

    Returns:
        Formatted message string with HTML tags
    """
    order_types = {
        'dine_in': 'В залі',
        'takeaway': 'З собою',
        'delivery': 'Доставка'
    }

    items_text = ""
    for item in order.get("items", []):
        items_text += f"  • {item['name']} x{item['qty']} — {item['price'] * item['qty']} грн\n"

    table_info = ""
    if order.get("table_number"):
        table_info = f"\n🪑 <b>Столик:</b> {order['table_number']}"

    customer_info = ""
    if order.get("customer_name"):
        customer_info += f"\n👤 <b>Клієнт:</b> {order['customer_name']}"
    if order.get("customer_phone"):
        customer_info += f"\n📞 <b>Телефон:</b> {order['customer_phone']}"

    discount_info = ""
    if order.get("discount_amount", 0) > 0:
        discount_info = f"\n💸 <b>Знижка:</b> -{order['discount_amount']} грн"
        if order.get("promo_code"):
            discount_info += f" (промокод: {order['promo_code']})"

    notes_info = ""
    if order.get("notes"):
        notes_info = f"\n📝 <b>Примітка:</b> {order['notes']}"

    message = f"""🆕 <b>Нове замовлення!</b>

📋 <b>№ {order.get('order_number', 'N/A')}</b>
🏷️ <b>Тип:</b> {order_types.get(order.get('order_type', ''), order.get('order_type', ''))}{table_info}{customer_info}

<b>Замовлення:</b>
{items_text}{discount_info}
💰 <b>Сума:</b> {order.get('total', 0)} грн{notes_info}
"""

    return message


async def send_order_notification(order: dict) -> bool:
    """Send notification about new order.

    Args:
        order: Order dictionary

    Returns:
        True if notification was sent, False otherwise
    """
    message = format_order_message(order)
    return await send_telegram_message(message)


async def send_status_notification(order_number: str, status: str, chat_id: str = None) -> bool:
    """Send notification about order status change.

    Args:
        order_number: Order number
        status: New status
        chat_id: Optional specific chat to notify

    Returns:
        True if notification was sent, False otherwise
    """
    statuses = {
        'preparing': '👨‍🍳 Готується',
        'ready': '✅ Готове',
        'completed': '🎉 Виконано',
        'cancelled': '❌ Скасовано'
    }

    status_text = statuses.get(status, status)
    message = f"📦 Замовлення <b>{order_number}</b>\n\nСтатус: {status_text}"

    return await send_telegram_message(message, chat_id)
