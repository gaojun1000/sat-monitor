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
DATE_THRESHOLD = 7  # Alert if more than this many dates are found
STATE_FILE = "sat_monitor_state.json"  # File to store the last modified timestamp


def fetch_page():
    """Fetch the SAT dates page using requests and capture the Last-Modified header"""
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

        # Get the Last-Modified header if it exists
        last_modified = response.headers.get('Last-Modified')

        if last_modified:
            logger.info(f"Page Last-Modified: {last_modified}")
        else:
            # If no Last-Modified header, use ETag or current time
            last_modified = response.headers.get('ETag') or datetime.now().isoformat()
            logger.info(f"No Last-Modified header, using alternative: {last_modified}")

        logger.info("Successfully fetched page with requests")
        return {
            'content': response.text,
            'last_modified': last_modified,
            'status_code': response.status_code
        }

    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to fetch the page: {e}")
        return None


def load_state():
    """Load the previous state from file"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r') as f:
                state = json.load(f)
            logger.info(f"Loaded state from {STATE_FILE}")
            return state
        else:
            logger.info(f"No state file found at {STATE_FILE}")
            return None
    except Exception as e:
        logger.error(f"Error loading state: {e}")
        return None


def save_state(last_modified, test_dates):
    """Save the current state to file"""
    state = {
        "timestamp": datetime.now().isoformat(),
        "last_modified": last_modified,
        "test_date_count": len(test_dates),
        "test_dates": test_dates
    }

    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
        logger.info(f"Saved state to {STATE_FILE}")
    except Exception as e:
        logger.error(f"Error saving state: {e}")


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


def send_discord_notification(test_dates, page_changed=False, last_modified=None, prev_modified=None):
    """Send notification to Discord webhook"""
    if not DISCORD_WEBHOOK_URL or DISCORD_WEBHOOK_URL == "YOUR_DISCORD_WEBHOOK_URL_HERE":
        logger.warning("Discord webhook URL not configured, skipping Discord notification")
        return False

    notification_reason = []
    if len(test_dates) > DATE_THRESHOLD:
        notification_reason.append(
            f"Found {len(test_dates)} SAT test dates, which exceeds the threshold of {DATE_THRESHOLD}")
    if page_changed:
        notification_reason.append("The SAT dates page has been modified")

    notification_text = " and ".join(notification_reason)

    logger.info(f"Sending Discord notification: {notification_text}")

    try:
        # Create message payload
        message = {
            "embeds": [{
                "title": "⚠️ SAT Test Dates Alert",
                "description": notification_text,
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
                    }
                ],
                "footer": {
                    "text": "SAT Test Dates Monitor"
                }
            }]
        }

        # Add modification times if available
        if last_modified:
            message["embeds"][0]["fields"].append({
                "name": "Current Last-Modified",
                "value": last_modified,
                "inline": False
            })

        if prev_modified and page_changed:
            message["embeds"][0]["fields"].append({
                "name": "Previous Last-Modified",
                "value": prev_modified,
                "inline": False
            })

        # Add URL field
        message["embeds"][0]["fields"].append({
            "name": "URL",
            "value": URL,
            "inline": False
        })

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


def send_telegram_notification(test_dates, page_changed=False, last_modified=None, prev_modified=None):
    """Send notification to Telegram channel"""
    if not TELEGRAM_BOT_TOKEN or TELEGRAM_BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        logger.warning("Telegram bot token not configured, skipping Telegram notification")
        return False

    notification_reason = []
    if len(test_dates) > DATE_THRESHOLD:
        notification_reason.append(
            f"Found {len(test_dates)} SAT test dates, which exceeds the threshold of {DATE_THRESHOLD}")
    if page_changed:
        notification_reason.append("The SAT dates page has been modified")

    notification_text = " and ".join(notification_reason)

    logger.info(f"Sending Telegram notification: {notification_text}")

    try:
        # Create message text
        message_text = (
            f"⚠️ *SAT Test Dates Alert*\n\n"
            f"{notification_text}\n\n"
            f"*Current Test Dates:*\n"
        )

        # Add each test date
        for date in test_dates:
            message_text += f"• {date}\n"

        # Add check time
        message_text += f"\n*Check Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

        # Add modification times if available
        if last_modified:
            message_text += f"*Current Last-Modified:* {last_modified}\n"

        if prev_modified and page_changed:
            message_text += f"*Previous Last-Modified:* {prev_modified}\n"

        # Add URL
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
    logger.info("Starting SAT Test Dates monitoring")

    # Fetch the page
    page_data = fetch_page()

    if not page_data:
        logger.error("Failed to fetch the page, exiting")
        return

    html_content = page_data['content']
    last_modified = page_data['last_modified']

    # Extract test dates
    test_dates = extract_test_dates(html_content)

    if not test_dates:
        logger.error("Failed to extract test dates")
        return

    # Load previous state
    prev_state = load_state()

    # Determine if we need to send notifications
    should_notify = False
    page_changed = False
    prev_modified = None

    # Check if we have previous state
    if prev_state:
        # Check if the page has changed since last time based on Last-Modified
        if last_modified != prev_state.get("last_modified"):
            page_changed = True
            prev_modified = prev_state.get("last_modified")
            should_notify = True
            logger.info(f"Page has been modified since last check (Last-Modified changed)")
        else:
            logger.info("Page has not been modified since last check")
    else:
        # No previous state, this is the first run
        logger.info("First run, no previous state to compare")

    # Check if the number of test dates exceeds the threshold
    if len(test_dates) > DATE_THRESHOLD:
        should_notify = True
        logger.info(f"Found {len(test_dates)} test dates, which exceeds the threshold of {DATE_THRESHOLD}")

    # Send notifications if needed
    if should_notify:
        discord_result = send_discord_notification(test_dates, page_changed, last_modified, prev_modified)
        telegram_result = send_telegram_notification(test_dates, page_changed, last_modified, prev_modified)

        if discord_result and telegram_result:
            logger.info("All notifications sent successfully")
        elif discord_result:
            logger.warning("Only Discord notification sent successfully")
        elif telegram_result:
            logger.warning("Only Telegram notification sent successfully")
        else:
            logger.error("All notifications failed")
    else:
        logger.info("No need to send notifications")

    # Save current state
    save_state(last_modified, test_dates)

    logger.info("Monitoring completed")


if __name__ == "__main__":
    main()