"""api.lifespan.crypto: the `crypto` branch — the user records' password hashing and tokens.

Crypto is written into the system graph — the user records' password hashing —; it is a pure in-process object, so this
concern owns no resource to close.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from litestar import Litestar

from e_api.api.state import AppState
from e_api.infra.logger import logger
from e_api.infra.settings import settings as st
from e_api.ops.crypto import Crypto, CryptoKeys


@asynccontextmanager
async def lifespan(app: Litestar) -> AsyncGenerator[None]:
    """Mount `system.crypto` from the CRYPTO__* settings."""
    AppState.of(app).system.crypto = Crypto(
        CryptoKeys(
            secret=st.CRYPTO__SECRET,
            alg=st.CRYPTO__ALG,
            enc=st.CRYPTO__ENC,
            private_key=st.CRYPTO__PRIVATE_KEY.get_secret_value(),
            hasher=st.CRYPTO__HASHER,
            bcrypt_rounds=st.CRYPTO__BCRYPT_ROUNDS,
        )
    )
    logger.info("crypto ready", step="START")
    yield
