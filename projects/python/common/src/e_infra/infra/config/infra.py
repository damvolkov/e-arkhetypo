"""infra/config/infra: the process — its environment, where it listens, and the crypto it signs with."""

from enum import StrEnum
from typing import Annotated

from pydantic import Field, PositiveInt, SecretStr

from e_infra.infra.config.base import BaseSettings
from e_infra.ops.crypto import BCRYPT_ROUNDS, PasswordHasher, TokenAlg, TokenEnc


##### ENUMS #####
class Env(StrEnum):
    PROD = "prod"
    DEV = "dev"
    LOCAL = "local"


##### SETTINGS #####
class InfraSettings(BaseSettings):
    """The process: APP_ENV (dev | local | prod) drives the logger, APP_HOST / APP_PORT the granian runner; a typo in
    the environment (`deV`) fails the load and never reaches runtime."""

    ### APP
    APP_ENV: Env = Env.DEV
    APP_HOST: str = "127.0.0.1"
    APP_PORT: Annotated[int, Field(ge=0, le=65535)] = 8000

    ### CRYPTO
    ### the double underscore is the variable's own: a bare SECRET, ALG or ENC would collide with any other tool's.
    CRYPTO__SECRET: SecretStr | None = None
    CRYPTO__ALG: TokenAlg = TokenAlg.HS256
    CRYPTO__ENC: TokenEnc = TokenEnc.A256GCM
    CRYPTO__PRIVATE_KEY: SecretStr = SecretStr("")
    CRYPTO__HASHER: PasswordHasher = PasswordHasher.ARGON2
    CRYPTO__BCRYPT_ROUNDS: PositiveInt = BCRYPT_ROUNDS
