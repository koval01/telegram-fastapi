"""
Telegram API Gateway

This API provides a simple interface to interact with Telegram.
"""

import logging
import os
import json
from contextlib import asynccontextmanager
from time import time
from datetime import datetime
from enum import Enum
from typing import Union

import asyncstdlib as a

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, StreamingResponse, Response

from pyrogram import Client, utils
from pyrogram.enums import ChatType
from pyrogram.types import Object

from pyrogram.errors.exceptions import UsernameNotOccupied
from pyrogram.errors.exceptions.not_acceptable_406 import ChannelPrivate

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken

from dotenv import load_dotenv

import jsonpickle

logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv(".env.local")

# Initialize the Telegram client
client = Client(
    "account",
    os.getenv("API_ID"),
    os.getenv("API_HASH"),
    in_memory=True,
    session_string=os.getenv("SESSION"),
    device_model=os.uname()[1]
)

# Initialize the FastAPI app
app = FastAPI()
main_app_lifespan = app.router.lifespan_context


@asynccontextmanager
async def lifespan_wrapper(_: FastAPI):
    await client.start()
    async with main_app_lifespan(app) as maybe_state:
        yield maybe_state
    await client.stop()

app.router.lifespan_context = lifespan_wrapper


class Cryptography:
    """
    Provides encryption and decryption utilities using Fernet.
    """

    def __init__(self) -> None:
        """
        Initializes the Cryptography class.

        Loads the encryption key from the environment variable `CRYPT_KEY`.
        """
        key: bytes = os.getenv("CRYPT_KEY").encode()
        self.fernet = Fernet(key)

    def encrypt(self, _input: str) -> str:
        """
        Encrypts the input string using Fernet.

        Args:
            _input: The input string to encrypt.

        Returns:
            The encrypted string.
        """
        return self.fernet.encrypt_at_time(
            _input.encode(), int(time())
        ).decode().replace("=", "")

    def encrypt_json(self, _input: dict) -> str:
        """
        Encrypts the input dictionary using Fernet.

        Adds a timestamp to the input dictionary before encryption.

        Args:
            _input: The input dictionary to encrypt.

        Returns:
            The encrypted string.
        """
        return self.encrypt(json.dumps(_input))

    def decrypt(self, _input: str) -> str:
        """
        Decrypts the input string using Fernet.

        Args:
            _input: The input string to decrypt.

        Returns:
            The decrypted string.
        """
        return self.fernet.decrypt(
            _input.encode() + b'=' * (-len(_input) % 4),
            ttl=3600
        ).decode()

    def decrypt_json(self, _input: str) -> dict:
        """
        Decrypts the input string using Fernet and loads the JSON data.

        Args:
            _input: The input string to decrypt.

        Returns:
            The decrypted JSON data.
        """
        return json.loads(self.decrypt(_input))


class PyrogramResponse:
    """
    Provides utilities for processing Pyrogram responses.
    """

    @staticmethod
    def file_id_(file_id: str, mime_type: str = "") -> str:
        """
        Generates a file URL from the given file ID and mime type.

        Args:
            file_id: The file ID.
            mime_type: The mime type (optional).

        Returns:
            The file URL.
        """
        data = {"file_id": file_id}
        if mime_type:
            data["mime_type"] = mime_type
        data = Cryptography().encrypt_json(data)
        return f"{os.getenv('APP_DOMAIN')}/media/{data}"

    @classmethod
    def process_file_ids(cls, data: Union[dict, list]) -> Union[dict, list]:
        """
        Recursively processes file IDs in the given data.

        Replaces file IDs with file URLs.

        Args:
            data: The data to process.

        Returns:
            The processed data.
        """
        def process_dict(_dict: dict) -> dict:
            new_dict = {}
            for key, value in _dict.items():
                if key == "file_id" or key.endswith("_file_id"):
                    new_key = key.replace("_file_id", "_file_url") if key.endswith("_file_id") else "file_url"
                    mime_key = key.replace("_file_id", "_mime_type") if key.endswith("_file_id") else "mime_type"
                    mime = _dict.get(mime_key, "")

                    if mime:
                        new_dict[new_key] = cls.file_id_(value, mime)
                    else:
                        new_dict[new_key] = cls.file_id_(value)
                new_dict[key] = value
                if isinstance(value, dict):
                    new_dict[key] = process_dict(value)
                elif isinstance(value, list):
                    new_dict[key] = process_list(value)
            # Sort the keys in the dictionary alphabetically
            return dict(sorted(new_dict.items()))

        def process_list(_list: list) -> list:
            new_list = []
            for item in _list:
                if isinstance(item, dict):
                    new_list.append(process_dict(item))
                elif isinstance(item, list):
                    new_list.append(process_list(item))
                else:
                    new_list.append(item)
                return new_list

        if isinstance(data, dict):
            return process_dict(data)
        elif isinstance(data, list):
            return process_list(data)

    @classmethod
    def replace_enum_types_with_names(cls, obj: "Object") -> Union[Object, list]:
        """
        Recursively replaces Enum types with their string names in a Pyrogram object.

        Args:
            obj: The Pyrogram object to process.

        Returns:
            The processed object.
        """
        if hasattr(obj, '__dict__'):
            for attr in obj.__dict__:
                if not attr.startswith("_"):
                    attr_value = getattr(obj, attr)
                    if isinstance(attr_value, Enum):
                        setattr(obj, attr, attr_value.name.title())
                    else:
                        setattr(obj, attr, cls.replace_enum_types_with_names(attr_value))
            return obj
        elif isinstance(obj, list):
            return [cls.replace_enum_types_with_names(item) for item in obj]
        else:
            return obj

    @classmethod
    def build(cls, _input: Object) -> Union[dict, list]:
        """
        Processes the Pyrogram object and returns a JSON-compatible representation.

        Args:
            _input: The Pyrogram object to process.

        Returns:
            The JSON-compatible representation of the object.
        """
        return cls.process_file_ids(
            jsonpickle.decode(
                str(cls.replace_enum_types_with_names(_input))
            )
        )


@app.get("/")
def read_root() -> RedirectResponse:
    """
    Redirects to the API documentation.

    Returns:
        A redirect response to the API documentation.
    """
    return RedirectResponse("/docs")


@app.get("/chat/{username}")
async def get_chat(username: str) -> JSONResponse:
    """
    Retrieves information about a Telegram chat.

    Args:
        username: The username of the chat.

    Returns:
        A JSON response containing the chat information.

    Raises:
        HTTPException: If the chat does not exist or is not a channel or group.
    """
    try:
        resp = await client.get_chat(username)
    except UsernameNotOccupied:
        raise HTTPException(status_code=404, detail="This username does not exist")
    except ChannelPrivate as e:
        raise HTTPException(status_code=403, detail=str(e))
    if resp.type not in (ChatType.CHANNEL, ChatType.GROUP, ChatType.SUPERGROUP,):
        raise HTTPException(status_code=403, detail="This is not channel or group")
    return JSONResponse(
        PyrogramResponse.build(resp)
    )


@app.get("/messages/{username}")
async def get_messages(
        username: str,
        offset: int = 0,
        offset_id: int = 0,
        offset_date: datetime = utils.zero_datetime()
) -> JSONResponse:
    """
    Retrieves messages from a Telegram channel.

    Args:
        username: The username of the channel.
        offset: The offset from which to start retrieving messages (default: 0).
        offset_id: The ID of the message from which to start retrieving messages (default: 0).
        offset_date: The date from which to start retrieving messages (default: Unix epoch).

    Returns:
        A JSON response containing the messages.

    Raises:
        HTTPException: If the channel does not exist or is not a channel.
    """
    messages = []
    try:
        resp = client.get_chat_history(
            username, limit=20, offset=offset, offset_id=offset_id, offset_date=offset_date)
    except UsernameNotOccupied:
        raise HTTPException(status_code=404, detail="This username does not exist")
    except ChannelPrivate as e:
        raise HTTPException(status_code=403, detail=str(e))
    async for i, message in a.enumerate(resp):
        if not i and message.chat.type not in (ChatType.CHANNEL, ChatType.GROUP, ChatType.SUPERGROUP,):
            raise HTTPException(status_code=403, detail="This is not channel or group")
        del message.chat
        messages.append(
            PyrogramResponse.build(message)
        )
    return JSONResponse(messages)


@app.get(
    "/media/{media}",
    responses={
        200: {
            "content": {"image/png": {}}
        }
    },
    response_class=Response
)
async def get_media(media: str) -> Response:
    """
    Retrieves a media file from Telegram.

    Args:
        media: The encrypted media token.

    Returns:
        A response containing the media file.

    Raises:
        HTTPException: If the media token is invalid or has expired.
    """
    # TODO: Need use CDN in production version
    try:
        data = Cryptography().decrypt_json(media)
    except InvalidToken:
        raise HTTPException(status_code=400, detail="Invalid media token")

    return StreamingResponse(
        client.stream_media(data["file_id"]),
        media_type=data.get("mime_type", "image/png"))


@app.get(
    "/healthz",
    tags=["healthcheck"],
    summary="Perform a Health Check",
    response_description="Return HTTP Status Code 200 (OK)",
)
async def get_health() -> Response:
    """
    Performs a health check on the API.

    Returns:
        A response with HTTP status code 200 (OK) if the API is healthy.

    Raises:
        HTTPException: If the API is not healthy.
    """
    await client.get_me()
    return Response(None, status_code=200)
