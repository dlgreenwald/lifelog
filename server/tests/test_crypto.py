"""Unit tests for crypto module (encrypt/decrypt roundtrip)."""
import os
import tempfile
from unittest.mock import patch


def test_derive_key_deterministic():
    """Same inputs produce the same derived key."""
    from lifelog.crypto import AudioEncryption

    enc = AudioEncryption()
    k1 = enc.derive_key(1, "secret-a")
    k2 = enc.derive_key(1, "secret-a")
    assert k1 == k2


def test_derive_key_different_per_user():
    """Different user IDs produce different keys."""
    from lifelog.crypto import AudioEncryption

    enc = AudioEncryption()
    k1 = enc.derive_key(1, "secret-a")
    k2 = enc.derive_key(2, "secret-a")
    assert k1 != k2


def test_derive_key_different_per_secret():
    """Different secrets produce different keys."""
    from lifelog.crypto import AudioEncryption

    enc = AudioEncryption()
    k1 = enc.derive_key(1, "secret-a")
    k2 = enc.derive_key(1, "secret-b")
    assert k1 != k2


def test_encrypt_decrypt_roundtrip():
    """Encrypt then decrypt returns original bytes."""
    from lifelog.crypto import AudioEncryption

    tmpdir = tempfile.mkdtemp()
    with patch("lifelog.crypto.settings") as mock_settings:
        mock_settings.audio_storage_path = tmpdir
        enc = AudioEncryption()

    audio_data = b"fake-opus-audio-data-12345"
    filename = enc.encrypt_audio(audio_data, user_id=42, user_secret="my-secret")

    assert filename.endswith(".enc")
    assert os.path.exists(os.path.join(tmpdir, filename))

    decrypted = enc.decrypt_audio(filename, user_id=42, user_secret="my-secret")
    assert decrypted == audio_data


def test_encrypt_decrypt_wrong_secret_fails():
    """Decrypting with the wrong secret raises an exception."""
    from lifelog.crypto import AudioEncryption

    tmpdir = tempfile.mkdtemp()
    with patch("lifelog.crypto.settings") as mock_settings:
        mock_settings.audio_storage_path = tmpdir
        enc = AudioEncryption()

    audio_data = b"secret-audio"
    filename = enc.encrypt_audio(audio_data, user_id=1, user_secret="correct-secret")

    try:
        enc.decrypt_audio(filename, user_id=1, user_secret="wrong-secret")
        assert False, "Should have raised an exception"
    except Exception:
        pass  # Fernet raises InvalidToken


def test_encrypt_decrypt_wrong_user_id_fails():
    """Decrypting with the wrong user_id raises an exception."""
    from lifelog.crypto import AudioEncryption

    tmpdir = tempfile.mkdtemp()
    with patch("lifelog.crypto.settings") as mock_settings:
        mock_settings.audio_storage_path = tmpdir
        enc = AudioEncryption()

    audio_data = b"secret-audio"
    filename = enc.encrypt_audio(audio_data, user_id=1, user_secret="my-secret")

    try:
        enc.decrypt_audio(filename, user_id=2, user_secret="my-secret")
        assert False, "Should have raised an exception"
    except Exception:
        pass


def test_encrypt_produces_unique_filenames():
    """Each encryption produces a unique filename."""
    from lifelog.crypto import AudioEncryption

    tmpdir = tempfile.mkdtemp()
    with patch("lifelog.crypto.settings") as mock_settings:
        mock_settings.audio_storage_path = tmpdir
        enc = AudioEncryption()

    f1 = enc.encrypt_audio(b"data1", 1, "secret")
    f2 = enc.encrypt_audio(b"data2", 1, "secret")
    assert f1 != f2
