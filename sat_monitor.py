#!/usr/bin/env python3
import requests
from bs4 import BeautifulSoup
import json
import logging
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
WEBHOOK_URL = "https://discord.com/api/webhooks/1369168716297666610/MVBIr8xyOJAlBADSlSrQfuVdu7HfkUe4a5rEX_rZMoHedi4suH3eYfWEKoI4XrrMYCN7"  # Replace with your actual Discord webhook URL
DATE_THRESHOLD = 7  # Alert if more than this many dates are found


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
            WEBHOOK_URL,
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
            send_discord_notification(test_dates)
        else:
            logger.info(f"Found {len(test_dates)} test dates, which does not exceed the threshold of {DATE_THRESHOLD}")

    logger.info("Monitoring completed")


if __name__ == "__main__":
    main()