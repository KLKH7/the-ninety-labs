"""The Producer's side of the Personalizer: a Personalize that calls the A2A server, with the
in-process fallback behind the same interface.

The remote gets `BUDGET_S` (ninety/personalizer/core.py). On a timeout, a 5xx or a refused
connection, the fallback answers instead, so a viewer never waits longer than the budget for the
remote. Anything else (a 4xx, a refused request, a malformed reply envelope) is a contract defect
between our own two programs and raises `PersonalizerError`, so a test or the trace shows it rather
than a fallback hiding it.

Whatever the remote returns is re-checked here, against the caller's own claim and evidence, by the
same rule the server applies (`core.recheck`): this process does not trust the other one.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import asdict

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.helpers.proto_helpers import get_data_parts, new_data_message
from a2a.types import Role, SendMessageRequest

from ninety.agents.contracts import Personalize, Profile, Variant
from ninety.agents.factcheck import Claim
from ninety.personalizer.core import BUDGET_S, recheck, verified_text
from ninety.personalizer.server import agent_card

log = logging.getLogger(__name__)


class PersonalizerError(RuntimeError):
    """The remote answered, but not as the contract says: a defect, never an outage."""


def outage(error: BaseException) -> str | None:
    """"timeout", "5xx" or "refused" when `error` (or what caused it) is one, else None."""
    seen: BaseException | None = error
    while seen is not None:
        if isinstance(seen, TimeoutError | httpx.TimeoutException):
            return "timeout"
        if isinstance(seen, httpx.HTTPStatusError) and seen.response.status_code >= 500:
            return "5xx"
        if isinstance(seen, httpx.ConnectError):
            return "refused"
        seen = seen.__cause__ or seen.__context__
    return None


class RemotePersonalizer:
    """A Personalize over A2A. `fallback` must be in-process and fast: it runs after the remote
    failed, so its own time is added to whatever the remote already spent."""

    def __init__(
        self,
        url: str,
        budget_s: float = BUDGET_S,
        fallback: Personalize = verified_text,
        http: httpx.AsyncClient | None = None,
    ):
        if budget_s <= 0:
            raise ValueError("budget_s must be positive")
        self.budget_s, self.fallback = budget_s, fallback
        self.http = http or httpx.AsyncClient(timeout=budget_s)
        config = ClientConfig(streaming=False, httpx_client=self.http)
        self.client = ClientFactory(config).create(agent_card(url))
        self.last_route = ""  # "remote" or "fallback: <why>", for the trace
        self.last_dropped: dict[int, str] = {}  # profile number -> why its variant did not air
        self.abandoned: set[asyncio.Task] = set()  # cancelled at the deadline, awaited on close

    async def __call__(self, claim: Claim, evidence: list[dict], profiles: list[Profile]) -> list[Variant]:
        if not profiles:
            return []
        started = time.perf_counter()
        try:
            data = await self._within_budget(self._send(claim, evidence, profiles))
        except Exception as e:
            why = outage(e)
            if why is None:
                raise PersonalizerError(f"personalizer refused the request: {e}") from e
            self.last_route, self.last_dropped = f"fallback: {why}", {}
            log.warning("personalizer %s after %.0f ms; in-process fallback", why, _ms(started))
            return await self.fallback(claim, evidence, profiles)
        variants, dropped = recheck(claim, evidence, profiles, _texts(data, profiles))
        # The server's reasons first: a variant it replaced comes back as the verified text, which
        # passes here, so only the server knows why. A reason this side found wins over it.
        self.last_dropped = {**_server_dropped(data, profiles), **dropped}
        self.last_route = "remote"
        return variants

    async def _within_budget(self, call):
        """The call's result, or TimeoutError at the deadline. Unlike asyncio.wait_for, this does not
        wait for the cancelled call to unwind, so a slow cancellation cannot overrun the budget."""
        task = asyncio.ensure_future(call)
        done, _ = await asyncio.wait({task}, timeout=self.budget_s)
        if not done:
            task.cancel()
            # Kept until it unwinds, then awaited by close(): a task left pending when the loop
            # closes is destroyed mid-request, and the A2A client's telemetry span then fails to
            # detach ("created in a different Context"), which the live evaluation logged.
            self.abandoned.add(task)
            task.add_done_callback(self._unwound)
            raise TimeoutError(f"no reply within {self.budget_s} s")
        return task.result()

    async def _send(self, claim: Claim, evidence: list[dict], profiles: list[Profile]) -> object:
        body = {"claim": asdict(claim), "evidence": evidence, "profiles": [asdict(p) for p in profiles]}
        request = SendMessageRequest(message=new_data_message(body, role=Role.ROLE_USER))
        replies = [r async for r in self.client.send_message(request)]
        parts = [d for r in replies if r.HasField("message") for d in get_data_parts(r.message.parts)]
        if len(parts) != 1:
            raise PersonalizerError(f"expected one data part in the reply, got {len(parts)}")
        return parts[0]

    def _unwound(self, task: asyncio.Task) -> None:
        self.abandoned.discard(task)
        if not task.cancelled():
            task.exception()  # retrieved, so asyncio does not report it as never retrieved

    async def close(self) -> None:
        if self.abandoned:  # bounded, in case one never unwinds
            _, stuck = await asyncio.wait(set(self.abandoned), timeout=self.budget_s)
            if stuck:
                log.warning("%d personalizer requests still unwinding at close", len(stuck))
        await self.client.close()


def _texts(data: object, profiles: list[Profile]) -> dict[int, str]:
    """The remote's text for each profile, by position, when its persona and language match the
    profile asked for. Anything else is left out, so that profile gets the verified text."""
    variants = data.get("variants") if isinstance(data, dict) else None
    if not isinstance(variants, list):
        raise PersonalizerError("the reply has no variants list")
    texts = {}
    for i, (v, p) in enumerate(zip(variants, profiles, strict=False)):
        if isinstance(v, dict) and v.get("persona") == p.persona and v.get("lang") == p.lang:
            if isinstance(v.get("text"), str):
                texts[i] = v["text"]
    return texts


def _server_dropped(data: dict, profiles: list[Profile]) -> dict[int, str]:
    """The server's drop reasons, for the trace only: they never decide what airs."""
    reported = data.get("dropped")
    if not isinstance(reported, dict):
        return {}
    return {
        int(i): f"server: {why}" for i, why in reported.items()
        if isinstance(i, str) and i.isdigit() and int(i) < len(profiles) and isinstance(why, str)
    }


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


URL_ENV = "NINETY_PERSONALIZER_URL"


def in_process(personalize: Personalize, budget_s: float = BUDGET_S) -> RemotePersonalizer:
    """The A2A server in this process behind the real client, for the evaluations: the same
    request, re-check and deadlines as the deployed service, with no container to deploy."""
    from ninety.personalizer.server import InProcess, create_app

    url = "http://personalizer.in-process/"
    transport = InProcess(create_app(personalize, url))
    http = httpx.AsyncClient(transport=transport, base_url=url, timeout=budget_s)
    return RemotePersonalizer(url, budget_s=budget_s, http=http)


def from_env(env: dict[str, str] | None = None) -> Personalize:
    """The live path's Personalizer: the A2A service at NINETY_PERSONALIZER_URL with the in-process
    fallback behind it, or the fallback alone when no URL is set. With NINETY_TRANSLATOR on, the
    fallback translates the verified text too, so Spanish survives the service being down."""
    from ninety.personalizer import translate

    env = dict(os.environ) if env is None else env
    translator = translate.from_env(env)
    fallback = verified_text if translator is None else translate.translated(verified_text, translator)
    return RemotePersonalizer(env[URL_ENV], fallback=fallback) if env.get(URL_ENV) else fallback
