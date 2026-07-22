"""podstage — headless game-streaming sandbox manager.

Provisions and manages isolated Steam streaming sessions:
a virtual gamescope display (headless) running an isolated Steam instance with
its own settings/prefixes but shared game downloads, captured and streamed via
Sunshine to Moonlight clients (e.g. Steam Deck) — without disturbing the host
desktop (its real monitors, audio, and running apps).
"""

__version__ = "0.1.1"
