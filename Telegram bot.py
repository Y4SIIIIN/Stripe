import os
# CHARACTER IS HOW YOU TREAT SOMEONE WHO CAN DO NOTHING FOR YOU.
import threading
import sqlite3
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, CallbackContext, MessageHandler, Filters
import stripe
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import logging

#Some info, if your server is unable to connect with the given ports make usage of ngrok


logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG)

logger = logging.getLogger(__name__)

# Initialize Stripe
stripe.api_key = "STRIPE_API"

def setup_database():
    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payments (
        user_id TEXT,
        username TEXT,
        session_id TEXT,
        payment_status TEXT,
        amount REAL,
        transaction_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        chat_id TEXT
    )
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wallets (
        user_id TEXT PRIMARY KEY,
        username TEXT,
        balance REAL DEFAULT 0
    )
    """)
    
    conn.commit()
    conn.close()



def start(update: Update, context: CallbackContext) -> None:
    update.callback_query.message.reply_text('Please input the amount you want to pay (in €). Fees will be added for the transaction. This will be added to your wallet')

def calculate_fee(amount: float) -> float:
    return (amount * 0.015) + 0.25

def handle_amount(update: Update, context: CallbackContext) -> None:
    try:
        amount = float(update.message.text)
        fee = calculate_fee(amount)
        total_amount = amount + fee
        
        context.user_data['original_amount'] = amount
        context.user_data['fee'] = fee
        context.user_data['total_amount'] = total_amount

        keyboard = [
            [InlineKeyboardButton(f"Pay €{total_amount:.2f} (includes €{fee:.2f} fee)", callback_data='initiate_payment')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        update.message.reply_text('Please confirm your payment:', reply_markup=reply_markup)

    except ValueError:
        update.message.reply_text('Invalid amount. Please input a valid number.')

def ensure_wallet_exists(user_id, username):
    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id FROM wallets WHERE user_id = ?", (user_id,))
    user_exists = cursor.fetchone()
    
    if not user_exists:
        cursor.execute("INSERT INTO wallets (user_id, username) VALUES (?, ?)", (user_id, username))
        conn.commit()
        
    conn.close()

def initiate_payment(update: Update, context: CallbackContext) -> None:
    print("Initiating payment...")  # Debugging statement

    query = update.callback_query
    user_id = query.message.chat_id
    amount = context.user_data.get('original_amount', 0)
    total_amount = context.user_data.get('total_amount', 0)
    final_amount = round(total_amount * 100)  # Convert to cents

    # Debugging statements
    print(f"User ID: {user_id}")
    print(f"Amount: {amount}")
    print(f"Total Amount: {total_amount}")
    print(f"Final Amount (in cents): {final_amount}")

    session = stripe.checkout.Session.create(
        payment_method_types=['card', 'bancontact', 'ideal'],
        line_items=[{
            'price_data': {
                'currency': 'eur',
                'product_data': {
                    'name': 'OKiU Payments',
                },
                'unit_amount': final_amount,
            },
            'quantity': 1,
        }],
        mode='payment',
        success_url='http://SERVER_IP/DOMAIN:80/success?session_id={CHECKOUT_SESSION_ID}',
        cancel_url='http://SERVER_IP/DOMAIN:80/cancel',
    )

    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()
    username = query.from_user.username if query.from_user else None

    cursor.execute("""
    INSERT INTO payments (user_id, username, session_id, payment_status, amount) 
    VALUES (?, ?, ?, ?, ?)""", (user_id, username, session.id, 'pending', total_amount))

    conn.commit()

    keyboard = [
        [InlineKeyboardButton(f"Pay Now €{total_amount:.2f}", url=session.url)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(text=f"Your total amount including fees is €{total_amount:.2f}. Click the button below to pay:", reply_markup=reply_markup)

from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import sqlite3

class RequestHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        parsed_url = urlparse(self.path)
        
        # Check if the request is for the /success endpoint
        if parsed_url.path == "/success":
            query_params = parse_qs(parsed_url.query)
            session_id = query_params.get('session_id', [None])[0]
            
            if session_id:
                conn = sqlite3.connect('payments.db')
                cursor = conn.cursor()

                # Check if payment is already completed for that session_id
                cursor.execute("SELECT payment_status FROM payments WHERE session_id = ?", (session_id,))
                status = cursor.fetchone()
                if status and status[0] == 'completed':
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(b"Payment Already Completed! go back to the bot!")
                    conn.close()
                    return
                
                # Update payment status to completed
                cursor.execute("UPDATE payments SET payment_status = 'completed' WHERE session_id = ?", (session_id,))
                conn.commit()

                # Fetch the user_id, username, and amount from the payment table for that session_id
                cursor.execute("SELECT user_id, username, amount FROM payments WHERE session_id = ?", (session_id,))
                user_data = cursor.fetchone()
                if user_data:
                    user_id, username, amount = user_data
                    ensure_wallet_exists(user_id, username)

                    # Update the user's balance in the wallet
                    cursor.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
                    conn.commit()
                    conn.close()
                    context.bot.send_message(chat_id=user_id, text=f"Your payment was successful! €{amount:.2f} has been added to your wallet.", parse_mode='Markdown')

                # Send a redirect response
                self.send_response(302)
                self.send_header('Location', '/payment_completed')
                self.end_headers()
                
            else:
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"Bad Request")

        # For the redirected /payment_completed endpoint
        elif parsed_url.path == "/payment_completed":
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"Payment Successful!")
        
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"Page Not Found, but not that there is something interesting here anyways...")

# Your ensure_wallet_exists function would go here...
def ensure_wallet_exists(user_id, username):
    """
    Ensures a wallet exists for the user.
    If not, create one with a default balance of 0.0.
    """
    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()

    cursor.execute("""
    SELECT 1 FROM wallets WHERE user_id = ?
    """, (user_id,))

    exists = cursor.fetchone()
    if not exists:
        cursor.execute("""
        INSERT INTO wallets (user_id, username, balance) VALUES (?, ?, 0.0)
        """, (user_id, username))
        conn.commit()

    conn.close()

def send_inline_commands(update: Update, context: CallbackContext) -> None:
    keyboard = [
        [InlineKeyboardButton("Start", callback_data='start')],
        [InlineKeyboardButton("ID Pay", callback_data='idpay')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text('Please choose a command:', reply_markup=reply_markup)

def handle_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query_data = query.data

    if query_data == "buy":
        start(update, context)
    elif query_data == "idpay":
        idpay(update, context)
    elif query_data == "balance":
        check_balance(update, context)
    
    # After handling, you can optionally edit the original message to remove the inline buttons:
    query.edit_message_text(text=f"You selected: {query_data}")


def update_wallet_balance(user_id, amount):
    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()
    
    # Update wallet balance (this is a hypothetical example and assumes you have a balance column in a wallet table)
    cursor.execute("UPDATE wallet SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    
    conn.close()


def add_balance(update: Update, context: CallbackContext) -> None:
    try:
        user_id = context.args[0]
        amount_to_add = float(context.args[1])
        
        conn = sqlite3.connect('payments.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE wallets SET balance = balance + ? WHERE user_id = ?", (amount_to_add, user_id))
        conn.commit()
        conn.close()

        update.message.reply_text(f"Added €{amount_to_add:.2f} to the balance of user {user_id}.")
    except:
        update.message.reply_text("Error in adding balance. Make sure you used the format `/addbalance <user_id> <amount>`")

def subtract_balance(update: Update, context: CallbackContext) -> None:
    try:
        user_id = context.args[0]
        amount_to_subtract = float(context.args[1])
        
        conn = sqlite3.connect('payments.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE wallets SET balance = balance - ? WHERE user_id = ?", (amount_to_subtract, user_id))
        conn.commit()
        conn.close()

        update.message.reply_text(f"Subtracted €{amount_to_subtract:.2f} from the balance of user {user_id}.")
    except:
        update.message.reply_text("Error in subtracting balance. Make sure you used the format `/subtractbalance <user_id> <amount>`")

# Add the handlers for these commands
def check_balance(update: Update, context: CallbackContext) -> None:
    if update.callback_query:
        user_id_query = context.args[0] if context.args else str(update.callback_query.message.chat_id)
        callback = True
    else:
        user_id_query = context.args[0] if context.args else str(update.message.chat_id)
        callback = False
    
    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM wallets WHERE user_id = ?", (user_id_query,))
    balance = cursor.fetchone()
    
    if balance:
        if callback:
            update.callback_query.message.reply_text(f"Your UserID is {user_id_query} and you have: €{balance[0]:.2f} balance")
        else:
            update.message.reply_text(f"Your UserID is {user_id_query} and you have: €{balance[0]:.2f} balance")
    else:
        if callback:
            update.callback_query.message.reply_text(f"No wallet found for user {user_id_query}.")
        else:
            update.message.reply_text(f"No wallet found for user {user_id_query}.")

    # Now, call the welcome_menu to show the main menu options.
    welcome_menu(update, context)
   


from telegram import Update
from telegram.ext import CallbackContext
import sqlite3

def set_balance(update: Update, context: CallbackContext) -> None:
    chat_id = update.message.chat_id

    try:
        # Extract user_id/username and amount from the arguments
        user_identifier = context.args[0].lstrip("@")
        new_balance = float(context.args[1])

        # Connect to the database
        conn = sqlite3.connect('payments.db')
        cursor = conn.cursor()

        # Check if the identifier is a user_id (integer) or username (string)
        if user_identifier.isdigit():
            user_id = int(user_identifier)
            cursor.execute("UPDATE wallets SET balance = ? WHERE user_id = ?", (new_balance, user_id))
            conn.commit()
        else:
            username = user_identifier
            cursor.execute("UPDATE wallets SET balance = ? WHERE username = ?", (new_balance, username))
        conn.commit()
        
        if cursor.rowcount == 0:
            raise ValueError("No user found with the given identifier")
        
        # Send a message to the user
        context.bot.send_message(
            chat_id=chat_id, 
            text=f"Balance for user {user_identifier} has been set to {new_balance}"
        )
    except Exception as e:
        # Send an error message if there's any issue
        context.bot.send_message(
            chat_id=chat_id, 
            text=f"Error: {e}"
        )

        conn.close()

        # Send a confirmation message to the admin
        update.message.reply_text(f"Set balance of user @{user_identifier} to €{new_balance:.2f},-")
    except ValueError as e:
        update.message.reply_text(str(e))
    except:
        update.message.reply_text("Error in setting balance. Make sure you used the format `/setbalance <user_id/username> <amount>`")

def welcome_menu(update: Update, context: CallbackContext) -> None:
    if update.callback_query:
        user_message = update.callback_query.message
    else:
        user_message = update.message

    keyboard = [
        [InlineKeyboardButton("Buy", callback_data='buy')],
        # [InlineKeyboardButton("ID Pay", callback_data='idpay')],
        [InlineKeyboardButton("Check Balance", callback_data='balance')],
        # You can add more options here...
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    user_message.reply_text('Please choose an option from the menu:', reply_markup=reply_markup)




def idpay(update: Update, context: CallbackContext) -> None:
    query_arg = context.args[0] if context.args else None

    if not query_arg:
        update.callback_query.message.reply_text("Please provide a user ID or username.")
        return

    conn = sqlite3.connect('payments.db')
    cursor = conn.cursor()

    if query_arg.startswith("@"):  # We assume it's a username
        cursor.execute("""
        SELECT user_id FROM payments WHERE username = ? LIMIT 1
        """, (query_arg[1:],))
        user_id_query = cursor.fetchone()
        if not user_id_query:
            update.message.reply_text(f"No data found for username {query_arg}")
            return
        user_id_query = user_id_query[0]
    else:
        user_id_query = query_arg

    # Get total amount paid by the user
    cursor.execute("""
    SELECT SUM(amount) FROM payments WHERE user_id = ? AND payment_status = 'completed'
    """, (user_id_query,))
    total_paid = cursor.fetchone()[0] or 0.0

    # Get the last two transactions of the user
    cursor.execute("""
    SELECT amount, transaction_timestamp FROM payments WHERE user_id = ? AND payment_status = 'completed' ORDER BY transaction_timestamp DESC LIMIT 2
    """, (user_id_query,))
    last_two_transactions = cursor.fetchall()

    conn.close()

    # Prepare the message
    message = f"User ID: {user_id_query}\n"
    message += f"Total amount paid: €{total_paid:.2f}\n\nLast two transactions:\n"

    for idx, (amount, timestamp) in enumerate(last_two_transactions, 1):
        message += f"{idx}. €{amount:.2f} on {timestamp}\n"

    update.message.reply_text(message)

def run_server():
    server_address = ('0.0.0.0', 81)
    httpd = HTTPServer(server_address, RequestHandler)
    print('Running server...')
    httpd.serve_forever()

def main():
    updater = Updater(token="BOT_TOKEN")
    global context
    context = CallbackContext.from_update(update=None, dispatcher=updater.dispatcher)

    dp = updater.dispatcher
    dp.add_handler(CommandHandler("buy", start))
    dp.add_handler(MessageHandler(Filters.regex(r'^\d+(\.\d{1,2})?$'), handle_amount))
    dp.add_handler(CallbackQueryHandler(initiate_payment, pattern='^' + str('initiate_payment') + '$'))
    dp.add_handler(CommandHandler("idpay", idpay, pass_args=True))
    dp.add_handler(CommandHandler("addbalance", add_balance, pass_args=True))
    dp.add_handler(CommandHandler("subtractbalance", subtract_balance, pass_args=True))
    dp.add_handler(CommandHandler("balance", check_balance, pass_args=True))
    dp.add_handler(CommandHandler("commands", send_inline_commands))
    dp.add_handler(CallbackQueryHandler(handle_callback))
    dp.add_handler(CommandHandler("start", welcome_menu))
    dp.add_handler(CommandHandler("setbalance", set_balance, pass_args=True))

    server_thread = threading.Thread(target=run_server)
    server_thread.start()

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    setup_database()
    main()
