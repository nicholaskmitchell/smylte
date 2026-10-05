"""The mail feature's per-app objects, built once at startup.

`build_runtime` is pure construction: it opens no socket, reads no secret and
does not touch D-Bus (`KeyringBackend` imports `keyring` lazily, inside its
methods). Everything that can fail — an unreachable keyring, a key file with
the wrong mode, a mailbox that refuses the login — fails later, on the request
or the scan that needs it, where the owner can see the reason. The rejected
alternative, checking at startup, would refuse to boot a deployment whose only
problem is that email ingestion has not been set up yet.

The secrets store's backend marker lives in the database's `meta` table and is
reached through `svc.mail`, the same lock borrow the pipeline uses.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import Settings
from ..db import store
from .pipeline import Ingestor
from .secrets import SecretStore, build_secret_store
from .settings import SECRETS_MARKER_KEY


@dataclass
class MailRuntime:
    secrets: SecretStore
    ingestor: Ingestor
    deployment_enabled: bool


def build_runtime(settings: Settings, svc) -> MailRuntime:
    """The secret store and the ingestor for `svc`, wired to the deployment's settings."""
    secrets = build_secret_store(
        settings,
        lambda: svc.mail(store.get_meta, SECRETS_MARKER_KEY),
        lambda v: svc.mail(store.set_meta, SECRETS_MARKER_KEY, v),
    )
    ingestor = Ingestor(svc, secrets, deployment_enabled=settings.mail_enabled)
    return MailRuntime(secrets=secrets, ingestor=ingestor,
                       deployment_enabled=settings.mail_enabled)
