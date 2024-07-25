import os
import json
from time import time
from datetime import datetime
from enum import Enum
from typing import Union

import asyncstdlib as a

from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse, JSONResponse, Response

from pyrogram import Client, utils
from pyrogram.errors.exceptions import UsernameNotOccupied
from pyrogram.enums import ChatType
from pyrogram.types import Object

from cryptography.fernet import Fernet
from cryptography.fernet import InvalidToken

from dotenv import load_dotenv

import jsonpickle

load_dotenv(".env.local")

client = Client(
    "account",
    os.getenv("API_ID"),
    os.getenv("API_HASH"),
    in_memory=True,
    session_string=os.getenv("SESSION")
)

app = FastAPI()


class Cryptography:

    def __init__(self) -> None:
        key: bytes = os.getenv("CRYPT_KEY").encode()
        self.fernet = Fernet(key)

    def encrypt(self, _input: str) -> str:
        return self.fernet.encrypt(_input.encode()).decode().replace("=", "")

    def encrypt_json(self, _input: dict) -> str:
        _input = {**_input, "timestamp": int(time() + 3600)}
        return self.encrypt(json.dumps(_input))

    def decrypt(self, _input: str) -> str:
        return self.fernet.decrypt(_input.encode() + b'=' * (-len(_input) % 4)).decode()

    def decrypt_json(self, _input: str) -> dict:
        return json.loads(self.decrypt(_input))


class PyrogramResponse:

    @staticmethod
    def file_id_(file_id: str, mime_type: str = "") -> str:
        data = Cryptography().encrypt_json({
            "file_id": file_id,
            "mime_type": mime_type
        })
        return f"{os.getenv('APP_DOMAIN')}/media/{data}"

    @classmethod
    def process_file_ids(cls, data: Union[dict, list]) -> Union[dict, list]:
        def process_dict(_dict: dict) -> dict:
            new_dict = {}
            for key, value in _dict.items():
                if key == "file_id" or key.endswith("_file_id"):
                    new_key = key.replace("_file_id", "_file_url") if key.endswith("_file_id") else "file_url"
                    mime_key = key.replace("_file_id", "_mime_type") if key.endswith("_file_id") else "mime_type"
                    mime = _dict.get(mime_key, None)

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
        """Recursively replace all Enum types with their string names in a Pyrogram object."""
        if hasattr(obj, '__dict__'):
            for attr in obj.__dict__:
                if not attr.startswith("_"):
                    attr_value = getattr(obj, attr)
                    if isinstance(attr_value, Enum):
                        setattr(obj, attr, attr_value.name.lower())
                    else:
                        setattr(obj, attr, cls.replace_enum_types_with_names(attr_value))
            return obj
        elif isinstance(obj, list):
            return [cls.replace_enum_types_with_names(item) for item in obj]
        else:
            return obj

    @classmethod
    def build(cls, _input: Object) -> Union[dict, list]:
        return cls.process_file_ids(
            jsonpickle.decode(
                str(cls.replace_enum_types_with_names(_input))
            )
        )


@app.get("/")
def read_root() -> RedirectResponse:
    return RedirectResponse("/docs")


@app.get("/channel/{username}")
async def get_channel(username: str) -> JSONResponse:
    async with client:
        try:
            resp = await client.get_chat(username)
        except UsernameNotOccupied:
            raise HTTPException(status_code=404, detail="This username does not exist")
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
    messages = []
    async with client:
        try:
            resp = client.get_chat_history(
                username, limit=20, offset=offset, offset_id=offset_id, offset_date=offset_date)
        except UsernameNotOccupied:
            raise HTTPException(status_code=404, detail="This username does not exist")
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
    try:
        data = Cryptography().decrypt_json(media)
    except InvalidToken:
        raise HTTPException(status_code=400, detail="Invalid media token")
    if data["timestamp"] < int(time()):
        raise HTTPException(status_code=400, detail="Invalid media token")

    async with client:
        file = await client.download_media(data["file_id"], in_memory=True)
        if not file:
            raise HTTPException(status_code=404, detail="File not found")
        image_bytes = bytes(file.getbuffer())
        return Response(content=image_bytes, media_type=data.get("mime_type", "image/png"))


@app.get(
    "/healthz",
    tags=["healthcheck"],
    summary="Perform a Health Check",
    response_description="Return HTTP Status Code 200 (OK)",
)
async def get_health() -> Response:
    """
    ## Perform a Health Check
    Endpoint to perform a healthcheck on. This endpoint can primarily be used Docker
    to ensure a robust container orchestration and management is in place. Other
    services which rely on proper functioning of the API service will not deploy if this
    endpoint returns any other HTTP status code except 200 (OK).
    Returns:
        Response: Returns a empty page with 200 (OK) or 500
    """
    async with client:
        await client.get_me()
        return Response(None, status_code=200)
