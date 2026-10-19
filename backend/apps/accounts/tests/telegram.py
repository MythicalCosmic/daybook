"""Builds mini app init data signed the way Telegram signs it."""

import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

BOT_TOKEN = "123456:TEST-TOKEN"


def signed_init_data(user_id: int = 42, *, auth_date: int | None = None, token: str = BOT_TOKEN):
    user = {
        "id": user_id,
        "first_name": "Ali",
        "last_name": "Valiyev",
        "username": "ali",
        "language_code": "ru",
    }
    fields = {
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(user, separators=(",", ":")),
        "auth_date": str(auth_date or int(time.time())),
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    fields["hash"] = hmac.new(secret, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(fields)
