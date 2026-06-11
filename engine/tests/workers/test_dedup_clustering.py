"""Clustering criteria of the F8 dedup sweep (pure build_clusters)."""

from zylch.workers.task_dedup_sweep import build_clusters


def _t(tid, contact=None, blobs=None, thread=None):
    return {
        "id": tid,
        "contact_email": contact,
        "sources": {"blobs": blobs or [], "thread_id": thread},
    }


def test_same_thread_id_clusters_even_without_contact():
    tasks = [
        _t("a", contact=None, thread="<x@mail>"),
        _t("b", contact=None, thread="<x@mail>"),
        _t("c", contact=None, thread="<y@mail>"),
    ]
    clusters = build_clusters(tasks)
    assert len(clusters) == 1
    assert {t["id"] for t in clusters[0]} == {"a", "b"}


def test_thread_and_contact_criteria_compose_transitively():
    # a~b share a thread, b~c share a contact → one cluster of 3
    tasks = [
        _t("a", contact="x@one.it", thread="<t1>"),
        _t("b", contact="simona@gmail.com", thread="<t1>"),
        _t("c", contact="simona@gmail.com", thread="<t2>"),
    ]
    clusters = build_clusters(tasks)
    assert len(clusters) == 1
    assert {t["id"] for t in clusters[0]} == {"a", "b", "c"}


def test_empty_thread_id_does_not_cluster():
    tasks = [
        _t("a", thread=""),
        _t("b", thread=""),
        _t("c", thread=None),
    ]
    assert build_clusters(tasks) == []
