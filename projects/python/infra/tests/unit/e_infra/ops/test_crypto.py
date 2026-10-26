"""e_infra.ops.crypto: password hashing, JWS/JWE tokens, signatures, AEAD, keyed identifiers, bearer tokens — one secret, many derived keys."""

from datetime import timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import x25519
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from joserfc import jwe
from joserfc.jwk import OctKey

from e_infra.infra.settings import Secret
from e_infra.infra.settings.crypto import CryptoSettings
from e_infra.ops import crypto as crypto_module
from e_infra.ops.crypto import (
    ENC_KEY_SIZES,
    JWE_INFO,
    Crypto,
    CryptoError,
    PasswordHasher,
    TokenAlg,
    TokenEnc,
    TokenError,
    TokenFailure,
)


##### ERROR HIERARCHY #####
def test_error_hierarchy() -> None:
    assert issubclass(TokenError, CryptoError)
    assert issubclass(CryptoError, Exception)


def test_token_failure_values() -> None:
    assert {tf.value for tf in TokenFailure} == {
        "malformed",
        "expired",
        "forged",
        "invalid_claim",
        "empty_jwe",
        "missing_field",
    }


def test_engine_without_root_refuses() -> None:
    with pytest.raises(CryptoError, match="needs a secret"):
        Crypto(CryptoSettings(secret=None))


SECRET = Secret("d0vn0t-r3ad-me-entropy-entropy-entropy")


##### FIXTURES #####
def engine(**overrides: Any) -> Crypto:
    overrides.setdefault("secret", SECRET)
    return Crypto(CryptoSettings(**overrides))


@pytest.fixture
def crypto() -> Crypto:
    return engine()


@pytest.fixture
def ed_crypto() -> Crypto:
    return Crypto(Crypto.generate_keys(TokenAlg.EDDSA))


##### PASSWORDS #####
async def test_hash_password_argon2_roundtrip(crypto: Crypto) -> None:
    hashed = await crypto.hash_password("correct horse")
    assert hashed.startswith("$argon2id$")
    assert await crypto.verify_password("correct horse", hashed)
    assert not await crypto.verify_password("wrong horse", hashed)


async def test_hash_password_bcrypt_roundtrip() -> None:
    crypto = engine(hasher=PasswordHasher.BCRYPT)
    hashed = await crypto.hash_password("correct horse")
    assert hashed.startswith("$2b$")
    assert await crypto.verify_password("correct horse", hashed)
    assert not await crypto.verify_password("wrong horse", hashed)


async def test_hash_password_bcrypt_too_long() -> None:
    crypto = engine(hasher=PasswordHasher.BCRYPT)
    with pytest.raises(CryptoError):
        await crypto.hash_password("x" * 73)


async def test_verify_password_cross_backend(crypto: Crypto) -> None:
    legacy = await engine(hasher=PasswordHasher.BCRYPT).hash_password("migrate me")
    assert await crypto.verify_password("migrate me", legacy)


async def test_verify_password_unknown_hash_raises(crypto: Crypto) -> None:
    with pytest.raises(CryptoError):
        await crypto.verify_password("pw", "$sha512$c2xvcHk=")


async def test_needs_rehash(crypto: Crypto) -> None:
    assert not crypto.needs_rehash(await crypto.hash_password("pw"))
    cheap = engine(hasher=PasswordHasher.BCRYPT, bcrypt_rounds=10)
    assert crypto.needs_rehash(await cheap.hash_password("pw"))


def test_needs_rehash_unknown_raises(crypto: Crypto) -> None:
    with pytest.raises(CryptoError):
        crypto.needs_rehash("plaintext?")


##### TOKENS #####
def test_create_token_jws_roundtrip(crypto: Crypto) -> None:
    token = crypto.create_token({"sub": "u1"}, expires_in=timedelta(minutes=5))
    claims = crypto.verify_token(token)
    assert claims["sub"] == "u1"
    assert isinstance(claims["exp"], int)


def test_create_token_jwe_roundtrip(crypto: Crypto) -> None:
    token = crypto.create_token({"sub": "u1"}, expires_in=timedelta(minutes=5), encrypted=True)
    assert token.count(".") == 4
    assert crypto.verify_token(token)["sub"] == "u1"


def test_create_token_encrypted(crypto: Crypto) -> None:
    crypto = engine(enc=TokenEnc.A128GCM)
    assert crypto.verify_token(crypto.create_token({"sub": "u"}, expires_in=timedelta(60), encrypted=True))


def test_create_token_jwe_asymmetric_roundtrip(ed_crypto: Crypto) -> None:
    token = ed_crypto.create_token({"sub": "u"}, expires_in=timedelta(minutes=5), encrypted=True)
    assert ed_crypto.verify_token(token)["sub"] == "u"


def test_create_token_eddsa_roundtrip(ed_crypto: Crypto) -> None:
    token = ed_crypto.create_token({"sub": "u1"}, expires_in=timedelta(minutes=5))
    assert ed_crypto.verify_token(token)["sub"] == "u1"


def test_verify_token_requires_exp(crypto: Crypto) -> None:
    with pytest.raises(TokenError):
        crypto.verify_token(crypto.create_token({"sub": "u1"}))


def test_verify_token_expired(crypto: Crypto) -> None:
    token = crypto.create_token({"sub": "u1"}, expires_in=timedelta(seconds=-10))
    with pytest.raises(TokenError):
        crypto.verify_token(token)


def test_verify_token_tampered(crypto: Crypto) -> None:
    token = crypto.create_token({"sub": "u1"}, expires_in=timedelta(minutes=5))
    head, payload, sig = token.split(".")
    forged = ".".join((head, payload[:-1] + ("A" if payload[-1] != "A" else "B"), sig))
    with pytest.raises(TokenError):
        crypto.verify_token(forged)


def test_verify_token_foreign_signature(crypto: Crypto) -> None:
    other = engine(secret=Secret("a-completely-different-secret-value-here"))
    token = other.create_token({"sub": "u1"}, expires_in=timedelta(minutes=5))
    with pytest.raises(TokenError):
        crypto.verify_token(token)


def test_verify_token_malformed(crypto: Crypto) -> None:
    with pytest.raises(TokenError):
        crypto.verify_token("not.a.token.at.all.really")


def test_verify_token_issuer_audience(crypto: Crypto) -> None:
    token = crypto.create_token({"sub": "u1", "iss": "e-core", "aud": "web"}, expires_in=timedelta(minutes=5))
    assert crypto.verify_token(token, issuer="e-core", audience="web")["iss"] == "e-core"
    with pytest.raises(TokenError):
        crypto.verify_token(token, issuer="other")


def test_verify_token_via_public_jwks(ed_crypto: Crypto) -> None:
    token = ed_crypto.create_token({"sub": "u1"}, expires_in=timedelta(minutes=5))
    listener = Crypto(CryptoSettings(secret=SECRET, alg=TokenAlg.EDDSA), jwks=ed_crypto.public_jwks())
    assert listener.verify_token(token)["sub"] == "u1"


def test_public_jwks_symmetric_raises(crypto: Crypto) -> None:
    with pytest.raises(CryptoError):
        crypto.public_jwks()


##### SIGNATURES #####
def test_sign_hmac_default(crypto: Crypto) -> None:
    signature = crypto.sign(b"payload")
    assert len(signature) == 32
    assert crypto.verify_signature(b"payload", signature)
    assert not crypto.verify_signature(b"payloac", signature)


def test_sign_ed25519(ed_crypto: Crypto) -> None:
    signature = ed_crypto.sign(b"payload")
    assert ed_crypto.verify_signature(b"payload", signature)
    assert not ed_crypto.verify_signature(b"other", signature)


def test_sign_ecdsa() -> None:
    crypto = Crypto(Crypto.generate_keys(TokenAlg.ES256))
    assert crypto.verify_signature(b"data", crypto.sign(b"data"))


def test_sign_rsa(monkeypatch: pytest.MonkeyPatch) -> None:
    """RSA-PSS round trip; a 2048-bit key keeps it in the fast suite CI runs (4096 is the engine's default)."""
    monkeypatch.setattr(crypto_module, "RSA_SIZE", 2048)
    crypto = Crypto(Crypto.generate_keys(TokenAlg.RS256))
    signature = crypto.sign(b"data")
    assert crypto.verify_signature(b"data", signature)
    assert not crypto.verify_signature(b"data!", signature)


##### AEAD #####
def test_encrypt_roundtrip(crypto: Crypto) -> None:
    blob = crypto.encrypt(b"secret letters")
    assert blob != b"secret letters"
    assert crypto.decrypt(blob) == b"secret letters"


def test_encrypt_nonce_random(crypto: Crypto) -> None:
    assert crypto.encrypt(b"same") != crypto.encrypt(b"same")


def test_encrypt_with_aad(crypto: Crypto) -> None:
    blob = crypto.encrypt(b"body", aad=b"header")
    assert crypto.decrypt(blob, aad=b"header") == b"body"
    with pytest.raises(CryptoError):
        crypto.decrypt(blob, aad=b"tampered")


def test_decrypt_tampered(crypto: Crypto) -> None:
    blob = bytearray(crypto.encrypt(b"integrity"))
    blob[-1] ^= 0xFF
    with pytest.raises(CryptoError):
        crypto.decrypt(bytes(blob))


def test_decrypt_truncated(crypto: Crypto) -> None:
    with pytest.raises(CryptoError):
        crypto.decrypt(b"too short")


##### SETTINGS #####
##### EDGES #####
def test_engine_without_any_key_raises() -> None:
    with pytest.raises(CryptoError):
        Crypto(CryptoSettings(secret=SECRET, alg=TokenAlg.EDDSA))


def test_listener_cannot_sign(ed_crypto: Crypto) -> None:
    listener = Crypto(CryptoSettings(secret=SECRET, alg=TokenAlg.EDDSA), jwks=ed_crypto.public_jwks())
    with pytest.raises(CryptoError):
        listener.create_token({"sub": "u"}, expires_in=timedelta(minutes=5))


def test_unsupported_pem_rejected() -> None:
    pem = (
        x25519.X25519PrivateKey.generate()
        .private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        .decode()
    )
    with pytest.raises(CryptoError):
        Crypto(CryptoSettings(secret=SECRET, private_key=pem))


def test_jwe_non_json_payload_rejected(crypto: Crypto) -> None:
    cek = OctKey.import_key(
        HKDF(algorithm=hashes.SHA256(), length=ENC_KEY_SIZES[TokenEnc.A256GCM], info=JWE_INFO, salt=None).derive(
            SECRET.get_secret_value().encode()
        )
    )
    forged = jwe.encrypt_compact({"alg": "dir", "enc": "A256GCM"}, b"legacy-not-json", cek)
    with pytest.raises(TokenError):
        crypto.verify_token(forged)


async def test_verify_password_broken_hashes(crypto: Crypto) -> None:
    with pytest.raises(CryptoError):
        await crypto.verify_password("pw", "$argon2id$v=broken")
    with pytest.raises(CryptoError):
        await crypto.verify_password("pw", "$2b$not-really-bcrypt")


def test_needs_rehash_broken_argon2(crypto: Crypto) -> None:
    with pytest.raises(CryptoError):
        crypto.needs_rehash("$argon2id$v=broken")


def test_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine takes the composite's settings as its config: CRYPTO__* from the environment."""
    monkeypatch.setenv("CRYPTO__SECRET", "from-the-environment")
    crypto = Crypto(CryptoSettings())
    assert crypto.verify_token(crypto.create_token({"sub": "u"}, expires_in=timedelta(60)))["sub"] == "u"


def test_generate_keys_symmetric_has_no_pem() -> None:
    settings = Crypto.generate_keys()
    assert settings.alg is TokenAlg.HS256
    assert settings.private_key == ""


##### IDENTIFIERS #####
@pytest.mark.parametrize(
    ("key", "identifier", "ident"),
    [
        ("k", "ana@example.org", "102ffdfba6752efa0a58b58c644d48c7"),
        ("gnosis-secret", " Ana@Example.ORG ", "c77936a172b73aa91dffd68633087fef"),
    ],
    ids=["plain", "folded"],
)
def test_identify_pinned(key: str, identifier: str, ident: str) -> None:
    """The ids every enrolled person already holds: a change here would orphan their memory."""
    assert Crypto.identify(key, identifier) == ident


def test_identify_one_person() -> None:
    """One person is one id however the identifier is written; a fixed-width hex digest."""
    ident = Crypto.identify("k", "ana@example.org")
    assert (ident, len(ident)) == (Crypto.identify("k", " Ana@Example.ORG "), 32)


@pytest.mark.parametrize(("key", "identifier"), [("k", "bob@example.org"), ("other", "ana@example.org")])
def test_identify_apart(key: str, identifier: str) -> None:
    """Another person, or another key, is another id."""
    assert Crypto.identify(key, identifier) != Crypto.identify("k", "ana@example.org")


def test_token_fresh() -> None:
    """Every token is new and URL-safe."""
    first, second = Crypto.token(), Crypto.token()
    assert (first != second, len(first) >= 43, first.isascii()) == (True, True, True)
