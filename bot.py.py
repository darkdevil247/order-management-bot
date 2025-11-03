# bot.py - Safe to deploy and share
import os
import requests
import logging
from datetime import datetime

print("🛒 Starting FreshMart Grocery Delivery Bot...")

# Get credentials from environment (safe approach)
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN')
ADMIN_CHAT_ID = os.environ.get('ADMIN_CHAT_ID')
SHEET_URL = os.environ.get('SHEET_URL')

# Your existing bot code goes here (the 200+ lines you showed me)
# But replace hardcoded tokens with the variables above

def main():
    # Your existing main function
    pass

if __name__ == '__main__':
    main()
