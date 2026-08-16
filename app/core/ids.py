"""ฅ^•ﻌ•^ฅ"""

import uuid

# Base62 character set: 0-9, a-z, A-Z (URL-safe, lexicographically clean)
_BASE62_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_BASE62_LOOKUP = {c: i for i, c in enumerate(_BASE62_CHARS)}
_BASE62_RADIX = 62


def uuid_to_typed_id(u: str | uuid.UUID, prefix: str | None = None) -> str:
    """
    Encode a 128-bit UUID to a Base62 string, optionally prefixed.
    Preserves exact 128-bit precision (zero loss).
    """
    if isinstance(u, str):
        parsed = uuid.UUID(u)
    else:
        parsed = u

    # 128-bit integer
    num = parsed.int
    if num == 0:
        encoded = _BASE62_CHARS[0]
    else:
        digits = []
        while num > 0:
            num, rem = divmod(num, _BASE62_RADIX)
            digits.append(_BASE62_CHARS[rem])
        encoded = "".join(reversed(digits))

    # Pad to fixed length 22 (62^22 > 2^128 > 62^21) for uniform length
    encoded = encoded.zfill(22)

    if prefix:
        return f"{prefix}_{encoded}"
    return encoded


def typed_id_to_uuid(val: str) -> str:
    """
    Decode a Base62 / Typed ID or passthrough a canonical UUID.
    Returns canonical UUID string (8-4-4-4-12).
    If val is not a valid 22-char Base62 or typed string, passthrough as-is.
    """
    if not val:
        return val

    # Passthrough standard 36-char UUID string
    if len(val) == 36 and "-" in val:
        try:
            return str(uuid.UUID(val))
        except ValueError:
            return val

    # If it's a typed ID or 22-char base62
    if "_" in val or len(val) == 22:
        raw = val.split("_", 1)[-1]
        if len(raw) == 22 and all(c in _BASE62_LOOKUP for c in raw):
            num = 0
            for char in raw:
                num = num * _BASE62_RADIX + _BASE62_LOOKUP[char]
            return str(uuid.UUID(int=num))

    # Try standard UUID parsing, fallback to original val (supports legacy/mock string IDs in tests)
    try:
        return str(uuid.UUID(val))
    except ValueError:
        return val
