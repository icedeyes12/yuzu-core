"""ฅ^•ﻌ•^ฅ"""

import uuid

from app.core.ids import EntityType, PublicId, typed_id_to_uuid, uuid_to_typed_id


def test_sandbox_public_id_round_trip_preserves_uuidv7():
    raw = "019d0000-0000-7000-8000-000000000001"

    public_id = PublicId.encode(EntityType.SANDBOX, raw)

    assert public_id.startswith("sbx_")
    assert PublicId.decode(EntityType.SANDBOX, public_id, allow_raw_uuid=False) == raw


def test_uuid_base62_roundtrip_precision():
    """Verify that 10,000 random and boundary UUIDs round-trip with zero bit loss."""
    # 1. Boundary cases
    boundary_uuids = [
        uuid.UUID(int=0),  # 00000000-0000-0000-0000-000000000000
        uuid.UUID(int=(1 << 128) - 1),  # ffffffff-ffff-ffff-ffff-ffffffffffff
        uuid.UUID(int=1),
        uuid.UUID(int=(1 << 127)),
    ]

    for u in boundary_uuids:
        raw_uuid = str(u)
        typed = uuid_to_typed_id(raw_uuid, prefix="ses")
        assert typed.startswith("ses_")
        assert len(typed) == 4 + 22  # "ses_" + 22 chars

        decoded = typed_id_to_uuid(typed)
        assert decoded == raw_uuid, f"Failed for boundary: {raw_uuid}"

    # 2. 10,000 random UUIDs
    for _ in range(10000):
        orig_uuid = str(uuid.uuid4())
        encoded = uuid_to_typed_id(orig_uuid, prefix="usr")
        decoded = typed_id_to_uuid(encoded)
        assert decoded == orig_uuid, f"Mismatch: {orig_uuid} != {decoded}"

    # 3. Standard UUID passthrough tolerance
    raw_uuid_input = "019fab6c-04a9-7731-91e3-e8543fe04363"
    assert typed_id_to_uuid(raw_uuid_input) == raw_uuid_input

    # 4. Typed ID with session prefix
    typed_session = uuid_to_typed_id(raw_uuid_input, prefix="ses")
    assert typed_id_to_uuid(typed_session) == raw_uuid_input
