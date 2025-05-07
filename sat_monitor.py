#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import json
import logging
import os
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("sat_monitor.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("sat_monitor")

# Configuration
URL = "https://satsuite.collegeboard.org/sat/dates-deadlines"
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "YOUR_DISCORD_WEBHOOK_URL_HERE")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1002594329611")
DATE_THRESHOLD = 6  # Alert if more than this many dates are found


def fetch_page():
    """Fetch the SAT dates page using requests"""
    logger.info(f"Fetching {URL}")

    try:
        # Add headers to mimic a browser
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5'
        }

        # Make the request with a longer timeout
        response = requests.get(URL, headers=headers, timeout=30)
        response.raise_for_status()

        logger.info("Successfully fetched page with requests")
        return response.text

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch the page: {e}")
        return None


def extract_test_dates(html_content):
    """Extract the current test dates from the table using BeautifulSoup"""
    if not html_content:
        return []

    try:
        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')

        # Find the table with the specific class
        table = soup.find('table', class_='cb-table cb-no-margin-top')

        if not table:
            logger.warning("Could not find the SAT dates table")
            return []

        # Find all rows in the table
        rows = table.find_all('tr')

        # Extract dates from the first column, excluding the header row
        test_dates = []
        for row in rows[1:]:  # Skip the header row
            # Find the first th element (date column)
            date_cell = row.find('th', scope='row')
            if date_cell and date_cell.text.strip() and any(char.isdigit() for char in date_cell.text):
                test_dates.append(date_cell.text.strip())

        logger.info(f"Found {len(test_dates)} test dates")
        return test_dates
    except Exception as e:
        logger.error(f"Error extracting test dates: {e}")
        return []


def send_discord_notification(test_dates):
    """Send notification to Discord webhook"""
    if not DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL == "YOUR_DISCORD_WEBHOOK_URL_HERE":
        logger.warning("Discord webhook URL not configured, skipping Discord notification")
        return False

    logger.info(f"Sending Discord notification about {len(test_dates)} test dates")

    try:
        # Create message payload
        message = {
            "embeds": [{
                "title": "⚠️ SAT Test Dates Alert",
                "description": f"Found {len(test_dates)} SAT test dates, which exceeds the threshold of {DATE_THRESHOLD}.",
                "color": 16711680,  # Red color
                "fields": [
                    {
                        "name": "Current Test Dates",
                        "value": "\n".join([f"• {date}" for date in test_dates]),
                        "inline": False
                    },
                    {
                        "name": "Check Time",
                        "value": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "inline": False
                    },
                    {
                        "name": "URL",
                        "value": URL,
                        "inline": False
                    }
                ],
                "footer": {
                    "text": "SAT Test Dates Monitor"
                }
            }]
        }

        # Send notification
        response = requests.post(
            DISCORD_WEBHOOK_URL,
            json=message,
            headers={"Content-Type": "application/json"},
            timeout=10
        )
        response.raise_for_status()

        logger.info("Discord notification sent successfully")
        return True
    except Exception as e:
        logger.error(f"Error sending Discord notification: {e}")
        return False


def send_telegram_notification(test_dates):
    """Send notification to Telegram channel"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.warning("Telegram bot token not configured, skipping Telegram notification")
        return False

    logger.info(f"Sending Telegram notification about {len(test_dates)} test dates")

    try:
        # Create message text
        message_text = (
            f"⚠️ *SAT Test Dates Alert*\n\n"
            f"Found {len(test_dates)} SAT test dates, which exceeds the threshold of {DATE_THRESHOLD}.\n\n"
            f"*Current Test Dates:*\n"
        )

        # Add each test date
        for date in test_dates:
            message_text += f"• {date}\n"

        # Add check time and URL
        message_text += f"\n*Check Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        message_text += f"*URL:* {URL}"

        # Telegram Bot API URL
        telegram_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

        # Prepare payload
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message_text,
            "parse_mode": "Markdown"
        }

        # Send notification
        response = requests.post(
            telegram_url,
            json=payload,
            timeout=10
        )
        response.raise_for_status()

        # Check response from Telegram
        response_json = response.json()
        if response_json.get("ok"):
            logger.info("Telegram notification sent successfully")
            return True
        else:
            logger.error(f"Telegram API error: {response_json.get('description', 'Unknown error')}")
            return False

    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")
        return False


def main():
    """Main function"""
    logger.info(f"Starting SAT Test Dates monitoring (threshold: {DATE_THRESHOLD})")

    # Fetch the page
    html_content = fetch_page()

    if html_content:
        # Extract current test dates
        test_dates = extract_test_dates(html_content)

        if not test_dates:
            logger.error("Failed to extract test dates")
            return

        # Check if the number of test dates exceeds the threshold
        if len(test_dates) > DATE_THRESHOLD:
            logger.warning(f"Found {len(test_dates)} test dates, which exceeds the threshold of {DATE_THRESHOLD}")

            # Send notifications to both platforms
            discord_result = send_discord_notification(test_dates)
            telegram_result = send_telegram_notification(test_dates)

            if discord_result and telegram_result:
                logger.info("All notifications sent successfully")
            elif discord_result:
                logger.warning("Only Discord notification sent successfully")
            elif telegram_result:
                logger.warning("Only Telegram notification sent successfully")
            else:
                logger.error("All notifications failed")
        else:
            logger.info(f"Found {len(test_dates)} test dates, which does not exceed the threshold of {DATE_THRESHOLD}")

    logger.info("Monitoring completed")


if __name__ == "__main__":
    main()