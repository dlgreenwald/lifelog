import base64
import os
import re
import uuid

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


class AudioEncryption:
    """Encrypt/decrypt audio files with per-user keys."""

    def __init__(self):
        self.storage_path = settings.audio_storage_path
        os.makedirs(self.storage_path, exist_ok=True)

    def derive_key(self, user_secret: str, salt: bytes) -> bytes:
        """Derive encryption key from user secret and random salt."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(user_secret.encode()))
        return key

    def encrypt_audio(self, audio_bytes: bytes, user_secret: str, salt: bytes) -> str:
        """Encrypt audio file and save to disk. Returns encrypted filename."""
        key = self.derive_key(user_secret, salt)
        fernet = Fernet(key)

        encrypted_data = fernet.encrypt(audio_bytes)

        filename = f"{uuid.uuid4()}.enc"
        filepath = os.path.join(self.storage_path, filename)

        with open(filepath, "wb") as f:
            f.write(encrypted_data)

        return filename

    def decrypt_audio(self, filename: str, user_secret: str, salt: bytes) -> bytes:
        """Decrypt audio file from disk."""
        # Prevent path traversal: basename + strict format check
        safe_name = os.path.basename(filename)
        if not re.match(r"^[a-f0-9\-]{36}\.enc$", safe_name):
            raise ValueError(f"Invalid filename: {filename}")

        key = self.derive_key(user_secret, salt)
        fernet = Fernet(key)

        filepath = os.path.join(self.storage_path, safe_name)
        real_storage = os.path.realpath(self.storage_path)
        real_filepath = os.path.realpath(filepath)
        if (
            not real_filepath.startswith(real_storage + os.sep)
            and real_filepath != real_storage
        ):
            raise ValueError(f"Path traversal attempt: {filename}")

        # CodeQL [py/path-injection]: filepath is validated by realpath guard above
        with open(filepath, "rb") as f:
            encrypted_data = f.read()

        return fernet.decrypt(encrypted_data)


from lifelog.config import settings

audio_crypto = AudioEncryption()
