#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup, Comment
import json
import logging
import os
import time
from datetime import datetime
from typing import Dict, List, Optional, Union
import hashlib
import re

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
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "-1002594329611")
DATE_THRESHOLD = 7  # Alert if more than this many dates are found
STATE_FILE = "sat_monitor_state.json"  # File to store the last state


def clean_html_for_hash(html_content: str) -> str:
    """
    Clean the HTML content to remove elements that might change frequently
    but don't affect the actual content we care about.
    """
    try:
        # Parse the HTML
        soup = BeautifulSoup(html_content, 'html.parser')

        # Remove common dynamic elements

        # 1. Remove all script tags (JavaScript can contain timestamps, random values, etc.)
        for script in soup.find_all('script'):
            script.decompose()

        # 2. Remove all style tags (CSS can change without affecting content)
        for style in soup.find_all('style'):
            style.decompose()

        # 3. Remove comments (may contain build info, timestamps)
        for comment in soup.find_all(text=lambda text: isinstance(text, Comment)):
            comment.extract()

        # 4. Remove meta tags (often contain dynamic content)
        for meta in soup.find_all('meta'):
            meta.decompose()

        # 5. Remove specific attributes that might change frequently
        for tag in soup.find_all(True):  # Find all elements
            # Remove data-* attributes (often used for dynamic data)
            attrs_to_remove = [attr for attr in tag.attrs if attr.startswith('data-')]
            # Also remove common attributes that may change without affecting content
            attrs_to_remove.extend(['class', 'id', 'style', 'data-reactid', 'data-react-checksum'])

            for attr in attrs_to_remove:
                if attr in tag.attrs:
                    del tag.attrs[attr]

        # 6. Convert the cleaned soup back to string
        cleaned_html = str(soup)

        # 7. Remove whitespace variations
        cleaned_html = re.sub(r'\s+', ' ', cleaned_html)

        # 8. Extract just the main content table if possible
        content_soup = BeautifulSoup(cleaned_html, 'html.parser')
        table = content_soup.find('table')
        if table:
            # If we can identify the main content table, just use that for hash
            logger.info("Using only the table content for hash calculation")
            cleaned_html = str(table)

        return cleaned_html
    except Exception as e:
        logger.error(f"Error cleaning HTML for hash: {e}")
        # Fall back to original content if cleaning fails
        return html_content


def calculate_content_hash(text: str) -> str:
    """Calculate MD5 hash of the content"""
    # First clean the HTML to remove dynamic elements
    cleaned_text = clean_html_for_hash(text)
    logger.info(f"Original text length: {len(text)}, Cleaned text length: {len(cleaned_text)}")
    return hashlib.md5(cleaned_text.encode('utf-8')).hexdigest()


def fetch_page() -> Optional[Dict[str, str]]:
    """Fetch the SAT dates page using requests and capture content hash"""
    logger.info(f"Fetching {URL}")

    # Add retry mechanism for robustness
    max_retries = 3
    retry_delay = 5  # seconds

    for attempt in range(max_retries):
        try:
            # Add headers to mimic a browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
                'Cache-Control': 'no-cache',
                'Pragma': 'no-cache'
            }

            # Make the request with a longer timeout
            response = requests.get(URL, headers=headers, timeout=30)
            response.raise_for_status()

            # Calculate content hash on cleaned HTML
            content_hash = calculate_content_hash(response.text)
            logger.info(f"Page content MD5 hash (after cleaning): {content_hash}")

            # Still log Last-Modified for reference
            last_modified = response.headers.get('Last-Modified', 'N/A')
            logger.info(f"Page Last-Modified: {last_modified}")

            logger.info(f"Successfully fetched page with status code: {response.status_code}")
            return {
                'content': response.text,
                'content_hash': content_hash,
                'last_modified': last_modified,
                'status_code': response.status_code
            }

        except requests.exceptions.RequestException as e:
            attempt_num = attempt + 1
            if attempt_num < max_retries:
                logger.warning(f"Attempt {attempt_num}/{max_retries} failed: {e}. Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                logger.error(f"All {max_retries} attempts failed to fetch the page: {e}")
                return None

    return None


def load_state() -> Optional[Dict[str, Union[str, int, List[str]]]]:
    """Load the previous state from file"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                state = json.load(f)
            logger.info(f"Loaded state from {STATE_FILE}")
            # Don't log the entire state as it might contain sensitive data
            logger.info(f"State contains {len(state)} keys")
            return state
        else:
            logger.info(f"No state file found at {STATE_FILE}, will create a new one")
            return None
    except json.JSONDecodeError as e:
        logger.error(f"Error parsing state file (corrupted JSON): {e}")
        # Rename the corrupted file for debugging
        backup_name = f"{STATE_FILE}.corrupted.{int(time.time())}"
        try:
            os.rename(STATE_FILE, backup_name)
            logger.info(f"Renamed corrupted state file to {backup_name}")
        except Exception as rename_err:
            logger.error(f"Failed to rename corrupted state file: {rename_err}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error loading state: {e}")
        return None


def save_state(content_hash: str, test_dates: List[str], last_modified: Optional[str] = None) -> None:
    logger.info("Attempting to execute save_state function...")
    state = {
        "content_hash": content_hash,
        "test_date_count": len(test_dates),
        "test_dates": test_dates
    }
    logger.info(f"Saving state with content hash: {content_hash}")

    try:
        temp_file = f"{STATE_FILE}.tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, STATE_FILE)
        logger.info(f"Successfully saved state to {STATE_FILE} via os.replace")
    except Exception as e:
        logger.error(f"Error saving state in save_state function: {e}")


def extract_test_dates(html_content: str) -> List[str]:
    """Extract the current test dates from the table using BeautifulSoup"""
    if not html_content:
        return []

    try:
        # Parse HTML with BeautifulSoup
        soup = BeautifulSoup(html_content, 'html.parser')

        # Find the table with the specific class
        table = soup.find('table', class_='cb-table cb-no-margin-top')

        if not table:
            # Try alternative selectors if the table class changed
            tables = soup.find_all('table')
            if tables:
                logger.warning("Could not find table with expected class, trying alternative tables")
                # Try to find a table that looks like it contains test dates
                for potential_table in tables:
                    if potential_table.find('th') and "date" in potential_table.text.lower():
                        table = potential_table
                        break

        if not table:
            logger.warning("Could not find any table that might contain SAT dates")
            return []

        # Find all rows in the table
        rows = table.find_all('tr')

        # Extract dates from the first column, excluding the header row
        test_dates: List[str] = []
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


def send_discord_notification(
        test_dates: List[str],
        page_changed: bool = False,
        content_hash: Optional[str] = None,
        prev_hash: Optional[str] = None
) -> bool:
    """Send notification to Discord webhook"""
    if not DISCORD_WEBHOOK_URL:
        logger.warning("Discord webhook URL not configured, skipping Discord notification")
        return False

    notification_reason = []
    if len(test_dates) > DATE_THRESHOLD:
        notification_reason.append(
            f"Found {len(test_dates)} SAT test dates, which exceeds the threshold of {DATE_THRESHOLD}")
    if page_changed:
        notification_reason.append("The SAT dates page content has changed")

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
                        "value": "\n".join([f"• {date}" for date in test_dates]) or "No dates found",
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

        # Add hash information if available
        if content_hash:
            message["embeds"][0]["fields"].append({
                "name": "Current Content Hash",
                "value": f"`{content_hash[:10]}...`",
                "inline": False
            })

        if prev_hash and page_changed:
            message["embeds"][0]["fields"].append({
                "name": "Previous Content Hash",
                "value": f"`{prev_hash[:10]}...`",
                "inline": False
            })

        # Add URL field
        message["embeds"][0]["fields"].append({
            "name": "URL",
            "value": URL,
            "inline": False
        })

        # Send notification with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.post(
                    DISCORD_WEBHOOK_URL,
                    json=message,
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )
                response.raise_for_status()
                logger.info(f"Discord notification sent successfully (status code {response.status_code})")
                return True
            except requests.RequestException as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Discord notification attempt {attempt + 1} failed: {e}. Retrying...")
                    time.sleep(2)  # Wait before retry
                else:
                    logger.error(f"All Discord notification attempts failed: {e}")
                    return False
    except Exception as e:
        logger.error(f"Error sending Discord notification: {e}")
        return False


def send_telegram_notification(
        test_dates: List[str],
        page_changed: bool = False,
        content_hash: Optional[str] = None,
        prev_hash: Optional[str] = None
) -> bool:
    """Send notification to Telegram channel"""
    if not TELEGRAM_BOT_TOKEN:
        logger.warning("Telegram bot token not configured, skipping Telegram notification")
        return False

    notification_reason = []
    if len(test_dates) > DATE_THRESHOLD:
        notification_reason.append(
            f"Found {len(test_dates)} SAT test dates, which exceeds the threshold of {DATE_THRESHOLD}")
    if page_changed:
        notification_reason.append("The SAT dates page content has changed")

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
        if test_dates:
            for date in test_dates:
                message_text += f"• {date}\n"
        else:
            message_text += "No dates found\n"

        # Add check time
        message_text += f"\n*Check Time:* {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"

        # Add hash information if available
        if content_hash:
            message_text += f"*Current Content Hash:* `{content_hash[:10]}...`\n"

        if prev_hash and page_changed:
            message_text += f"*Previous Content Hash:* `{prev_hash[:10]}...`\n"

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

        # Send notification with retry logic
        max_retries = 3
        for attempt in range(max_retries):
            try:
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
                    error_msg = response_json.get('description', 'Unknown error')
                    logger.error(f"Telegram API error: {error_msg}")

                    # Don't retry if it's a permanent error like invalid token
                    if "unauthorized" in error_msg.lower() or "not found" in error_msg.lower():
                        return False

                    if attempt < max_retries - 1:
                        logger.warning(f"Retrying Telegram notification...")
                        time.sleep(2)  # Wait before retry
                    else:
                        return False
            except requests.RequestException as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Telegram notification attempt {attempt + 1} failed: {e}. Retrying...")
                    time.sleep(2)  # Wait before retry
                else:
                    logger.error(f"All Telegram notification attempts failed: {e}")
                    return False

    except Exception as e:
        logger.error(f"Error sending Telegram notification: {e}")
        return False

    return False  # Should not reach here


def main() -> None:
    """Main function"""
    logger.info(f"Starting SAT Test Dates monitoring (version 1.2.0)")
    logger.info(f"Running in GitHub Actions: {os.environ.get('GITHUB_ACTIONS', 'No')}")

    # Fetch the page
    page_data = fetch_page()

    if not page_data:
        logger.error("Failed to fetch the page, exiting")
        return

    html_content = page_data['content']
    content_hash = page_data['content_hash']

    # Extract test dates
    test_dates = extract_test_dates(html_content)

    if not test_dates:
        logger.warning("No test dates extracted from the page")
        # Continue execution to check if the page changed

    # Load previous state
    prev_state = load_state()

    # Determine if we need to send notifications
    should_notify = False
    page_changed = False
    prev_hash = None

    # Check if we have previous state
    if prev_state:
        # Check if the page has changed since last time based on content hash
        prev_hash_value = prev_state.get("content_hash")
        prev_dates = prev_state.get("test_dates", [])

        if content_hash != prev_hash_value:
            page_changed = True
            prev_hash = prev_hash_value
            should_notify = True
            logger.info(f"Page content has changed (hash mismatch)")
            logger.info(f"Previous hash: {prev_hash_value}")
            logger.info(f"Current hash: {content_hash}")
        elif set(test_dates) != set(prev_dates):
            # This shouldn't normally happen if hash detection is working properly
            page_changed = True
            should_notify = True
            logger.warning(f"Test dates have changed even though content hash didn't change")
        else:
            logger.info("Page content and test dates have not changed since last check")
    else:
        # No previous state, this is the first run
        logger.info("First run, no previous state to compare")
        # Don't notify on first run, just establish a baseline
        should_notify = False

    # Check if the number of test dates exceeds the threshold
    if len(test_dates) > DATE_THRESHOLD:
        should_notify = True
        logger.info(f"Found {len(test_dates)} test dates, which exceeds the threshold of {DATE_THRESHOLD}")

    # Send notifications if needed
    if should_notify:
        discord_result = send_discord_notification(test_dates, page_changed, content_hash, prev_hash)
        telegram_result = send_telegram_notification(test_dates, page_changed, content_hash, prev_hash)

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
    save_state(content_hash, test_dates)

    logger.info("Monitoring completed successfully")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.critical(f"Unhandled exception in main function: {e}", exc_info=True)
        # Exit with error code for GitHub Actions to mark the step as failed
        exit(1)