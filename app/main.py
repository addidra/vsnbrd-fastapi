from fastapi import FastAPI, Query, Response
import requests
from urllib import parse

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello World"}

@app.get('/getImage')
def getImage(file_path: str = Query(...)):
    try:
        # en_file_path = parse.urlencode(file_path)
        url = f'https://api.telegram.org/file/bot7374565657:AAHltUNRTPeA0DiHoxT_4BCEappAGJ5htHg/{file_path}'
        response = requests.get(url)
        return Response(content=response.content, media_type='image/png')
    except Exception as e:
        return e