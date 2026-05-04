"""SEC-001 stage 3a — symmetric crypto for settings.value.

Stored format:  v1:<base64(openssl_blob)>:<base64(hmac_blob)>

AES-256-CBC via openssl shell-out (PBKDF2, 100k iter, random salt).
HMAC-SHA256 via stdlib over the raw openssl blob (encrypt-then-MAC).
HMAC key is derived from the master key with a distinct purpose-string
so the MAC key is independent of any AES key material openssl derives.

stdlib only: subprocess, base64, hmac, hashlib.
"""

import base64
import hashlib
import hmac
import subprocess

_VERSION_PREFIX = "v1:"
_HMAC_PURPOSE = b"burnctl-hmac-v1"
_HMAC_ITER = 100_000
_HMAC_KEY_LEN = 32


def _hmac_key(master_key_hex: str) -> bytes:
    return hashlib.pbkdf2_hmac(
        "sha256",
        master_key_hex.encode("utf-8"),
        _HMAC_PURPOSE,
        _HMAC_ITER,
        _HMAC_KEY_LEN,
    )


def encrypt(plaintext: str, master_key_hex: str) -> str:
    proc = subprocess.run(
        [
            "openssl", "enc", "-e", "-aes-256-cbc",
            "-pbkdf2", "-iter", "100000", "-salt",
            "-k", master_key_hex,
        ],
        input=plaintext.encode("utf-8"),
        capture_output=True,
        check=True,
    )
    blob = proc.stdout
    mac = hmac.new(_hmac_key(master_key_hex), blob, hashlib.sha256).digest()
    return (
        _VERSION_PREFIX
        + base64.b64encode(blob).decode("ascii")
        + ":"
        + base64.b64encode(mac).decode("ascii")
    )


def decrypt(ciphertext: str, master_key_hex: str) -> str:
    if not ciphertext.startswith(_VERSION_PREFIX):
        raise ValueError("unsupported ciphertext format")
    body = ciphertext[len(_VERSION_PREFIX):]
    parts = body.split(":")
    if len(parts) != 2:
        raise ValueError("malformed v1 ciphertext")
    try:
        blob = base64.b64decode(parts[0], validate=True)
        mac = base64.b64decode(parts[1], validate=True)
    except (ValueError, base64.binascii.Error) as e:
        raise ValueError("malformed v1 ciphertext") from e

    expected = hmac.new(_hmac_key(master_key_hex), blob, hashlib.sha256).digest()
    if not hmac.compare_digest(mac, expected):
        raise ValueError("HMAC verification failed")

    proc = subprocess.run(
        [
            "openssl", "enc", "-d", "-aes-256-cbc",
            "-pbkdf2", "-iter", "100000",
            "-k", master_key_hex,
        ],
        input=blob,
        capture_output=True,
        check=True,
    )
    return proc.stdout.decode("utf-8")
