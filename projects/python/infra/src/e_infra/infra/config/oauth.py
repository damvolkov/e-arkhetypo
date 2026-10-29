"""infra/config/oauth: the OAuth2 identity provider — name, client, secret and metadata URL."""

from e_infra.infra.config.base import BaseSettings, Secret


class OAuthSettings(BaseSettings):
    """An empty SERVER_METADATA_URL means "no IdP configured": the registry stays empty and the app boots."""

    oauth_name: str = "dev"
    client_id: str = ""
    client_secret: Secret = Secret("")
    server_metadata_url: str = ""
