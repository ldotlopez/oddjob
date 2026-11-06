#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = [
#     "platformdirs>=4.0",
#     "rich>=13.0",
# ]
# ///

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from glados.transcription.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
