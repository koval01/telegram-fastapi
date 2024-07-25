import os
import asyncio

from dotenv import load_dotenv

from pyrogram import Client

load_dotenv(".env.example")

client = Client(
        "account",
        os.getenv("API_ID"),
        os.getenv("API_HASH"),
        in_memory=True
)


def append_to_file_if_not_exists(key: str, value: str, file_path: str = ".env.local") -> None:
    with open(".env.example", 'r') as _example_env:
        example_env = _example_env.read()

    try:
        # Check if file exists and read its content
        with open(file_path, 'r') as file:
            lines = file.readlines()
            for line in lines:
                if line.startswith(f'{key}='):
                    print(f'{key} already exists in the file.')
                    ask_overwrite = input("Overwrite (type any for continue): ")
                    if not ask_overwrite:
                        print("You refused to overwrite")
                        return
    except FileNotFoundError:
        print("file not found")

    # Append the key-value pair to the file
    with open(file_path, 'w') as file:
        file.write(f'{example_env}{key}="{value}"\n')


async def main():
    async with client:
        session_key = await client.export_session_string()
        if not session_key:
            raise Exception("session_key export error")
        append_to_file_if_not_exists('SESSION', session_key)
        exit("done")


asyncio.run(main())
