"""infra/settings/crypto: the configuration of the crypto engine (`ops/crypto`), loaded from CRYPTO__*."""

from pydantic_settings import SettingsConfigDict

from e_infra.infra.settings.base import BaseSettings, Secret
from e_infra.ops.crypto import BCRYPT_ROUNDS, PasswordHasher, TokenAlg, TokenEnc


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
