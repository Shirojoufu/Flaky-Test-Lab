"""Flaky: hardware failure. A worker node process dies mid-job and the cluster has no failover."""

from lab.cluster import Cluster


def test_map_across_nodes():
    with Cluster(size=3) as cluster:
        assert cluster.map("square", range(9)) == [x * x for x in range(9)]
