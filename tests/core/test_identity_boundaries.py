"""Standard Library unittest Suite for Sovereign Identity Architecture & Boundaries.

Validates:
1. Bijective 1:1 Invariant: UUID <-> Public ID (Base62 uniform 22-char).
2. Entity Prefix Enforcement: Rejects cross-entity confusion (e.g. passing usr_ to session boundary).
3. Malformed ID Handling: Rejects corrupt characters, overflow, or broken structures.
4. Persistence Purity: Ensures repository and database layers never receive Public IDs.
"""

import unittest
import uuid

from fastapi import HTTPException

from app.core.ids import (
    EntityType,
    PublicId,
    resolve_session_id_boundary,
)
from app.db.queries import parse_session_row


class TestIdentityBoundaries(unittest.TestCase):
    def test_bijective_128bit_precision(self):
        """Verify 1000 random UUIDs encode and decode back with 0 bit loss."""
        for _ in range(1000):
            original_uuid = uuid.uuid4()
            # Session Entity
            encoded_session = PublicId.encode(EntityType.SESSION, original_uuid)
            self.assertTrue(encoded_session.startswith("ses_"), "Must have ses_ prefix")
            self.assertEqual(
                len(encoded_session), 26, "ses_ (4) + 22 chars Base62 = 26 chars"
            )
            decoded_uuid_str = PublicId.decode(EntityType.SESSION, encoded_session)
            self.assertEqual(
                decoded_uuid_str, str(original_uuid), "Decoded UUID must exactly match"
            )

            # User Entity
            encoded_user = PublicId.encode(EntityType.USER, original_uuid)
            self.assertTrue(encoded_user.startswith("usr_"))
            self.assertEqual(
                PublicId.decode(EntityType.USER, encoded_user), str(original_uuid)
            )

            # Memory Node Entity
            encoded_mem = PublicId.encode(EntityType.MEMORY_NODE, original_uuid)
            self.assertTrue(encoded_mem.startswith("mem_"))
            self.assertEqual(
                PublicId.decode(EntityType.MEMORY_NODE, encoded_mem), str(original_uuid)
            )

    def test_cross_entity_prefix_confusion_rejection(self):
        """Verify passing an ID of one entity type to another entity boundary raises ValueError / HTTPException."""
        test_uuid = uuid.uuid4()
        user_public_id = PublicId.encode(EntityType.USER, test_uuid)
        session_public_id = PublicId.encode(EntityType.SESSION, test_uuid)

        # 1. Decoding user ID with expected EntityType.SESSION must fail
        with self.assertRaises(ValueError):
            PublicId.decode(EntityType.SESSION, user_public_id)

        # 2. Decoding session ID with expected EntityType.USER must fail
        with self.assertRaises(ValueError):
            PublicId.decode(EntityType.USER, session_public_id)

        # 3. Boundary resolvers must raise HTTP 400 Bad Request
        with self.assertRaises(HTTPException) as ctx:
            resolve_session_id_boundary(user_public_id)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Invalid session identifier", ctx.exception.detail)

    def test_malformed_public_id_rejection(self):
        """Verify malformed Base62 characters and invalid structures are rejected."""
        # Invalid characters (e.g. symbols not in Base62 alphabet)
        with self.assertRaises(ValueError):
            PublicId.decode(EntityType.SESSION, "ses_@@@invalid_base62@@@")

        with self.assertRaises(HTTPException) as ctx:
            resolve_session_id_boundary("ses_@@@invalid_base62@@@")
        self.assertEqual(ctx.exception.status_code, 400)

        # Non-hex canonical UUID format
        with self.assertRaises(ValueError):
            PublicId.decode(EntityType.SESSION, "01901d93-37d3-752a-9d34-5c7cb5f0468Z")

    def test_raw_canonical_uuid_passthrough(self):
        """Verify internal tools passing raw canonical 36-char UUIDs are supported seamlessly."""
        raw_uuid = str(uuid.uuid4())
        resolved = PublicId.decode(EntityType.SESSION, raw_uuid)
        self.assertEqual(resolved, raw_uuid)

        resolved_boundary = resolve_session_id_boundary(raw_uuid)
        self.assertEqual(resolved_boundary, raw_uuid)

    def test_repository_session_row_purity(self):
        """Verify parse_session_row in db/queries returns canonical DB structure without public ID mutations."""
        sample_uuid = str(uuid.uuid4())
        row = {
            "id": sample_uuid,
            "name": "General Chat",
            "is_active": True,
            "message_count": 42,
        }
        parsed = parse_session_row(row)
        # The ID must remain the clean canonical UUID
        self.assertEqual(parsed["id"], sample_uuid)
        self.assertFalse(
            parsed["id"].startswith("ses_"),
            "Repository layer must not inject Public ID prefix",
        )


if __name__ == "__main__":
    unittest.main()
