import aiohttp
import asyncio
import logging

class TelegramFilePathFetcher:
    def __init__(self, bot_token,user_id):
        self.url = f"https://api.telegram.org/bot{bot_token}/"
        self.file_id_array = []
        self.user_id = user_id

    async def fetch_json(self, endpoint):
        """Helper function to fetch JSON data from a Telegram API endpoint."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url + endpoint) as response:
                    if response.status != 200:
                        raise Exception(f"Response status: {response.status}")
                    return await response.json()
        except Exception as error:
            print(f"Error fetching {endpoint}: {error}")
            return {}

    async def get_updates(self):
        """Fetch updates from Telegram and extract messages."""
        json_data = await self.fetch_json("getUpdates")
        results = json_data.get("result",[])
        user_data = []
        for update in results:
            message = update.get("message")
            if message and str(message.get("from",{}).get("id")) == self.user_id:
                sender_id = message.get("from", {}).get("id")
                # logging.info(f"{sender_id} == {self.user_id}")
                user_data.append(update)
        return user_data

    async def get_file_ids(self, result):
        """Extract unique file IDs from messages."""
        try:
            new_file_ids = {
                item["message"]["photo"][-1]["file_id"]
                for item in result if "message" in item and "photo" in item["message"]
            }
            self.file_id_array.extend(new_file_ids - set(self.file_id_array))
        except Exception as error:
            print(f"Error in get_file_ids function: {error}")

    async def get_file_paths(self):
        """Fetch file paths for collected file IDs concurrently."""
        try:
            tasks = [
                self.fetch_json(f"getFile?file_id={file_id}")
                for file_id in self.file_id_array
            ]
            responses = await asyncio.gather(*tasks)
            return {
                r.get("result", {}).get("file_path", "")
                for r in responses if r.get("result")
            }
        except Exception as error:
            print(f"Error in get_file_paths function: {error}")
            return set()

    async def process(self):
        """Execute the full image fetching process."""
        try:
            result = await self.get_updates()
            await self.get_file_ids(result)
            return await self.get_file_paths()
        except Exception as error:
            print(f"Error fetching images: {error}")
            return set()

# Example usage
# if __name__ == "__main__":
#     fetcher = TelegramFilePathFetcher(bot_token)
#     file_paths = asyncio.run(fetcher.process())
#     print("Fetched File Paths:", file_paths)
