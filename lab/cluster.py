"""A tiny compute cluster: each worker node is a separate process fed tasks over a pipe."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from . import chaos

# Sometimes a machine in the pool dies mid-job: power loss, kernel panic, OOM kill.
NODE_FAILURE = chaos.fires("cluster.node_failure", 0.1)
ROOT = Path(__file__).resolve().parents[1]


class NodeFailure(RuntimeError):
    pass


class Cluster:
    def __init__(self, size: int = 3):
        self.nodes = []
        for index in range(size):
            env = {**os.environ, "PYTHONPATH": str(ROOT)}
            env["NODE_CRASH_AFTER"] = "1" if NODE_FAILURE and index == 1 else ""
            self.nodes.append(subprocess.Popen(
                [sys.executable, "-m", "lab.node"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=env, cwd=ROOT,
            ))

    def map(self, op: str, values) -> list:
        """Run ``op`` on each value, spreading tasks round-robin. No failover."""
        results = []
        for i, value in enumerate(values):
            node = self.nodes[i % len(self.nodes)]
            try:
                node.stdin.write(json.dumps({"op": op, "value": value}) + "\n")
                node.stdin.flush()
                line = node.stdout.readline()
            except (BrokenPipeError, OSError):
                line = ""
            if not line:
                raise NodeFailure(f"node {i % len(self.nodes)} died (exit code {node.wait()})")
            results.append(json.loads(line)["result"])
        return results

    def close(self) -> None:
        for node in self.nodes:
            try:
                node.stdin.close()
            except OSError:
                pass
            node.wait(timeout=5)

    def __enter__(self) -> Cluster:
        return self

    def __exit__(self, *exc) -> None:
        self.close()
