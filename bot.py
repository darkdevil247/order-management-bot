import os
import requests
import time
import json
from datetime import datetime
import logging
import traceback

# ==================== SAFE CONFIGURATION ====================
print("🛒 Starting FreshMart Grocery Delivery Bot...")

# Get credentials from environment (SAFE)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
SHEET_URL = os.environ.get('SHEET_URL')
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID')

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Check if environment variables are set
if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_TOKEN environment variable not set!")
if not SHEET_URL:
    logger.warning("⚠️ SHEET_URL not set, Google Sheets disabled")

# Google Sheets setup (with error handling)
sheet = None
try:
    if SHEET_URL:
        import gspread
        from google.oauth2.service_account import Credentials
        
        # Get service account from environment or use None
        service_account_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
        if service_account_json:
            import json
            creds_dict = json.loads(service_account_json)
            scope = ['https://www.googleapis.com/auth/spreadsheets']
            creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
            client = gspread.authorize(creds)
            sheet = client.open_by_url(SHEET_URL).sheet1
            logger.info("✅ Google Sheets connected successfully!")
        else:
            logger.warning("⚠️ Google Sheets credentials not provided")
except Exception as e:
    logger.error(f"❌ Google Sheets setup failed: {e}")
    sheet = None

# Grocery database (SAFE - no secrets)
grocery_categories = {
    '🥦 Fresh Produce': {
        '🍎 Apples': {'price': 3.99, 'unit': 'kg'},
        '🍌 Bananas': {'price': 1.99, 'unit': 'kg'},
        '🥕 Carrots': {'price': 2.49, 'unit': 'kg'},
        '🥬 Spinach': {'price': 4.99, 'unit': 'bunch'},
        '🍅 Tomatoes': {'price': 3.49, 'unit': 'kg'}
    },
    '🥩 Meat & Poultry': {
        '🍗 Chicken Breast': {'price': 12.99, 'unit': 'kg'},
        '🥩 Beef Steak': {'price': 24.99, 'unit': 'kg'},
        '🐟 Salmon Fillet': {'price': 18.99, 'unit': 'kg'},
        '🥓 Bacon': {'price': 8.99, 'unit': 'pack'}
    },
    '🥛 Dairy & Eggs': {
        '🥛 Milk': {'price': 2.99, 'unit': 'liter'},
        '🧀 Cheese': {'price': 6.99, 'unit': 'block'},
        '🍳 Eggs': {'price': 4.99, 'unit': 'dozen'},
        '🧈 Butter': {'price': 3.99, 'unit': 'block'}
    }
}

user_carts = {}
user_sessions = {}

# ==================== ENHANCED MESSAGE HANDLING ====================
def send_message(chat_id, text, keyboard=None, inline_keyboard=None, parse_mode='HTML'):
    """Enhanced message sending with comprehensive error handling"""
    if not TELEGRAM_TOKEN:
        logger.error("❌ Cannot send message: TELEGRAM_TOKEN not set")
        return False
        
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            'chat_id': chat_id, 
            'text': text,
            'parse_mode': parse_mode
        }

        if keyboard:
            payload['reply_markup'] = json.dumps({
                'keyboard': keyboard,
                'resize_keyboard': True,
                'one_time_keyboard': False
            })
        elif inline_keyboard:
            payload['reply_markup'] = json.dumps({
                'inline_keyboard': inline_keyboard
            })

        response = requests.post(url, json=payload, timeout=10)
        
        if response.status_code != 200:
            logger.error(f"Telegram API error: {response.status_code} - {response.text}")
            return False
            
        logger.info(f"✅ Message sent to {chat_id}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Error sending message: {e}")
        return False

# ==================== ADMIN NOTIFICATIONS ====================
def notify_admin(order_summary, order_type="🆕 NEW ORDER"):
    """Send immediate notification to store owner/administrator"""
    if not ADMIN_CHAT_ID:
        logger.warning("⚠️ ADMIN_CHAT_ID not set, skipping admin notification")
        return False
        
    try:
        admin_message = f"""{order_type}

{order_summary}

⏰ Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
📊 Status: Awaiting Processing"""
        
        send_message(ADMIN_CHAT_ID, admin_message)
        logger.info("✅ Admin notified successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to notify admin: {e}")
        return False

# ==================== ENHANCED ORDER SUMMARY ====================
def create_enhanced_order_summary(customer_name, phone, address, cart, special_instructions=""):
    """Create a beautifully formatted order summary"""
    
    subtotal = sum(details['price'] * details['quantity'] for details in cart.values())
    delivery_fee = 0 if subtotal >= 50 else 5
    total = subtotal + delivery_fee
    
    items_text = ""
    for item_name, details in cart.items():
        item_total = details['price'] * details['quantity']
        items_text += f"• {item_name}\n"
        items_text += f"  ${details['price']}/{details['unit']} × {details['quantity']} = ${item_total:.2f}\n"
    
    summary = f"""🛒 ORDER SUMMARY

👤 Customer Details:
Name: {customer_name}
Phone: {phone}
Address: {address}

📦 Order Items:
{items_text}
💵 Pricing:
Subtotal: ${subtotal:.2f}
Delivery Fee: ${delivery_fee:.2f}
{'🎉 FREE DELIVERY (Order > $50)' if delivery_fee == 0 else f'🎯 Add ${50 - subtotal:.2f} more for FREE delivery!'}
💰 TOTAL: ${total:.2f}

{f'📝 Special Instructions: {special_instructions}' if special_instructions else '📝 Special Instructions: None'}
    
⏰ Expected Delivery: Within 2 hours
🕐 Order Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}"""
    
    return summary, total

# ==================== PAYMENT PROCESSING ====================
def handle_payment_selection(chat_id):
    """Let customer choose payment method"""
    payment_text = """💳 Payment Method

How would you like to pay for your order?

💰 Cash on Delivery - Pay when you receive your groceries
💳 Online Payment - Pay now securely (Coming Soon!)

Select your preferred payment method:"""
    
    keyboard = [
        [{'text': '💰 Cash on Delivery'}, {'text': '💳 Online Payment (Soon)'}],
        [{'text': '🔙 Back to Checkout'}, {'text': '🛒 View Cart'}]
    ]
    
    send_message(chat_id, payment_text, keyboard=keyboard)
    user_sessions[chat_id] = {'step': 'awaiting_payment_method'}

def process_cash_on_delivery(chat_id, customer_name, phone, address, cart, special_instructions):
    """Process cash on delivery order"""
    try:
        order_summary, total = create_enhanced_order_summary(
            customer_name, phone, address, cart, special_instructions
        )
        
        # Save to Google Sheets if available
        success = True
        if sheet:
            success = save_order_to_sheet(
                chat_id, customer_name, phone, address, cart, 
                special_instructions, "Cash on Delivery"
            )
        
        if success:
            # Notify admin
            admin_summary = f"""💵 CASH ON DELIVERY ORDER

{order_summary}

💰 Payment Method: Cash on Delivery
💸 Amount to Collect: ${total:.2f}"""
            
            notify_admin(admin_summary, "💵 NEW COD ORDER")
            
            # Send customer confirmation
            confirmation = f"""✅ Order Confirmed! 🎉

Thank you {customer_name}!

{order_summary}

💵 Payment: Cash on Delivery
💸 Please have ${total:.2f} ready for our delivery driver.

We're preparing your fresh groceries! 🥦"""
            
            send_message(chat_id, confirmation)
            
            # Clear cart and session
            user_carts[chat_id] = {}
            user_sessions[chat_id] = {'step': 'main_menu'}
            
            logger.info(f"✅ COD order processed successfully for {customer_name}")
            return True
            
    except Exception as e:
        logger.error(f"❌ Error processing COD order: {e}")
        send_message(chat_id, "❌ Sorry, there was an error processing your order. Please try again.")
        return False

# ==================== ENHANCED SHEET SAVING ====================
def save_order_to_sheet(chat_id, customer_name, phone, address, cart, special_instructions="", payment_method="Cash on Delivery"):
    """Enhanced order saving with payment method"""
    if not sheet:
        logger.warning("Google Sheets not available, order not saved")
        return True  # Return True to continue order process

    try:
        subtotal = sum(details['price'] * details['quantity'] for details in cart.values())
        delivery_fee = 0 if subtotal >= 50 else 5
        total = subtotal + delivery_fee

        # Format items
        items_list = []
        quantities_list = []
        for item_name, details in cart.items():
            items_list.append(item_name)
            quantities_list.append(f"{details['quantity']} {details['unit']}")

        items_lines = ["\n".join(items_list[i:i+3]) for i in range(0, len(items_list), 3)]
        quantities_lines = ["\n".join(quantities_list[i:i+3]) for i in range(0, len(quantities_list), 3)]

        order_data = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            str(chat_id),
            customer_name,
            phone,
            address,
            "\n".join(items_lines),
            "\n".join(quantities_lines),
            f"${subtotal:.2f}",
            f"${delivery_fee:.2f}",
            f"${total:.2f}",
            "Pending",
            special_instructions,
            payment_method,
            "Telegram Bot"
        ]

        sheet.append_row(order_data)
        logger.info(f"✅ Order saved to sheet: {customer_name} - ${total:.2f}")
        return True

    except Exception as e:
        logger.error(f"❌ Error saving order to sheet: {e}")
        return False  # Order continues even if sheet save fails

# ==================== BOT HANDLERS ====================
def handle_start(chat_id):
    welcome = """🛒 Welcome to FreshMart Grocery Delivery! 🛒

🌟 <b>Fresh Groceries Delivered to Your Doorstep!</b> 🌟

🚚 <b>Free Delivery</b> on orders over $50
⏰ <b>Delivery Hours:</b> 7 AM - 10 PM Daily
💰 <b>Payment:</b> Cash on Delivery Available

<b>What would you like to do?</b>"""

    keyboard = [
        [{'text': '🛍️ Shop Groceries'}, {'text': '🛒 My Cart'}],
        [{'text': '💰 Payment Methods'}, {'text': '📞 Contact Store'}],
        [{'text': 'ℹ️ Store Info'}]
    ]

    send_message(chat_id, welcome, keyboard=keyboard)
    user_sessions[chat_id] = {'step': 'main_menu'}

def show_categories(chat_id):
    categories = """📋 Grocery Categories

Choose a category to start shopping:"""

    keyboard = [
        [{'text': '🥦 Fresh Produce'}, {'text': '🥩 Meat & Poultry'}],
        [{'text': '🥛 Dairy & Eggs'}, {'text': '🍞 Bakery'}],
        [{'text': '🧴 Household'}, {'text': '🔙 Main Menu'}]
    ]

    send_message(chat_id, categories, keyboard=keyboard)

def show_category_items(chat_id, category):
    if category not in grocery_categories:
        send_message(chat_id, "Category not found. Please choose from the menu.")
        return

    items_text = f"{category}\n\nSelect an item to add to cart:"
    items = grocery_categories[category]
    inline_keyboard = []

    for item_name, details in items.items():
        button_text = f"{item_name} - ${details['price']}/{details['unit']}"
        inline_keyboard.append([{
            'text': button_text,
            'callback_data': f"add_{item_name}"
        }])

    inline_keyboard.append([
        {'text': '🔙 Back to Categories', 'callback_data': 'back_categories'},
        {'text': '🛒 View Cart', 'callback_data': 'view_cart'}
    ])

    send_message(chat_id, items_text, inline_keyboard=inline_keyboard)
    user_sessions[chat_id] = {'step': 'browsing_category', 'current_category': category}

def handle_add_to_cart(chat_id, item_name):
    item_details = None
    for category, items in grocery_categories.items():
        if item_name in items:
            item_details = items[item_name]
            break

    if not item_details:
        send_message(chat_id, "Item not found. Please select from the menu.")
        return

    if chat_id not in user_carts:
        user_carts[chat_id] = {}

    if item_name in user_carts[chat_id]:
        user_carts[chat_id][item_name]['quantity'] += 1
    else:
        user_carts[chat_id][item_name] = {
            'price': item_details['price'],
            'unit': item_details['unit'],
            'quantity': 1
        }

    response = f"✅ Added to Cart!\n\n{item_name}\n${item_details['price']}/{item_details['unit']}\n\nWhat would you like to do next?"

    keyboard = [
        [{'text': '🛒 View Cart'}, {'text': '📋 Continue Shopping'}],
        [{'text': '🚚 Checkout'}, {'text': '🔙 Main Menu'}]
    ]

    send_message(chat_id, response, keyboard=keyboard)

def show_cart(chat_id):
    if chat_id not in user_carts or not user_carts[chat_id]:
        cart_text = "🛒 Your cart is empty!\n\nStart shopping to add some delicious groceries! 🥦"
        keyboard = [
            [{'text': '🛍️ Start Shopping'}, {'text': '🔙 Main Menu'}]
        ]
        send_message(chat_id, cart_text, keyboard=keyboard)
        return

    cart = user_carts[chat_id]
    total = 0
    cart_text = "🛒 Your Shopping Cart\n\n"

    for item_name, details in cart.items():
        item_total = details['price'] * details['quantity']
        total += item_total
        cart_text += f"• {item_name}\n"
        cart_text += f"  ${details['price']}/{details['unit']} × {details['quantity']} = ${item_total:.2f}\n\n"

    cart_text += f"💵 Subtotal: ${total:.2f}"
    delivery_fee = 0 if total >= 50 else 5
    final_total = total + delivery_fee

    cart_text += f"\n🚚 Delivery: ${delivery_fee:.2f}"
    cart_text += f"\n💰 Total: ${final_total:.2f}"

    if total < 50:
        cart_text += f"\n\n🎯 Add ${50 - total:.2f} more for FREE delivery!"
    else:
        cart_text += f"\n\n✅ You qualify for FREE delivery!"

    keyboard = [
        [{'text': '➕ Add More Items'}, {'text': '🗑️ Clear Cart'}],
        [{'text': '🚚 Checkout Now'}, {'text': '📋 Continue Shopping'}],
        [{'text': '🔙 Main Menu'}]
    ]

    send_message(chat_id, cart_text, keyboard=keyboard)

def handle_checkout(chat_id):
    if chat_id not in user_carts or not user_carts[chat_id]:
        send_message(chat_id, "Your cart is empty! Please add items first.")
        show_categories(chat_id)
        return

    send_message(chat_id, "🚚 Let's get your order delivered!\n\nPlease provide your full name:")
    user_sessions[chat_id] = {'step': 'awaiting_name'}

def handle_callback_query(chat_id, callback_data):
    if callback_data.startswith('add_'):
        item_name = callback_data[4:]
        handle_add_to_cart(chat_id, item_name)
    elif callback_data == 'back_categories':
        show_categories(chat_id)
    elif callback_data == 'view_cart':
        show_cart(chat_id)

def get_updates(offset=None):
    if not TELEGRAM_TOKEN:
        logger.error("Cannot get updates: TELEGRAM_TOKEN not set")
        return None
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {'timeout': 30}
    if offset:
        params['offset'] = offset
        
    try:
        response = requests.get(url, params=params, timeout=35)
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Telegram API error: {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"get_updates error: {e}")
        return None

def handle_message(chat_id, text):
    try:
        if text == '/start':
            handle_start(chat_id)
        elif text == '🛍️ Shop Groceries':
            show_categories(chat_id)
        elif text == '🛒 My Cart':
            show_cart(chat_id)
        elif text == '🔙 Main Menu':
            handle_start(chat_id)
        elif text == '📋 Continue Shopping':
            show_categories(chat_id)
        elif text == '➕ Add More Items':
            show_categories(chat_id)
        elif text == '🗑️ Clear Cart':
            if chat_id in user_carts:
                user_carts[chat_id] = {}
            send_message(chat_id, "🛒 Your cart has been cleared!")
            show_categories(chat_id)
        elif text == '🚚 Checkout Now' or text == '🚚 Checkout':
            handle_checkout(chat_id)
        elif text in grocery_categories:
            show_category_items(chat_id, text)
        elif text == '💰 Cash on Delivery':
            if user_sessions.get(chat_id, {}).get('step') == 'awaiting_payment_method':
                send_message(chat_id, "🚚 Great! You've chosen Cash on Delivery.\n\nPlease provide your full name:")
                user_sessions[chat_id] = {'step': 'awaiting_name', 'payment_method': 'Cash on Delivery'}
        elif text == '💳 Online Payment (Soon)':
            send_message(chat_id, "⚡ Online payments coming soon!\n\nFor now, please use Cash on Delivery for your orders.")
            handle_payment_selection(chat_id)
        elif text == '💰 Payment Methods':
            payment_info = """💳 <b>Payment Options</b>

Currently Available:
💰 <b>Cash on Delivery</b> - Pay when you receive your groceries

Coming Soon:
💳 <b>Credit/Debit Cards</b>
📱 <b>Mobile Payments</b>
🎫 <b>Digital Wallets</b>

We're working to bring you more payment options soon!"""
            send_message(chat_id, payment_info)
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_name':
            customer_name = text
            user_sessions[chat_id] = {'step': 'awaiting_phone', 'customer_name': customer_name}
            send_message(chat_id, f"👋 Thanks {customer_name}! Now please provide your phone number for delivery updates:")
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_phone':
            user_phone = text
            customer_name = user_sessions[chat_id]['customer_name']
            user_sessions[chat_id] = {'step': 'awaiting_address', 'customer_name': customer_name, 'phone': user_phone}
            send_message(chat_id, "📦 Great! Now please provide your delivery address:")
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_address':
            user_address = text
            customer_name = user_sessions[chat_id]['customer_name']
            user_phone = user_sessions[chat_id]['phone']
            user_sessions[chat_id] = {'step': 'awaiting_instructions', 'customer_name': customer_name, 'phone': user_phone, 'address': user_address}
            send_message(chat_id, "📝 Any special delivery instructions?\n\n(e.g., 'Leave at door', 'Call before delivery', or type 'None'):")
        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_instructions':
            special_instructions = text if text.lower() != 'none' else ""
            session_data = user_sessions[chat_id]
            
            if session_data.get('payment_method') == 'Cash on Delivery':
                process_cash_on_delivery(
                    chat_id,
                    session_data['customer_name'],
                    session_data['phone'],
                    session_data['address'],
                    user_carts[chat_id],
                    special_instructions
                )
        else:
            handle_start(chat_id)

    except Exception as e:
        logger.error(f"❌ Error handling message: {e}")
        send_message(chat_id, "❌ Sorry, an error occurred. Please try again.")
        handle_start(chat_id)

def main():
    # Check environment variables first
    if not TELEGRAM_TOKEN:
        logger.error("❌ CRITICAL: TELEGRAM_TOKEN environment variable not set!")
        logger.error("💡 Set it in Railway → Variables tab")
        logger.error("💤 Bot will sleep instead of crashing...")
        while True:
            time.sleep(60)
        return

    logger.info("🛒 FreshMart Grocery Bot Started Successfully!")
    logger.info("📊 Features: Enhanced Logging, Admin Notifications, Payment Processing")
    logger.info("💰 Payment: Cash on Delivery Implemented")
    logger.info("📱 Ready to take orders with professional error handling!")

    last_update_id = None

    while True:
        try:
            updates = get_updates(last_update_id)

            if updates and 'result' in updates:
                for update in updates['result']:
                    last_update_id = update['update_id'] + 1

                    if 'message' in update and 'text' in update['message']:
                        chat_id = update['message']['chat']['id']
                        text = update['message']['text']
                        logger.info(f"📩 Message from {chat_id}: {text}")
                        handle_message(chat_id, text)

                    elif 'callback_query' in update:
                        callback = update['callback_query']
                        chat_id = callback['message']['chat']['id']
                        callback_data = callback['data']
                        logger.info(f"🔘 Callback from {chat_id}: {callback_data}")
                        handle_callback_query(chat_id, callback_data)

            time.sleep(1)
            
        except Exception as e:
            logger.error(f"❌ Main loop error: {e}")
            logger.error(traceback.format_exc())
            time.sleep(5)

if __name__ == '__main__':
    main()
