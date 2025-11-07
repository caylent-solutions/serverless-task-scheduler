# Initialize app package
import logging

from dotenv import load_dotenv

class CustomFormatter(logging.Formatter):

    grey = "\x1b[38;20m"    
    red = "\x1b[31;20m"
    green = "\x1b[32;20m"
    yellow = "\x1b[33;20m"
    blue = "\x1b[34;20m"
    magenta = "\x1b[35;20m"
    cyan = "\x1b[36;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: blue + format + reset,
        logging.INFO: green + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)
    
# Configure root logger with custom handler only
root_logger = logging.getLogger()
root_logger.setLevel(logging.INFO)

# Remove any existing handlers
for handler in root_logger.handlers[:]:
    root_logger.removeHandler(handler)

# Add only our custom handler
ch = logging.StreamHandler()
ch.setFormatter(CustomFormatter())
root_logger.addHandler(ch)

# Configure module loggers
logger = logging.getLogger(__name__)
logging.getLogger("botocore").setLevel(logging.INFO)
logging.getLogger("boto3").setLevel(logging.INFO)
logger.debug("App package initialized")

load_dotenv(verbose=True)