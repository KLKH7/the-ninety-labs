"""The credential every live run uses: the aio DefaultAzureCredential, signed in before long work.

Foundry's agent clients are async, so they take an async credential. A sync DefaultAzureCredential
handed to one fetches its token on the event loop's thread, blocking every other call while it
does; and a run that only asks for its first token after a long simulation can find agents-live's
five-minute OIDC assertion already expired (AADSTS700024). So every live run: makes one
`new_credential()`, signs in (`sign_in`) before anything slow, then passes the same object to the
chat client and every FoundryAgent. Moved here from the workflow (W1) so the slice and the
evaluations use the same one.

Known exceptions, each with a reason: ninety/agents/foundry_evals.py and foundry.publish talk to the
sync AIProjectClient, which takes a sync credential (no event loop to block); ninety/speech/tts.py
asks for one Speech token per synthesis, synchronously, outside the agents' loop. The Personalizer's
service (ninety/personalizer/server.py, eval.py) moves here with #155.
"""

from __future__ import annotations

import time
from collections.abc import Callable

from ninety.agents.budgets import TOKEN_MARGIN_SECONDS

# The Foundry project's token scope, the default of azure-ai-projects' client configuration.
FOUNDRY_SCOPE = "https://ai.azure.com/.default"


class SignedIn:
    """An async credential that keeps each token it gets until shortly before it expires.

    In agents-live, `azure/login` leaves the Azure CLI holding an OIDC client assertion that is
    valid for five minutes; every token request after that fails (AADSTS700024, as the
    Personalizer evaluation did 24 minutes in). A token itself lasts an hour or more, so a run
    that signs in first and reuses its tokens never asks again within a run."""

    def __init__(self, inner):
        self.inner, self.tokens = inner, {}

    async def get_token(self, *scopes: str, **kwargs):
        if kwargs.get("claims") or kwargs.get("enable_cae"):
            # A claims challenge (or continuous access evaluation) asks for a new token on purpose:
            # the kept one may have been revoked. Never answer it from the cache.
            return await self.inner.get_token(*scopes, **kwargs)
        token = self.tokens.get(scopes)
        if token is None or token.expires_on - time.time() < TOKEN_MARGIN_SECONDS:
            token = self.tokens[scopes] = await self.inner.get_token(*scopes, **kwargs)
        return token

    async def close(self) -> None:
        await self.inner.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()


def new_credential() -> SignedIn:
    """The live run's credential: the aio DefaultAzureCredential, kept by SignedIn."""
    from azure.identity.aio import DefaultAzureCredential

    return SignedIn(DefaultAzureCredential())


async def sign_in(credential) -> None:
    """Gets the Foundry token now, before anything slow (a simulation) can outlast the sign-in."""
    await credential.get_token(FOUNDRY_SCOPE)


async def sign_in_then_load(credential, load_events: Callable[[], list[dict]]) -> list[dict]:
    """Signs in, then loads the events (a simulation can take minutes)."""
    await sign_in(credential)
    return load_events()
