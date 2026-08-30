"""Unit tests for crypto module (encrypt/decrypt roundtrip)."""

import os
import tempfile
from unittest.mock import patch

SALT_A = b"test-salt-aaaaaaaa"
SALT_B = b"test-salt-bbbbbbbbb"


def test_derive_key_deterministic():
    """Same inputs produce the same derived key."""
    from lifelog.crypto import AudioEncryption

    enc = AudioEncryption()
    k1 = enc.derive_key("secret-a", SALT_A)
    k2 = enc.derive_key("secret-a", SALT_A)
    assert k1 == k2


def test_derive_key_different_per_salt():
    """Different salts produce different keys."""
    from lifelog.crypto import AudioEncryption

    enc = AudioEncryption()
    k1 = enc.derive_key("secret-a", SALT_A)
    k2 = enc.derive_key("secret-a", SALT_B)
    assert k1 != k2


def test_derive_key_different_per_secret():
    """Different secrets produce different keys."""
    from lifelog.crypto import AudioEncryption

    enc = AudioEncryption()
    k1 = enc.derive_key("secret-a", SALT_A)
    k2 = enc.derive_key("secret-b", SALT_A)
    assert k1 != k2


def test_encrypt_decrypt_roundtrip():
    """Encrypt then decrypt returns original bytes."""
    from lifelog.crypto import AudioEncryption

    tmpdir = tempfile.mkdtemp()
    with patch("lifelog.crypto.settings") as mock_settings:
        mock_settings.audio_storage_path = tmpdir
        enc = AudioEncryption()

    audio_data = b"fake-opus-audio-data-12345"
    filename = enc.encrypt_audio(audio_data, user_secret="my-secret", salt=SALT_A)

    assert filename.endswith(".enc")
    assert os.path.exists(os.path.join(tmpdir, filename))

    decrypted = enc.decrypt_audio(filename, user_secret="my-secret", salt=SALT_A)
    assert decrypted == audio_data


def test_encrypt_decrypt_wrong_secret_fails():
    """Decrypting with the wrong secret raises an exception."""
    from lifelog.crypto import AudioEncryption

    tmpdir = tempfile.mkdtemp()
    with patch("lifelog.crypto.settings") as mock_settings:
        mock_settings.audio_storage_path = tmpdir
        enc = AudioEncryption()

    audio_data = b"secret-audio"
    filename = enc.encrypt_audio(audio_data, user_secret="correct-secret", salt=SALT_A)

    try:
        enc.decrypt_audio(filename, user_secret="wrong-secret", salt=SALT_A)
        assert False, "Should have raised an exception"
    except Exception:
        pass  # Fernet raises InvalidToken


def test_encrypt_decrypt_wrong_salt_fails():
    """Decrypting with the wrong salt raises an exception."""
    from lifelog.crypto import AudioEncryption

    tmpdir = tempfile.mkdtemp()
    with patch("lifelog.crypto.settings") as mock_settings:
        mock_settings.audio_storage_path = tmpdir
        enc = AudioEncryption()

    audio_data = b"secret-audio"
    filename = enc.encrypt_audio(audio_data, user_secret="my-secret", salt=SALT_A)

    try:
        enc.decrypt_audio(filename, user_secret="my-secret", salt=SALT_B)
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

    f1 = enc.encrypt_audio(b"data1", user_secret="secret", salt=SALT_A)
    f2 = enc.encrypt_audio(b"data2", user_secret="secret", salt=SALT_A)
    assert f1 != f2


def test_decrypt_audio_rejects_path_traversal():
    """Decrypting with path traversal in filename raises ValueError."""
    from lifelog.crypto import AudioEncryption

    tmpdir = tempfile.mkdtemp()
    with patch("lifelog.crypto.settings") as mock_settings:
        mock_settings.audio_storage_path = tmpdir
        enc = AudioEncryption()

    try:
        enc.decrypt_audio("../../../etc/passwd", user_secret="secret", salt=SALT_A)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass


def test_decrypt_audio_rejects_bad_filename():
    """Decrypting with non-UUID filename raises ValueError."""
    from lifelog.crypto import AudioEncryption

    tmpdir = tempfile.mkdtemp()
    with patch("lifelog.crypto.settings") as mock_settings:
        mock_settings.audio_storage_path = tmpdir
        enc = AudioEncryption()

    try:
        enc.decrypt_audio("evil.exe", user_secret="secret", salt=SALT_A)
        assert False, "Should have raised ValueError"
    except ValueError:
        pass
