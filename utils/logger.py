import logging
import os

# Ensure logs/ directory exists
os.makedirs("logs", exist_ok=True)

# Configure logger
logger = logging.getLogger("mailer")
logger.setLevel(logging.INFO)

# File handler
file_handler = logging.FileHandler("logs/mailer.log")
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)

logger.addHandler(file_handler)
