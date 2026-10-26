"""ops/crypto: everything that needs a key or entropy — keyed ids, bearer tokens, password hashing, JWS/JWE, AEAD.

Signatures and tokens ride on joserfc over cryptography; hashing without a key is `ops/hash`, and the two never
overlap. Agnostic: the engine reads its configuration through `CryptoConfig` (what `core/settings/crypto`
satisfies, or the `CryptoKeys` that `generate_keys` mints), and its errors are its own.

bcrypt is Rust-backed, argon2 the PHC winner; async only where hashing is intentionally slow, everything else is microseconds."""

import hashlib
import hmac
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import IntEnum, StrEnum
from functools import partial
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Literal, Protocol, cast, runtime_checkable

import anyio
import argon2
import bcrypt
import beartype
import msgspec
from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import (
    RSAPrivateKey,  # noqa: TC002 — beartype resolves the engine annotations at runtime
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from joserfc import jwe, jwk, jwt
from joserfc.errors import JoseError
from joserfc.jwk import ECKey, KeySet, OctKey, OKPKey, RSAKey
from joserfc.jwt import JWTClaimsRegistry
from pydantic import SecretStr

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping


##### ERRORS #####
class CryptoError(Exception):
    """The crypto engine refused: key material missing, corrupt input or failed decryption."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class TokenFailure(StrEnum):
    """Distinct reasons a JWT token will not pass validation."""

    MALFORMED = "malformed"  # count "." ≠ JWS(2) / JWE(4)
    EXPIRED = "expired"  # exp claim validation failed
    FORGED = "forged"  # signature mismatch with our keys
    INVALID_CLAIM = "invalid_claim"  # issuer/audience mismatch
    EMPTY_JWE = "empty_jwe"  # decrypted payload was None
    MISSING_FIELD = "missing_field"  # required claim absent


class TokenError(CryptoError):
    """A token that will not pass: malformed, forged, expired or failing its claim registry."""

    def __init__(self, message: str, *, kind: TokenFailure = TokenFailure.MALFORMED) -> None:
        super().__init__(message)
        self.kind = kind


##### TYPES #####
class TokenAlg(StrEnum):
    HS256 = "HS256"
    HS384 = "HS384"
    HS512 = "HS512"
    RS256 = "RS256"
    RS512 = "RS512"
    PS256 = "PS256"
    ES256 = "ES256"
    EDDSA = "EdDSA"


class TokenEnc(StrEnum):
    A128GCM = "A128GCM"
    A256GCM = "A256GCM"


class PasswordHasher(StrEnum):
    ARGON2 = "argon2id"
    BCRYPT = "bcrypt"


BCRYPT_ROUNDS: int = 12


@runtime_checkable
class CryptoConfig(Protocol):
    """What the engine reads of its configuration: the master secret, the token algorithms, an optional PEM key, the
    password hasher and bcrypt's cost."""

    @property
    def secret(self) -> SecretStr | None: ...

    @property
    def alg(self) -> TokenAlg: ...

    @property
    def enc(self) -> TokenEnc: ...

    @property
    def private_key(self) -> str: ...

    @property
    def hasher(self) -> PasswordHasher: ...

    @property
    def bcrypt_rounds(self) -> int: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class CryptoKeys:
    """Key material `generate_keys` mints for a deployment: a `CryptoConfig` with the defaults for the rest."""

    secret: SecretStr | None
    alg: TokenAlg = TokenAlg.HS256
    enc: TokenEnc = TokenEnc.A256GCM
    private_key: str = ""
    hasher: PasswordHasher = PasswordHasher.ARGON2
    bcrypt_rounds: int = BCRYPT_ROUNDS


class TokenShape(IntEnum):
    JWS = 2  # count of "." separators: 3 parts
    JWE = 4  # 5 parts


class AlgPrefix(StrEnum):
    RS = "RS"
    PS = "PS"
    ES = "ES"
    EDDSA = "Ed"  # EdDSA's two-letter prefix, named by the algorithm it opens


##### DEFAULTS #####
SECRET_SIZE: int = 32  # bytes of entropy for the master secret
IDENT_SIZE: int = 32  # hex chars of an identifier's id: 128 bits, never colliding, short enough for a log
KEY_SIZE: int = 32  # HKDF output: one AES-256/HMAC-256 key per domain
NONCE_SIZE: int = 12  # AES-GCM standard
TAG_SIZE: int = 16
RSA_SIZE: int = 4096
RSA_EXPONENT: int = 65537
BCRYPT_MAX_INPUT: int = 72
ARGON2_MARKER: str = "$argon2"
BCRYPT_MARKER: str = "$2"
TOKEN_INFO: bytes = b"e-core/token"
JWE_INFO: bytes = b"e-core/jwe"
ENCRYPT_INFO: bytes = b"e-core/encrypt"
SIGN_INFO: bytes = b"e-core/sign"
ENC_KEY_SIZES: Final[Mapping[TokenEnc, int]] = MappingProxyType(
    {TokenEnc.A128GCM: 16, TokenEnc.A256GCM: 32}
)  # dir mode: key IS the CEK
JOSE_KEY_TYPES: Final[Mapping[AlgPrefix, Literal["RSA", "EC", "OKP"]]] = MappingProxyType(
    {AlgPrefix.RS: "RSA", AlgPrefix.PS: "RSA", AlgPrefix.ES: "EC", AlgPrefix.EDDSA: "OKP"}
)  # alg prefix -> joserfc key_type
MISSING_PRIVATE_KEY: str = "asymmetric engine needs a private_key PEM to sign tokens"
NO_VERIFY_KEY: str = "engine needs a signing key or a public jwks set to verify"
MISSING_ROOT: str = "crypto engine needs a secret: set CRYPTO__SECRET or pass CryptoSettings(secret=...)"
UNSUPPORTED_KEY: str = "Unsupported signing key type"
MALFORMED: str = "Not a JWS (3 parts) or JWE (5 parts) compact token"
UNKNOWN_HASH: str = "Unrecognized password hash format"
NO_PUBLIC_JWKS: str = "Symmetric (HS*) engines have no public set to export"
ENCRYPT_FAILED: str = "Decryption failed: wrong key, corrupt payload or mismatched AAD"
REJECTED: str = "Token rejected: {}"
BCRYPT_TOO_LONG: str = f"bcrypt silently truncates past {BCRYPT_MAX_INPUT} bytes; choose a shorter password or argon2"


##### ENGINE #####


class Crypto:
    """Master crypto engine: hash_password/verify_password (async, off-thread), create_token/verify_token (JWS JWT and JWE), sign/verify_signature (Ed25519/RSA/EC, HMAC fallback), encrypt/decrypt (AES-256-GCM); identify (a keyed, stable id for an identifier) and token (a fresh bearer token) need no engine."""

    __slots__ = (
        "_aead",
        "_alg",
        "_argon2",
        "_enc",
        "_hasher",
        "_hmac_key",
        "_jwe_key",
        "_private_key",
        "_rounds",
        "_secret",
        "_token_key",
        "_verify_key",
    )

    def __init__(self, settings: CryptoConfig, *, jwks: dict[str, Any] | None = None) -> None:
        match settings.secret:
            case None:
                raise CryptoError(MISSING_ROOT)
            case secret:
                self._secret = secret.get_secret_value().encode()
        self._alg, self._enc = settings.alg, settings.enc
        self._hasher, self._rounds = settings.hasher, settings.bcrypt_rounds
        self._argon2 = argon2.PasswordHasher()
        self._aead = AESGCM(self._common_derive(ENCRYPT_INFO))
        self._hmac_key = self._common_derive(SIGN_INFO)
        self._jwe_key = OctKey.import_key(self._common_derive(JWE_INFO, ENC_KEY_SIZES[settings.enc]))
        self._private_key = self._common_load_pem(settings.private_key)
        self._token_key = self._common_build_token_key(settings.alg, settings.private_key)
        match KeySet.import_key_set(cast("Any", jwks)) if jwks else self._token_key:
            case None:
                raise CryptoError(NO_VERIFY_KEY)
            case key:
                self._verify_key: OctKey | RSAKey | ECKey | OKPKey | KeySet = key

    ##### PRIVATE #####

    def _common_derive(self, info: bytes, length: int = KEY_SIZE) -> bytes:
        return HKDF(algorithm=hashes.SHA256(), length=length, info=info, salt=None).derive(self._secret)

    @staticmethod
    def _common_load_pem(pem: str) -> ed25519.Ed25519PrivateKey | RSAPrivateKey | ec.EllipticCurvePrivateKey | None:
        match pem:
            case "":
                return None
            case _:
                match serialization.load_pem_private_key(pem.encode(), password=None):
                    case ed25519.Ed25519PrivateKey() | rsa.RSAPrivateKey() | ec.EllipticCurvePrivateKey() as key:
                        return key
                    case _:
                        raise CryptoError(UNSUPPORTED_KEY)

    def _common_build_token_key(self, alg: TokenAlg, pem: str) -> OctKey | RSAKey | ECKey | OKPKey | None:
        match alg:
            case TokenAlg.HS256 | TokenAlg.HS384 | TokenAlg.HS512:
                return OctKey.import_key(self._common_derive(TOKEN_INFO, int(alg.value[2:]) // 8))
            case _:
                match pem:
                    case "":
                        return None
                    case _:
                        return jwk.import_key(pem, JOSE_KEY_TYPES[AlgPrefix(alg.value[:2])])

    def _common_verify_claims(self, claims: dict[str, Any], issuer: str | None, audience: str | None) -> None:
        options: dict[str, Any] = {"exp": {"essential": True}, "nbf": {}, "iat": {}}
        match issuer:
            case str() as value:
                options["iss"] = {"essential": True, "value": value}
            case _:
                pass
        match audience:
            case str() as value:
                options["aud"] = {"essential": True, "value": value}
            case _:
                pass
        try:
            JWTClaimsRegistry(**options).validate(claims)
        except JoseError as exc:
            raise TokenError(REJECTED.format(exc), kind=TokenFailure.INVALID_CLAIM) from exc

    def _verify_token_jws(self, token: str) -> dict[str, Any]:
        try:
            return dict(jwt.decode(token, self._verify_key, algorithms=[self._alg.value]).claims)
        except JoseError as exc:
            raise TokenError(REJECTED.format(exc), kind=TokenFailure.INVALID_CLAIM) from exc

    def _verify_token_jwe(self, token: str) -> dict[str, Any]:
        try:
            plaintext = jwe.decrypt_compact(token, self._jwe_key).plaintext
            return msgspec.json.decode(cast("bytes", plaintext))
        except (JoseError, msgspec.DecodeError) as exc:
            raise TokenError(REJECTED.format(exc), kind=TokenFailure.INVALID_CLAIM) from exc

    def _create_token_jws(self, claims: dict[str, Any]) -> str:
        match self._token_key:
            case None:
                raise CryptoError(MISSING_PRIVATE_KEY)
            case key:
                return jwt.encode({"alg": self._alg.value}, claims, key, algorithms=[self._alg.value])

    def _create_token_jwe(self, claims: dict[str, Any]) -> str:
        protected = {"alg": "dir", "enc": self._enc.value}
        return jwe.encrypt_compact(protected, msgspec.json.encode(claims), self._jwe_key)

    def _hash_password_sync(self, password: str) -> str:
        match self._hasher:
            case PasswordHasher.ARGON2:
                return self._argon2.hash(password)
            case _:
                encoded = password.encode()
                match len(encoded):
                    case size if size > BCRYPT_MAX_INPUT:
                        raise CryptoError(BCRYPT_TOO_LONG)
                    case _:
                        salt = bcrypt.gensalt(rounds=self._rounds)
                        return bcrypt.hashpw(encoded, salt).decode()

    def _verify_password_sync(self, password: str, hashed: str) -> bool:
        match hashed:
            case str() if hashed.startswith(ARGON2_MARKER):
                try:
                    self._argon2.verify(hashed, password)
                except argon2.exceptions.VerifyMismatchError:
                    return False
                except argon2.exceptions.Argon2Error as exc:
                    raise CryptoError(UNKNOWN_HASH) from exc
                return True
            case str() if hashed.startswith(BCRYPT_MARKER):
                try:
                    return bcrypt.checkpw(password.encode(), hashed.encode())
                except ValueError as exc:
                    raise CryptoError(UNKNOWN_HASH) from exc
            case _:
                raise CryptoError(UNKNOWN_HASH)

    ############################################################

    ##### CLASSMAKERS #####

    @classmethod
    def generate_keys(cls, alg: TokenAlg = TokenAlg.HS256) -> CryptoKeys:
        """Bootstrap material for a deployment: fresh master secret and, for asymmetric algs, a fresh PEM key."""
        secret = SecretStr(secrets.token_urlsafe(SECRET_SIZE))
        match alg:
            case TokenAlg.HS256 | TokenAlg.HS384 | TokenAlg.HS512:
                return CryptoKeys(secret=secret, alg=alg)
            case TokenAlg.EDDSA:
                key: Any = ed25519.Ed25519PrivateKey.generate()
            case TokenAlg.ES256:
                key = ec.generate_private_key(ec.SECP256R1())
            case _:
                key = rsa.generate_private_key(public_exponent=RSA_EXPONENT, key_size=RSA_SIZE)
        pem = key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()
        return CryptoKeys(secret=secret, alg=alg, private_key=pem)

    ##### IDENTIFIERS #####

    @staticmethod
    def identify(key: str, identifier: str, *, width: int = IDENT_SIZE) -> str:
        """A stable, irreversible id for an identifier (an e-mail, a handle) under a named key: NFKC-folded, casefolded
        and trimmed, then HMAC-SHA256 under the key as given — never derived, so the id outlives this engine's own keys
        and gives nothing back without the key."""
        folded = unicodedata.normalize("NFKC", identifier).casefold().strip()
        return hmac.new(key.encode(), folded.encode(), hashlib.sha256).hexdigest()[:width]

    @staticmethod
    def token(size: int = SECRET_SIZE) -> str:
        """A fresh bearer token from the system's CSPRNG, URL-safe: handed out once, stored only as its hash."""
        return secrets.token_urlsafe(size)

    ##### PASSWORDS #####

    async def hash_password(self, password: str) -> str:
        """Argon2id (default) or bcrypt; deliberately slow, so it runs off the event loop."""
        return await anyio.to_thread.run_sync(self._hash_password_sync, password)

    async def verify_password(self, password: str, hashed: str) -> bool:
        """Backend chosen from the hash prefix, so old hashes verify while the fleet migrates."""
        return await anyio.to_thread.run_sync(self._verify_password_sync, password, hashed)

    def needs_rehash(self, hashed: str) -> bool:
        """True when parameters or backend drifted from config: re-hash on next successful login."""
        match hashed:
            case str() if hashed.startswith(ARGON2_MARKER):
                try:
                    return self._argon2.check_needs_rehash(hashed)
                except argon2.exceptions.InvalidHashError as exc:
                    raise CryptoError(UNKNOWN_HASH) from exc
            case str() if hashed.startswith(BCRYPT_MARKER):
                return hashed[4:6] != f"{self._rounds:02d}"
            case _:
                raise CryptoError(UNKNOWN_HASH)

    ##### TOKENS #####

    def create_token(
        self,
        payload: dict[str, Any],
        *,
        expires_in: timedelta | None = None,
        encrypted: bool = False,
    ) -> str:
        """Signed JWS JWT, or JWE (dir + A256GCM) when encrypted; `expires_in` stamps a relative `exp`."""
        claims = dict(payload)
        match expires_in:
            case timedelta() as delta:
                claims["exp"] = int((datetime.now(UTC) + delta).timestamp())
            case _:
                pass
        return self._create_token_jwe(claims) if encrypted else self._create_token_jws(claims)

    def verify_token(self, token: str, *, issuer: str | None = None, audience: str | None = None) -> dict[str, Any]:
        """Decode JWS or JWE by shape, pin the configured alg, then enforce exp/nbf/iat and optional iss/aud."""
        match token.count("."):
            case TokenShape.JWS:
                claims = self._verify_token_jws(token)
            case TokenShape.JWE:
                claims = self._verify_token_jwe(token)
            case _:
                raise TokenError(MALFORMED, kind=TokenFailure.MALFORMED)
        self._common_verify_claims(claims, issuer, audience)
        return claims

    def public_jwks(self) -> dict[str, Any]:
        """The public verification set for other services, servable as-is at /.well-known/jwks.json."""
        match self._token_key:
            case OctKey() | None:
                raise CryptoError(NO_PUBLIC_JWKS)
            case key:
                return dict(KeySet([key]).as_dict())

    ##### SIGNATURES #####

    def sign(self, data: bytes) -> bytes:
        """Ed25519 / RSA-PSS / ECDSA over the configured PEM key; HMAC-SHA256 with the derived key when there is none."""
        match self._private_key:
            case None:
                return hmac.new(self._hmac_key, data, hashlib.sha256).digest()
            case ed25519.Ed25519PrivateKey() as key:
                return key.sign(data)
            case rsa.RSAPrivateKey() as key:
                pss = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH)
                return key.sign(data, pss, hashes.SHA256())
            case key:  ### narrowed by the union: what remains after None/Ed25519/RSA is only EC.
                return key.sign(data, ec.ECDSA(hashes.SHA256()))

    def verify_signature(self, data: bytes, signature: bytes) -> bool:
        """Counterpart of sign(); False on any mismatch, never an exception."""
        match self._private_key:
            case None:
                return hmac.compare_digest(self.sign(data), signature)
            case ed25519.Ed25519PrivateKey() as key:
                check: Callable[[], None] = partial(key.public_key().verify, signature, data)
            case rsa.RSAPrivateKey() as key:
                pss = padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH)
                check = partial(key.public_key().verify, signature, data, pss, hashes.SHA256())
            case key:  ### narrowed by the union: what remains after None/Ed25519/RSA is only EC.
                check = partial(key.public_key().verify, signature, data, ec.ECDSA(hashes.SHA256()))
        try:
            check()
        except InvalidSignature:
            return False
        return True

    ##### AEAD #####

    def encrypt(self, data: bytes, *, aad: bytes | None = None) -> bytes:
        """AES-256-GCM with a fresh nonce, framed `nonce || ciphertext || tag`."""
        nonce = secrets.token_bytes(NONCE_SIZE)
        return nonce + self._aead.encrypt(nonce, data, aad)

    def decrypt(self, data: bytes, *, aad: bytes | None = None) -> bytes:
        """Inverse of encrypt(); CryptoError on tamper, truncation or AAD mismatch."""
        match len(data) >= NONCE_SIZE + TAG_SIZE:
            case True:
                try:
                    return self._aead.decrypt(data[:NONCE_SIZE], data[NONCE_SIZE:], aad)
                except InvalidTag as exc:
                    raise CryptoError(ENCRYPT_FAILED) from exc
            case _:
                raise CryptoError(ENCRYPT_FAILED)


##### RUNTIME TYPE CHECKING #####
Crypto = beartype.beartype(Crypto)
TokenAlg = beartype.beartype(TokenAlg)
TokenEnc = beartype.beartype(TokenEnc)
PasswordHasher = beartype.beartype(PasswordHasher)
