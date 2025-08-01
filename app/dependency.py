from pymongo.mongo_client import MongoClient
from pymongo import AsyncMongoClient
from pymongo.server_api import ServerApi
import os
from dotenv import load_dotenv
load_dotenv()

# MongoDB connection string
uri = os.getenv("MONGO_DB")

# Create a new client and connect to the server
try:
    client = AsyncMongoClient(uri)
    # client = MongoClient(uri, server_api=ServerApi('1'))
    # Configure Database
    db = client.oivsnbrd
    users_collection = db.users
    posts_collection = db.posts
    tags_collection = db.tags
    print("MongoDB connection successful")
except Exception as e:
    print(f"Error connecting to MongoDB: {e}")
    raise e
