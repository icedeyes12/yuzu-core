"""Canonical Identity Abstraction & Public ID Boundary Module.

Invariants:
1. Internal Layer (DB, Repository, Application Logic): Operates strictly on Canonical UUIDs.
2. External Layer (API URLs, Query Params, JSON Request/Response, Frontend): Uses Typed Public IDs (ses_..., usr_..., mem_...).
3. Bijective 1:1 Mapping: UUID (128-bit) <-> Base62 (22 chars uniform).
4. Entity Prefix Verification: Strict validation prevents cross-entity confusion (e.g. passing usr_ to session endpoint).
"""

import uuid
from enum import StrEnum

from fastapi import HTTPException, status


class EntityType(StrEnum):
    SESSION = "ses"
    USER = "usr"
    MEMORY_NODE = "mem"


_BASE62_CHARS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_BASE62_LOOKUP = {c: i for i, c in enumerate(_BASE62_CHARS)}
_BASE62_RADIX = 62


class PublicId:
    """Canonical Public ID Encoder, Decoder, and Domain Validator."""

    @staticmethod
    def encode(entity: EntityType | str, u: str | uuid.UUID | None) -> str:
        """Encode a canonical 128-bit UUID to a Base62 Public ID string with prefix.

        Zero bit loss. Uniform 22-char Base62 representation.
        """
        if u is None:
            return ""
        if isinstance(u, str):
            if not u.strip():
                return ""
            try:
                parsed = uuid.UUID(u.strip())
            except ValueError:
                # If already an encoded public id matching entity prefix, return as-is
                prefix = entity.value if isinstance(entity, EntityType) else str(entity)
                if u.startswith(f"{prefix}_"):
                    return u
                raise ValueError(f"Invalid UUID string for Public ID encoding: '{u}'")
        else:
            parsed = u

        num = parsed.int
        if num == 0:
            encoded = _BASE62_CHARS[0]
        else:
            digits = []
            while num > 0:
                num, rem = divmod(num, _BASE62_RADIX)
                digits.append(_BASE62_CHARS[rem])
            encoded = "".join(reversed(digits))

        # Pad to uniform fixed length 22 (62^22 > 2^128 > 62^21)
        encoded = encoded.zfill(22)
        prefix = entity.value if isinstance(entity, EntityType) else str(entity)
        return f"{prefix}_{encoded}"

    @staticmethod
    def decode(
        entity: EntityType | str | None,
        val: str | None,
        *,
        allow_raw_uuid: bool = True,
    ) -> str:
        """Decode a Public ID string or Canonical UUID to standard 36-char canonical UUID string.

        Enforces entity prefix matching if entity is specified.
        Rejects malformed Base62 digits or unexpected prefixes.
        """
        if not val or not isinstance(val, str):
            return ""

        val = val.strip()
        expected_prefix = (
            entity.value
            if isinstance(entity, EntityType)
            else (str(entity) if entity else None)
        )

        # 1. Passthrough standard 36-char canonical UUID
        if len(val) == 36 and val.count("-") == 4:
            try:
                return str(uuid.UUID(val))
            except ValueError as err:
                raise ValueError(f"Malformed canonical UUID format: '{val}'") from err

        # 2. Parse typed Public ID (prefix_base62)
        if "_" in val:
            prefix, raw_b62 = val.split("_", 1)
            if expected_prefix and prefix != expected_prefix:
                raise ValueError(
                    f"Entity prefix mismatch: expected '{expected_prefix}_', got '{prefix}_' for ID '{val}'"
                )
        else:
            if expected_prefix:
                # Raw un-prefixed Base62 or non-prefixed ID when prefix was expected
                raw_b62 = val
            else:
                raw_b62 = val

        # 3. Validate Base62 payload characters
        for c in raw_b62:
            if c not in _BASE62_LOOKUP:
                if allow_raw_uuid:
                    try:
                        return str(uuid.UUID(val))
                    except ValueError:
                        pass
                raise ValueError(f"Malformed Base62 characters in Public ID: '{val}'")

        # 4. Decode Base62 integer to 128-bit UUID
        num = 0
        for c in raw_b62:
            num = num * _BASE62_RADIX + _BASE62_LOOKUP[c]

        if num >= (1 << 128):
            raise ValueError(
                f"Public ID overflow: exceeds 128-bit integer space: '{val}'"
            )

        return str(uuid.UUID(int=num))


# Backward compatibility aliases for existing caller sites
def uuid_to_typed_id(u: str | uuid.UUID, prefix: str | None = None) -> str:
    """Deprecated: Use PublicId.encode(entity, u) instead."""
    return PublicId.encode(prefix or EntityType.SESSION, u)


def typed_id_to_uuid(val: str, expected_prefix: str | None = None) -> str:
    """Deprecated: Use PublicId.decode(entity, val) instead."""
    try:
        return PublicId.decode(expected_prefix, val)
    except Exception:
        return val


# FastAPI Transport Dependency Resolvers
def resolve_session_id_boundary(session_id: str | None) -> str:
    """Resolve an incoming session identifier at the HTTP transport boundary.

    Raises HTTP 400 if malformed or wrong entity prefix.
    Returns canonical 36-char UUID string.
    """
    if not session_id:
        return ""
    try:
        return PublicId.decode(EntityType.SESSION, session_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid session identifier: {e}",
        ) from e


def resolve_user_id_boundary(user_id: str | None) -> str:
    """Resolve an incoming user identifier at the HTTP transport boundary.

    Raises HTTP 400 if malformed or wrong entity prefix.
    Returns canonical 36-char UUID string.
    """
    if not user_id:
        return ""
    try:
        return PublicId.decode(EntityType.USER, user_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid user identifier: {e}",
        ) from e


def resolve_memory_id_boundary(memory_id: str | None) -> str:
    """Resolve an incoming memory node identifier at the HTTP transport boundary.

    Raises HTTP 400 if malformed or wrong entity prefix.
    Returns canonical 36-char UUID string.
    """
    if not memory_id:
        return ""
    try:
        return PublicId.decode(EntityType.MEMORY_NODE, memory_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid memory identifier: {e}",
        ) from e
