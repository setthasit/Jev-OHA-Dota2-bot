WIP: Jev OHA Dota 2 Bot
---

Fork from [forest0xia/dota2bot-OpenHyperAI](https://github.com/forest0xia/dota2bot-OpenHyperAI) (Open Hyper AI bot scripts for Dota 2).

---

Dota 2 bots that ask TypeSafe's Jev model for decisions during a custom lobby game.
The Lua bot scripts in `bots/` talk to a local bridge in `bridge/` over `127.0.0.1:8765`.
The bridge calls the model, caps spend per second, and writes one JSONL log per game.
When the model is unreachable, the bots keep playing on fallback logic.
The in-game code that calls the bridge is still in progress.

Setup, lobby rules, and fair play: [docs/JEV_BOTS.md](docs/JEV_BOTS.md).
Codebase reference: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
