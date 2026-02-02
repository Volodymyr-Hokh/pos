import os
from dotenv import load_dotenv

load_dotenv()

# MongoDB Atlas
MONGODB_URL = os.getenv(
    "MONGODB_URL",
    "mongodb+srv://admin:adminvlad@cluster0.pye1guw.mongodb.net/?appName=Cluster0"
)
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "pos_clover")

# Redis Cloud
REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://default:iI2V3Go228dP5qCJQuC2RdnPxLVlJpSV@redis-11371.c281.us-east-1-2.ec2.cloud.redislabs.com:11371"
)

# Redis Pub/Sub channels
CHANNEL_ORDERS_NEW = "pos:orders:new"
CHANNEL_STATS_UPDATE = "pos:stats:update"
REDIS_CHANNELS = [CHANNEL_ORDERS_NEW, CHANNEL_STATS_UPDATE]

# Restaurant settings
RESTAURANT_NAME = "PoS"
RESTAURANT_ADDRESS = "Івано-Франківськ"
RESTAURANT_PHONE = "+38069696969"
RESTAURANT_HOURS = "08:00 - 21:00"

# Telegram Bot settings
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
