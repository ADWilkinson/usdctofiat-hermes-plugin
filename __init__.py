"""USDCtoFiat Hermes plugin — registration.

USDCtoFiat by Galleon Labs. Built on the public Peer/ZKP2P protocol.
Not a Peer Cash product. Not Peerlytics.

Standalone plugin. Do not merge into NousResearch/hermes-agent.
Install: hermes plugins install ADWilkinson/usdctofiat-hermes-plugin
"""

from __future__ import annotations

try:
    from . import schemas, tools
except ImportError:  # loose directory / unit tests
    import schemas, tools

PLUGIN_NAME = "usdctofiat"


def register(ctx):
    """Wire schemas to handlers. No requires_env. No keys."""
    ctx.register_tool(
        name="usdctofiat_cashout",
        toolset=PLUGIN_NAME,
        schema=schemas.CASHOUT,
        handler=tools.usdctofiat_cashout,
    )
    ctx.register_tool(
        name="usdctofiat_estimate",
        toolset=PLUGIN_NAME,
        schema=schemas.ESTIMATE,
        handler=tools.usdctofiat_estimate,
    )
    ctx.register_tool(
        name="usdctofiat_watch",
        toolset=PLUGIN_NAME,
        schema=schemas.WATCH,
        handler=tools.usdctofiat_watch,
    )
    ctx.register_tool(
        name="usdctofiat_withdraw",
        toolset=PLUGIN_NAME,
        schema=schemas.WITHDRAW,
        handler=tools.usdctofiat_withdraw,
    )
    ctx.register_tool(
        name="usdctofiat_deposits",
        toolset=PLUGIN_NAME,
        schema=schemas.DEPOSITS,
        handler=tools.usdctofiat_deposits,
    )
