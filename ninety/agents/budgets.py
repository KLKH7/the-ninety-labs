"""Time budgets the live agents share, in one place so each is derived from the others, not copied.

The workflow (ninety/agents/workflow.py) gives a writer MODEL_TIMEOUT_SECONDS; the live credential
(ninety/agents/credentials.py) refreshes a kept token TOKEN_MARGIN_SECONDS before it expires, so no
model call starts on a token that could lapse before the call is answered.
"""

# Design: a live writer that has not answered in a minute is writing about a moment the broadcast
# has moved past; its claim is held and the template stays. The Judge has its own timeout.
MODEL_TIMEOUT_SECONDS = 60.0
# Twice a writer's whole budget: a token is refreshed well before a call in flight could outlive it.
TOKEN_MARGIN_SECONDS = 2 * MODEL_TIMEOUT_SECONDS
