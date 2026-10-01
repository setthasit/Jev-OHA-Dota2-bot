# jevbot bridge

Local HTTP process that the Dota 2 bot scripts call for decisions from TypeSafe's Jev model.

## Run

1. Run `mise install` at the repo root.
2. Set `TYPESAFE_API_KEY` in the environment.
3. From `bridge/`, run:

   ```sh
   mise exec -- uv run jevbot serve
   ```
