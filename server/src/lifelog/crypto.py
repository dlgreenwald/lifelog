import base64
import os
import uuid

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class AudioEncryption:
    """Encrypt/decrypt audio files with per-user keys."""

    def __init__(self):
        self.storage_path = settings.audio_storage_path
        os.makedirs(self.storage_path, exist_ok=True)

    def derive_key(self, user_id: int, user_secret: str) -> bytes:
        """Derive encryption key from user ID and secret."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=f"lifelog-{user_id}".encode(),
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(user_secret.encode()))
        return key

    def encrypt_audio(
        self, audio_bytes: bytes, user_id: int, user_secret: str
    ) -> str:
        """Encrypt audio file and save to disk. Returns encrypted filename."""
        key = self.derive_key(user_id, user_secret)
        fernet = Fernet(key)

        encrypted_data = fernet.encrypt(audio_bytes)

        filename = f"{uuid.uuid4()}.enc"
        filepath = os.path.join(self.storage_path, filename)

        with open(filepath, "wb") as f:
            f.write(encrypted_data)

        return filename

    def decrypt_audio(
        self, filename: str, user_id: int, user_secret: str
    ) -> bytes:
        """Decrypt audio file from disk."""
        key = self.derive_key(user_id, user_secret)
        fernet = Fernet(key)

        filepath = os.path.join(self.storage_path, filename)
        with open(filepath, "rb") as f:
            encrypted_data = f.read()

        return fernet.decrypt(encrypted_data)


from lifelog.config import settings

audio_crypto = AudioEncryption()
