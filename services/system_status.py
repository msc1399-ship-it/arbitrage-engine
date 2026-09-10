import os
from dotenv import load_dotenv


def connector_statuses():
    load_dotenv()
    bricklink = all(os.getenv(key, "").strip() for key in (
        "BRICKLINK_CONSUMER_KEY", "BRICKLINK_CONSUMER_SECRET", "BRICKLINK_TOKEN", "BRICKLINK_TOKEN_SECRET"))
    ebay = all(os.getenv(key, "").strip() for key in (
        "EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_ENVIRONMENT"))
    ebay = ebay and os.getenv("EBAY_ENVIRONMENT", "").strip().lower() in {"sandbox", "production"}
    return {
        "Rebrickable": "ACTIVE" if os.getenv("REBRICKABLE_API_KEY", "").strip() else "PENDING",
        "BrickLink": "ACTIVE" if bricklink else "PENDING",
        "eBay": "ACTIVE" if ebay else "PENDING",
    }
