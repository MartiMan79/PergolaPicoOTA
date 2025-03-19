import logging
from logging.handlers import RotatingFileHandler

# Create a logger object
logger = logging.getLogger('MQTT')
logger.setLevel(logging.DEBUG)  # Set the logger's level to INFO

# Set up a rotating file handler
file_handler = RotatingFileHandler(
    'debug.log',          # Log file name
    maxBytes=50000,    # Maximum size of a log file in bytes before rotation
    backupCount=3       # Number of backup files to keep
)

# Set up a console handler to output logs to the console
console_handler = logging.StreamHandler()


# Optional: Set a formatter for the log messages
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Add the handler to the logger

logger.addHandler(file_handler)
logger.addHandler(console_handler)