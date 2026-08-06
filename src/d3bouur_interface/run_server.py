#!/usr/bin/env python3
"""Run the D3BOUUR web interface locally.

Run from this directory (no colcon build needed, same convention as
d3bouur_conversation/demo_chat.py and d3bouur_behavior/demo_state_machine.py):

    python3 run_server.py

Then open http://localhost:8000 in a browser (or, from Windows against this
WSL2 machine, see the README in this folder for the one extra step needed).
"""

import uvicorn

from d3bouur_interface import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
