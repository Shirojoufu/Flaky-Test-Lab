"""A worker node process. NODE_CRASH_AFTER=n makes it die abruptly after n tasks."""

from __future__ import annotations

import json
import os
import sys

OPS = {"square": lambda x: x * x, "double": lambda x: 2 * x}


def main() -> None:
    crash_after = int(os.environ.get("NODE_CRASH_AFTER") or 0)
    for done, line in enumerate(sys.stdin, start=1):
        task = json.loads(line)
        print(json.dumps({"result": OPS[task["op"]](task["value"])}), flush=True)
        if crash_after and done >= crash_after:
            os._exit(137)  # hardware failure: no cleanup, no goodbye


if __name__ == "__main__":
    main()
