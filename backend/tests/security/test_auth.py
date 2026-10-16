from app.core.auth import create_access_token, decode_token
from app.core.security import get_password_hash, verify_password
from app.models.user import User


def test_password_hashing():
    password = "supersecretpassword123"
    hashed = get_password_hash(password)
    assert hashed != password
    assert verify_password(password, hashed)
    assert not verify_password("wrongpassword", hashed)


def test_jwt_token_creation_and_decoding():
    user_id = "12345"
    token = create_access_token(user_id)
    payload = decode_token(token)
    assert payload["sub"] == user_id
    assert "exp" in payload


def test_user_permissions():
    user = User(email="test@example.com", role="USER")
    assert user.has_permission("read:incidents")
    assert not user.has_permission("update:incidents")

    admin = User(email="admin@example.com", role="ADMIN")
    assert admin.has_permission("update:incidents")
    assert admin.has_permission("manage:system")
