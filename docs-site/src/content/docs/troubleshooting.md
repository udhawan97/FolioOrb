---
title: Troubleshooting & FAQ
description: Common setup and runtime issues, and how to fix them.
---

| Symptom | Try this |
| --- | --- |
| `Python not found` | Install Python 3.11+ from [python.org](https://www.python.org/downloads/) and open a new terminal |
| Windows cannot find Python | Reinstall Python and check "Add Python to PATH" on the first installer screen |
| `localhost:8000` will not load | Make sure the terminal running `python run.py` or the start script is still open |
| Browser does not open automatically | Visit `http://localhost:8000` manually |
| Port 8000 is busy | Stop the other local server or change the port in `run.py` |
| Market data looks empty | Check your internet connection and retry; Yahoo Finance requests can fail or rate-limit |
| AI shows Local mode | Add a valid Anthropic key through the dashboard key panel or `.env` |
| Claude request fails | Confirm the key starts with `sk-ant-`, has account credit/access, and restart if you edited `.env` manually |
| Pylint command fails on Windows | Use Git Bash, WSL, or run `pylint app tests run.py` |
| Senpai stopped talking | It's probably hidden — check the overflow menu's Intelligence section and toggle it back on |

## FAQ

**Does FolioSenseAI place trades or connect to a brokerage?**
No. It's for understanding portfolio state and context, not execution.

**Is this financial advice?**
No. Verdicts and action plans are analytical output, not investment advice.

**Do I need a Claude API key to use it?**
No. Local Intelligence covers verdicts, scenarios, exposure, and fallback summaries
without one. A key unlocks narration, action plan thesis text, and news themes on top.

**Where is my data stored?**
Locally, in SQLite under `database/`, and in a local `.env` file. Neither leaves your
machine except for the explicit Yahoo Finance and (optional) Anthropic calls described in
[Privacy & Data Handling](/privacy/).
