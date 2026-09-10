"""Lossless project-history merge, inside the company join transaction."""

from sqlalchemy import Connection, insert, inspect, select, update

from zylch.services.project_store import D, ProjectError, R, key


def merge_projects(source: Connection, destination: Connection) -> dict[str, int]:
    """Preflight every collision before writing. Matching history prefixes converge."""
    tables = set(inspect(source).get_table_names())
    present = {D.name, R.name} & tables
    if not present:
        return {"project_documents": 0, "project_revisions": 0}
    if present != {D.name, R.name}:
        raise ProjectError(-32040, "Project schema is incomplete; company join refused")
    source_docs = source.execute(select(D)).mappings().all()
    pending = []
    for document in source_docs:
        project, path = document["project"], document["path"]
        src = (
            source.execute(select(R).where(key(project, path, R)).order_by(R.c.revision))
            .mappings()
            .all()
        )
        dst = (
            destination.execute(select(R).where(key(project, path, R)).order_by(R.c.revision))
            .mappings()
            .all()
        )
        # A matching head alone is insufficient: older authored evidence must survive.
        if [r["revision"] for r in src] != list(range(1, document["revision"] + 1)):
            raise ProjectError(-32040, "Project history is incomplete; company join refused")
        for left, right in zip(src, dst):
            if any(left[name] != right[name] for name in tuple(column.name for column in R.c)):
                raise ProjectError(-32040, "Project histories diverge; company join refused")
        pending.append((project, path, src[len(dst) :], bool(dst)))
    copied_docs = copied_revisions = 0
    for project, path, revisions, exists in pending:
        if not revisions:
            continue
        destination.execute(insert(R), [dict(row) for row in revisions])
        latest = revisions[-1]["revision"]
        if exists:
            destination.execute(update(D).where(key(project, path)).values(revision=latest))
        else:
            destination.execute(insert(D).values(project=project, path=path, revision=latest))
            copied_docs += 1
        copied_revisions += len(revisions)
    return {"project_documents": copied_docs, "project_revisions": copied_revisions}
