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
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Check if environment variables are set
if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_TOKEN environment variable not set!")
    exit(1)

logger.info(f"✅ TELEGRAM_TOKEN: {'*' * 10}{TELEGRAM_TOKEN[-4:]}" if TELEGRAM_TOKEN else "❌ TELEGRAM_TOKEN not set")
logger.info(f"✅ ADMIN_CHAT_ID: {ADMIN_CHAT_ID}" if ADMIN_CHAT_ID else "⚠️ ADMIN_CHAT_ID not set")
logger.info(f"✅ SHEET_URL: {'Set' if SHEET_URL else 'Not set'}")

# Google Sheets setup (with error handling)
sheet = None
try:
    if SHEET_URL:
        import gspread
        from google.oauth2.service_account import Credentials
        
        # Get service account from environment or use None
        service_account_json = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
        if service_account_json:
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

# Grocery database
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
order_tracking = {}
last_update_id = 0

# ==================== SIMPLE ORDER TRACKING SYSTEM ====================
def generate_order_id():
    """Generate unique order ID"""
    return f"ORD{int(time.time())}"

def save_order_tracking(order_id, chat_id, customer_name, phone, address, cart, total, status="Pending"):
    """Save order to tracking system"""
    try:
        # Create a safe copy of the cart
        cart_copy = {}
        for item_name, details in cart.items():
            cart_copy[item_name] = {
                'price': details['price'],
                'unit': details['unit'],
                'quantity': details['quantity']
            }
        
        order_tracking[order_id] = {
            'chat_id': chat_id,
            'customer_name': customer_name,
            'phone': phone,
            'address': address,
            'cart': cart_copy,
            'total': total,
            'status': status,
            'created_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'updated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        logger.info(f"✅ Order {order_id} saved to tracking system")
        return order_id
    except Exception as e:
        logger.error(f"❌ Error saving order tracking: {e}")
        return None

def update_order_status(order_id, new_status, admin_note=""):
    """Update order status and notify customer"""
    if order_id not in order_tracking:
        logger.error(f"❌ Order {order_id} not found in tracking")
        return False
    
    try:
        order = order_tracking[order_id]
        old_status = order['status']
        order['status'] = new_status
        order['updated_at'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # Notify customer
        notify_customer_order_update(order_id, new_status, admin_note)
        
        logger.info(f"✅ Order {order_id} status updated: {old_status} → {new_status}")
        return True
    except Exception as e:
        logger.error(f"❌ Error updating order status: {e}")
        return False

def notify_customer_order_update(order_id, new_status, admin_note=""):
    """Notify customer about order status update"""
    try:
        order = order_tracking.get(order_id)
        if not order:
            return
        
        chat_id = order['chat_id']
        customer_name = order['customer_name']
        
        status_messages = {
            'Shipped': f"""🚚 Order Shipped! 

Hi {customer_name},

Your order #{order_id} is on the way! 

Your groceries will arrive within 2 hours.

{f'📝 Note from store: {admin_note}' if admin_note else ''}

Thank you for choosing FreshMart! 🛒""",
            
            'Cancelled': f"""❌ Order Cancelled

Hi {customer_name},

We're sorry to inform you that your order #{order_id} has been cancelled.

{f'📝 Reason: {admin_note}' if admin_note else '📝 Reason: Unable to fulfill order at this time'}

We apologize for the inconvenience.

FreshMart Team 🛒""",
            
            'Delivered': f"""✅ Order Delivered! 

Hi {customer_name},

Your order #{order_id} has been successfully delivered!

Thank you for shopping with FreshMart! 🛒

We hope to serve you again soon! 🌟"""
        }
        
        message = status_messages.get(new_status)
        if message:
            send_message(chat_id, message)
            logger.info(f"✅ Customer notified about {new_status} status")
    except Exception as e:
        logger.error(f"❌ Error notifying customer: {e}")

# ==================== SIMPLE ADMIN ORDER MANAGEMENT ====================
def send_admin_order_notification(order_id, order_data):
    """Send new order notification to admin with action buttons"""
    if not ADMIN_CHAT_ID:
        logger.warning("⚠️ ADMIN_CHAT_ID not set, skipping admin notification")
        return
        
    try:
        order_summary = create_admin_order_summary(order_id, order_data)
        
        admin_message = f"""🆕 NEW ORDER #{order_id}

{order_summary}

⏰ Order Time: {order_data['created_at']}
📊 Status: {order_data['status']}

Choose action:"""
        
        # Inline keyboard for admin actions
        inline_keyboard = [
            [
                {'text': '🚚 Mark as Shipped', 'callback_data': f'ship_{order_id}'},
                {'text': '❌ Cancel Order', 'callback_data': f'cancel_{order_id}'}
            ],
            [
                {'text': '✅ Mark Delivered', 'callback_data': f'deliver_{order_id}'}
            ]
        ]
        
        if send_message(ADMIN_CHAT_ID, admin_message, inline_keyboard=inline_keyboard):
            logger.info(f"✅ Admin notified about new order {order_id}")
        else:
            logger.error(f"❌ Failed to notify admin about order {order_id}")
    except Exception as e:
        logger.error(f"❌ Error sending admin notification: {e}")

def create_admin_order_summary(order_id, order_data):
    """Create order summary for admin"""
    try:
        cart = order_data['cart']
        items_text = ""
        for item_name, details in cart.items():
            items_text += f"• {item_name} - {details['quantity']} {details['unit']}\n"
        
        summary = f"""👤 Customer: {order_data['customer_name']}
📞 Phone: {order_data['phone']}
📍 Address: {order_data['address']}

📦 Order Items:
{items_text}
💰 Total: ${order_data['total']:.2f}"""
        
        return summary
    except Exception as e:
        logger.error(f"❌ Error creating admin summary: {e}")
        return "Error generating order summary"

def handle_admin_callback(chat_id, callback_data):
    """Handle admin action callbacks"""
    if not ADMIN_CHAT_ID or str(chat_id) != ADMIN_CHAT_ID:
        send_message(chat_id, "❌ Unauthorized access.")
        return
    
    try:
        if callback_data.startswith('ship_'):
            order_id = callback_data[5:]
            if update_order_status(order_id, 'Shipped', 'Your order is on the way!'):
                send_message(chat_id, f"✅ Order #{order_id} marked as shipped! Customer notified.")
            else:
                send_message(chat_id, f"❌ Order #{order_id} not found.")
                
        elif callback_data.startswith('cancel_'):
            order_id = callback_data[7:]
            # Ask for cancellation reason
            user_sessions[chat_id] = {
                'step': 'awaiting_cancel_reason',
                'order_id': order_id
            }
            send_message(chat_id, f"📝 Please provide reason for cancelling order #{order_id}:")
            
        elif callback_data.startswith('deliver_'):
            order_id = callback_data[8:]
            if update_order_status(order_id, 'Delivered'):
                send_message(chat_id, f"✅ Order #{order_id} marked as delivered! Customer notified.")
            else:
                send_message(chat_id, f"❌ Order #{order_id} not found.")
                
    except Exception as e:
        logger.error(f"❌ Admin callback error: {e}")
        send_message(chat_id, "❌ Error processing admin action.")

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
        
        if response.status_code == 200:
            return True
        else:
            logger.error(f"Telegram API error: {response.status_code} - {response.text}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error sending message to {chat_id}: {e}")
        return False

# ==================== SIMPLE ORDER SUMMARY ====================
def create_order_summary(customer_name, phone, address, cart, special_instructions=""):
    """Create order summary"""
    try:
        subtotal = sum(details['price'] * details['quantity'] for details in cart.values())
        delivery_fee = 0 if subtotal >= 50 else 5
        total = subtotal + delivery_fee
        
        items_text = ""
        for item_name, details in cart.items():
            item_total = details['price'] * details['quantity']
            items_text += f"• {item_name} - {details['quantity']} {details['unit']} - ${item_total:.2f}\n"
        
        summary = f"""🛒 ORDER SUMMARY

Customer: {customer_name}
Phone: {phone}
Address: {address}

Items:
{items_text}
Subtotal: ${subtotal:.2f}
Delivery: ${delivery_fee:.2f}
TOTAL: ${total:.2f}

{f'Instructions: {special_instructions}' if special_instructions else ''}

Order Time: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}"""
        
        return summary, total
    except Exception as e:
        logger.error(f"❌ Error creating order summary: {e}")
        return "Error creating order summary", 0

# ==================== SIMPLE SHEET SAVING ====================
def save_order_to_sheet(order_id, customer_name, phone, address, cart, total, special_instructions=""):
    """Save order to Google Sheets - SIMPLIFIED"""
    if not sheet:
        logger.info("📝 Google Sheets not available, order saved locally only")
        return True
    
    try:
        subtotal = sum(details['price'] * details['quantity'] for details in cart.values())
        delivery_fee = 0 if subtotal >= 50 else 5
        
        # Simple items list
        items_list = []
        quantities_list = []
        for item_name, details in cart.items():
            items_list.append(item_name)
            quantities_list.append(f"{details['quantity']} {details['unit']}")

        # Join items with commas
        items_str = ", ".join(items_list)
        quantities_str = ", ".join(quantities_list)

        order_data = [
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            order_id,
            customer_name,
            phone,
            address,
            items_str,
            quantities_str,
            f"${subtotal:.2f}",
            f"${delivery_fee:.2f}",
            f"${total:.2f}",
            "Pending",
            special_instructions,
            "Cash on Delivery"
        ]

        sheet.append_row(order_data)
        logger.info(f"✅ Order {order_id} saved to Google Sheets")
        return True

    except Exception as e:
        logger.error(f"❌ Google Sheets save failed: {e}")
        return False

# ==================== SIMPLIFIED ORDER PROCESSING ====================
def complete_order(chat_id, customer_name, phone, address, cart, special_instructions):
    """Complete order processing - SIMPLIFIED AND FIXED"""
    try:
        logger.info(f"🔄 Starting order completion for {customer_name}")
        
        # Generate order ID
        order_id = generate_order_id()
        logger.info(f"📦 Generated Order ID: {order_id}")
        
        # Calculate total
        subtotal = sum(details['price'] * details['quantity'] for details in cart.values())
        delivery_fee = 0 if subtotal >= 50 else 5
        total = subtotal + delivery_fee
        
        # Save to tracking
        if not save_order_tracking(order_id, chat_id, customer_name, phone, address, cart, total):
            logger.error("❌ Failed to save order tracking")
            send_message(chat_id, "❌ Error saving your order. Please try again.")
            return False
        
        # Save to Google Sheets
        sheet_success = save_order_to_sheet(order_id, customer_name, phone, address, cart, total, special_instructions)
        
        # Send confirmation to customer (ALWAYS DO THIS)
        confirmation = f"""✅ Order Confirmed! 🎉

Thank you {customer_name}!

Your order has been received successfully.

📦 Order ID: #{order_id}
💰 Total Amount: ${total:.2f}
💵 Payment: Cash on Delivery

We'll notify you when your order is shipped! 🚚

FreshMart Grocery Delivery 🛒"""
        
        if not send_message(chat_id, confirmation):
            logger.error("❌ Failed to send confirmation to customer")
            # Try one more time
            time.sleep(1)
            send_message(chat_id, "✅ Your order has been received! We'll contact you soon.")
        
        # Notify admin
        try:
            order_data = order_tracking[order_id]
            send_admin_order_notification(order_id, order_data)
        except Exception as e:
            logger.error(f"❌ Admin notification failed: {e}")
        
        # Clear cart and session
        if chat_id in user_carts:
            user_carts[chat_id] = {}
        if chat_id in user_sessions:
            user_sessions[chat_id] = {'step': 'main_menu'}
        
        logger.info(f"🎉 Order {order_id} completed successfully for {customer_name}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Critical error in order completion: {e}")
        logger.error(traceback.format_exc())
        
        # Try to send error message to user
        try:
            send_message(chat_id, "❌ Sorry, there was an error processing your order. Please contact support.")
        except:
            pass
        return False

# ==================== BOT HANDLERS ====================
def handle_start(chat_id):
    welcome = """🛒 Welcome to FreshMart Grocery Delivery! 🛒

🌟 Fresh Groceries Delivered to Your Doorstep! 🌟

🚚 Free Delivery on orders over $50
⏰ Delivery Hours: 7 AM - 10 PM Daily  
💰 Payment: Cash on Delivery Available
📦 Real-time Order Tracking

What would you like to do?"""

    keyboard = [
        [{'text': '🛍️ Shop Groceries'}, {'text': '🛒 My Cart'}],
        [{'text': '📦 Track Order'}, {'text': '📞 Contact Store'}]
    ]

    send_message(chat_id, welcome, keyboard=keyboard)
    user_sessions[chat_id] = {'step': 'main_menu'}

def show_categories(chat_id):
    categories = """📋 Grocery Categories

Choose a category to start shopping:"""

    keyboard = [
        [{'text': '🥦 Fresh Produce'}, {'text': '🥩 Meat & Poultry'}],
        [{'text': '🥛 Dairy & Eggs'}, {'text': '🔙 Main Menu'}]
    ]

    send_message(chat_id, categories, keyboard=keyboard)

def show_category_items(chat_id, category):
    if category not in grocery_categories:
        send_message(chat_id, "Category not found.")
        return

    items_text = f"{category}\n\nSelect an item:"
    items = grocery_categories[category]
    inline_keyboard = []

    for item_name, details in items.items():
        button_text = f"{item_name} - ${details['price']}/{details['unit']}"
        inline_keyboard.append([{
            'text': button_text,
            'callback_data': f"add_{item_name}"
        }])

    inline_keyboard.append([{'text': '🔙 Back', 'callback_data': 'back_categories'}])

    send_message(chat_id, items_text, inline_keyboard=inline_keyboard)

def handle_add_to_cart(chat_id, item_name):
    item_details = None
    for category, items in grocery_categories.items():
        if item_name in items:
            item_details = items[item_name]
            break

    if not item_details:
        send_message(chat_id, "Item not found.")
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

    response = f"✅ Added {item_name} to cart!"
    send_message(chat_id, response)
    show_categories(chat_id)

def show_cart(chat_id):
    if chat_id not in user_carts or not user_carts[chat_id]:
        send_message(chat_id, "🛒 Your cart is empty!")
        return

    cart = user_carts[chat_id]
    total = 0
    cart_text = "🛒 Your Cart:\n\n"

    for item_name, details in cart.items():
        item_total = details['price'] * details['quantity']
        total += item_total
        cart_text += f"• {item_name} - {details['quantity']} {details['unit']} - ${item_total:.2f}\n"

    delivery_fee = 0 if total >= 50 else 5
    final_total = total + delivery_fee

    cart_text += f"\nSubtotal: ${total:.2f}"
    cart_text += f"\nDelivery: ${delivery_fee:.2f}"
    cart_text += f"\nTotal: ${final_total:.2f}"

    keyboard = [
        [{'text': '🚚 Checkout'}, {'text': '📋 Continue Shopping'}],
        [{'text': '🗑️ Clear Cart'}, {'text': '🔙 Main Menu'}]
    ]

    send_message(chat_id, cart_text, keyboard=keyboard)

def handle_checkout(chat_id):
    if chat_id not in user_carts or not user_carts[chat_id]:
        send_message(chat_id, "Your cart is empty!")
        return

    send_message(chat_id, "🚚 Let's get your order delivered!\n\nPlease provide your full name:")
    user_sessions[chat_id] = {'step': 'awaiting_name'}

def handle_callback_query(chat_id, callback_data):
    if callback_data.startswith('add_'):
        item_name = callback_data[4:]
        handle_add_to_cart(chat_id, item_name)
    elif callback_data == 'back_categories':
        show_categories(chat_id)
    elif callback_data.startswith(('ship_', 'cancel_', 'deliver_')):
        handle_admin_callback(chat_id, callback_data)

def get_updates(offset=None):
    global last_update_id
    
    if not TELEGRAM_TOKEN:
        return None
        
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    params = {'timeout': 30}
    if offset is not None:
        params['offset'] = offset
        
    try:
        response = requests.get(url, params=params, timeout=35)
        if response.status_code == 200:
            data = response.json()
            if data.get('ok') and data.get('result'):
                updates = data['result']
                if updates:
                    last_update_id = max(update['update_id'] for update in updates) + 1
                return data
        return None
    except Exception as e:
        logger.error(f"get_updates error: {e}")
        return None

def handle_message(chat_id, text):
    try:
        # Handle checkout flow first
        if user_sessions.get(chat_id, {}).get('step') == 'awaiting_name':
            customer_name = text
            user_sessions[chat_id] = {'step': 'awaiting_phone', 'customer_name': customer_name}
            send_message(chat_id, f"👋 Thanks {customer_name}! Please provide your phone number:")
            return

        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_phone':
            user_phone = text
            customer_name = user_sessions[chat_id]['customer_name']
            user_sessions[chat_id] = {'step': 'awaiting_address', 'customer_name': customer_name, 'phone': user_phone}
            send_message(chat_id, "📦 Please provide your delivery address:")
            return

        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_address':
            user_address = text
            customer_name = user_sessions[chat_id]['customer_name']
            user_phone = user_sessions[chat_id]['phone']
            user_sessions[chat_id] = {'step': 'awaiting_instructions', 'customer_name': customer_name, 'phone': user_phone, 'address': user_address}
            send_message(chat_id, "📝 Any special instructions? (or type 'None'):")
            return

        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_instructions':
            special_instructions = text if text.lower() != 'none' else ""
            session_data = user_sessions[chat_id]
            
            # Process the order
            logger.info(f"🔄 Processing order for {session_data['customer_name']}")
            success = complete_order(
                chat_id,
                session_data['customer_name'],
                session_data['phone'],
                session_data['address'],
                user_carts.get(chat_id, {}),
                special_instructions
            )
            
            if success:
                logger.info(f"✅ Order completed successfully for {session_data['customer_name']}")
            else:
                logger.error(f"❌ Order failed for {session_data['customer_name']}")
                send_message(chat_id, "❌ Order failed. Please try again.")
            
            return

        elif user_sessions.get(chat_id, {}).get('step') == 'awaiting_cancel_reason':
            order_id = user_sessions[chat_id].get('order_id')
            if order_id and update_order_status(order_id, 'Cancelled', text):
                send_message(chat_id, f"✅ Order #{order_id} cancelled!")
            user_sessions[chat_id] = {'step': 'main_menu'}
            return

        # Handle main menu commands
        if text == '/start':
            handle_start(chat_id)
        elif text == '🛍️ Shop Groceries':
            show_categories(chat_id)
        elif text == '🛒 My Cart':
            show_cart(chat_id)
        elif text == '📦 Track Order':
            user_orders = [(oid, o) for oid, o in order_tracking.items() if o['chat_id'] == chat_id]
            if user_orders:
                track_text = "📦 Your Orders:\n\n"
                for order_id, order in user_orders[-3:]:
                    track_text += f"#{order_id} - {order['status']} - ${order['total']:.2f}\n"
                send_message(chat_id, track_text)
            else:
                send_message(chat_id, "No orders found.")
        elif text == '🚚 Checkout':
            handle_checkout(chat_id)
        elif text == '🗑️ Clear Cart':
            if chat_id in user_carts:
                user_carts[chat_id] = {}
            send_message(chat_id, "Cart cleared!")
        elif text == '📋 Continue Shopping' or text == '🔙 Main Menu':
            handle_start(chat_id)
        elif text in grocery_categories:
            show_category_items(chat_id, text)
        else:
            handle_start(chat_id)

    except Exception as e:
        logger.error(f"❌ Error handling message: {e}")
        logger.error(traceback.format_exc())
        send_message(chat_id, "❌ An error occurred. Please try /start")

def main():
    if not TELEGRAM_TOKEN:
        logger.error("❌ TELEGRAM_TOKEN not set!")
        return

    logger.info("🛒 Bot Started Successfully!")
    logger.info("📱 Ready to take orders!")

    while True:
        try:
            updates = get_updates(last_update_id)
            
            if updates and 'result' in updates:
                for update in updates['result']:
                    try:
                        if 'message' in update and 'text' in update['message']:
                            chat_id = update['message']['chat']['id']
                            text = update['message']['text']
                            handle_message(chat_id, text)

                        elif 'callback_query' in update:
                            callback = update['callback_query']
                            chat_id = callback['message']['chat']['id']
                            callback_data = callback['data']
                            handle_callback_query(chat_id, callback_data)
                    except Exception as e:
                        logger.error(f"❌ Error processing update: {e}")

            time.sleep(1)
            
        except Exception as e:
            logger.error(f"❌ Main loop error: {e}")
            time.sleep(5)

if __name__ == '__main__':
    main()
