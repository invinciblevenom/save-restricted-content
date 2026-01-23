import asyncio
from pyrogram import Client
import nest_asyncio

nest_asyncio.apply()

async def main():
    api_id = input("Enter your API ID: ")
    api_hash = input("Enter your API HASH: ")

    async with Client(
        name="session",
        api_id=int(api_id), 
        api_hash=api_hash,
        in_memory=True
    ) as app:
        session = await app.export_session_string()
        print("\nYour Session String:\n")
        print(session)

if __name__ == "__main__":
    asyncio.run(main())main()
