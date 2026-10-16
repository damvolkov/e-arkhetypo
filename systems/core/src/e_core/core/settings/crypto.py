"""core/settings/crypto: crypto engine configuration, loaded from CRYPTO__*."""

from enum import StrEnum

from pydantic_settings import SettingsConfigDict

from e_core.core.settings.base import BaseSettings, Secret


##### ENUMS #####
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


##### DEFAULTS #####
BCRYPT_ROUNDS: int = 12


##### SETTINGS #####
class CryptoSettings(BaseSettings):
    """CRYPTO__SECRET / _ALG / _ENC / _PRIVATE_KEY (PEM) / _HASHER / _BCRYPT_ROUNDS."""

    ### bare SECRET, ALG or ENC would collide with any other tool's variables: the scope owns its prefix.
    model_config = SettingsConfigDict(env_prefix="CRYPTO__")

    secret: Secret | None = None
    alg: TokenAlg = TokenAlg.HS256
    enc: TokenEnc = TokenEnc.A256GCM
    private_key: str = ""
    hasher: PasswordHasher = PasswordHasher.ARGON2
    bcrypt_rounds: int = BCRYPT_ROUNDS
