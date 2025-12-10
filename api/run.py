import uvicorn
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger("uvicorn")
logger.info("Starting FastAPI application")

# Load environment variables
load_dotenv()

if __name__ == "__main__":
    # Configure uvicorn logging
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["access"]["fmt"] = "%(asctime)s - %(levelname)s - %(client_addr)s - %(request_line)s - %(status_code)s"
    log_config["loggers"]["uvicorn.access"]["level"] = "DEBUG"
    log_config["loggers"]["uvicorn.error"]["level"] = "DEBUG"
    
    logger.info("Running uvicorn server on port 8080")
    uvicorn.run(
        "app.main:app", 
        host="0.0.0.0", 
        port=8080, 
        reload=True,
        log_config=log_config,
        log_level="debug",
        access_log=True,
        timeout_keep_alive=0  # Disable keep-alive completely
    )