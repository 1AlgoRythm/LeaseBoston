# Demo recorder

These scripts recorded `docs/demo.mp4`. They drive the real Claude Desktop app and a browser window showing the landlord
inbox, and they record that part of the screen.

| File | What it does |
|---|---|
| `ad.py` | A small wrapper around the [agent-desktop](https://github.com/vercel-labs/agent-desktop) command-line tool: it finds elements and clicks or types on them |
| `run_demo.py` | Plays seven scenes, records with macOS `screencapture`, and writes the time each scene starts and ends to `demo/out/steps.json` |
| `edit.py` | Cuts the recording into the final video: a title card before each scene, and long waits sped up |

## Before you run it

- macOS, with Claude Desktop set up for this server (see the main README), `agent-desktop` (`npm install -g agent-desktop`)
  and `ffmpeg`.
- Accessibility and Screen Recording permission for the app that runs the script.
- The landlord page open in its own Chrome window:
  `open -na "Google Chrome" --args --app=http://127.0.0.1:8000/landlord/L2 --user-data-dir=/tmp/leaseboston-chrome`
- **Hands off.** Claude Desktop's message box ignores text typed in the background, so the script uses real keystrokes
  for typing (agent-desktop's `--headed` mode). Don't touch the keyboard or mouse until the script brings your previous
  app back.

## Run

```bash
python3 demo/run_demo.py                 # about 5 minutes, hands off
uv run --with pillow python demo/edit.py # writes demo/out/leaseboston-demo.mp4
```

The script resets the demo database, restarts Claude Desktop and the landlord server, and refuses to record if either
window is not where it expects. It pauses the recording while it opens a new chat, because the sidebar would show your
chat history.
