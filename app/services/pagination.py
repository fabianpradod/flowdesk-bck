"""Validated keyset cursors bound to the tenant, resource and active filters."""
import base64
import json
from datetime import datetime
from uuid import UUID
from app.utils.exceptions import AppError


def encode_cursor(row, date_key, context):
    data = [context, row[date_key].isoformat(), str(row['id'])]
    return base64.urlsafe_b64encode(json.dumps(data, separators=(',', ':')).encode()).decode()


def decode_cursor(cursor, context):
    try:
        if len(cursor) > 1024:
            raise ValueError()
        value = json.loads(base64.b64decode(cursor, altchars=b'-_', validate=True))
        if not isinstance(value, list) or len(value) != 3 or value[0] != context:
            raise ValueError()
        if not isinstance(value[1], str) or not isinstance(value[2], str):
            raise ValueError()
        timestamp = datetime.fromisoformat(value[1])
        if timestamp.tzinfo is not None:
            raise ValueError()
        return timestamp, UUID(value[2])
    except (ValueError, TypeError, KeyError, OverflowError) as exc:
        raise AppError(422, 'Invalid pagination cursor', 'invalid_cursor') from exc
