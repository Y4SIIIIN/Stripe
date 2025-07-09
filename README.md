# Stripe

A Telegram bot that uses Stripe Checkout for payments and manages user wallet balances via SQLite.

## ⚙️ Features

- Stripe Checkout integration (card, iDEAL, Bancontact)
- SQLite-based wallet system
- Automatic balance updates after successful payments
- Inline buttons and interactive Telegram UI
- Admin commands:
- Add/Subtract/Set balance
- View user payments and balances

## 🚀 How it works

1. User starts the bot and enters the amount to top-up.
2. Bot calculates Stripe fees and generates a payment button.
3. User pays via Stripe Checkout.
4. HTTP server listens for Stripe success callback.
5. User balance is updated in the local SQLite database.

## 🛠 Setup

1. Clone this repo
2. Replace `STRIPE_API` and `BOT_TOKEN` in the script
3. Open port `81` or use [ngrok](https://ngrok.com/) to expose your HTTP server
4. Run the bot

## 📦 Requirements

- Python 3.8+
- `python-telegram-bot`
- `stripe`
- `sqlite3`

Install with:

```bash
pip install python-telegram-bot stripe
