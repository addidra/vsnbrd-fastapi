from fastapi import FastAPI, Query, Response
import requests
from dotenv import load_dotenv
import os

load_dotenv()

TELE_FILE_URL = os.getenv("TELE_FILE_URL")

app = FastAPI()

@app.get("/")
async def root():
    return {"message": TELE_FILE_URL}

@app.get('/getImage')
def getImage(file_path: str = Query(...)):
    try:
        # en_file_path = parse.urlencode(file_path)
        url = f'{TELE_FILE_URL}{file_path}'
        response = requests.get(url)
        return Response(content=response.content, media_type='image/png')
    except Exception as e:
        return e