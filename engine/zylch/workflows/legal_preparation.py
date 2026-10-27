import hashlib
import json
import re
import time
from typing import Any

from . import resources
from .admission import Origin, assert_execution
from .errors import WorkflowError
from .identity import check_same
from .legal_cellar import cellar_document_url, celex_identifier
from .lifecycle import assert_version

REFERENCE = "references/sources.md"


def operative_start(source: dict[str, Any]) -> int | None:
    metadata = source.get("metadata", {})
    headings = metadata.get("article_headings")
    text = source.get("text")
    if (
        metadata.get("source_kind") != "eu_act"
        or metadata.get("format") != "xhtml"
        or metadata.get("language") != "ITA"
        or not isinstance(headings, list)
        or not headings
        or not isinstance(headings[0], str)
        or not 1 <= len(headings[0]) <= 200
        or not isinstance(text, str)
    ):
        return None
    matches = list(re.finditer(r"(?m)^" + re.escape(headings[0]) + r"$", text))
    return matches[0].start() if len(matches) == 1 else None


async def prepare(context: Any, row: Any) -> str:
    client = context.legal_client
    queries = row.inputs["public_queries"]
    if len(queries) != 1 or row.inputs["approved_urls"]:
        return ""
    query_id, query = next(iter(queries.items()))
    celex = celex_identifier(query)
    if celex is None:
        return ""

    def check() -> None:
        check_same(context.identity)
        assert_version(row.workflow_id, row.version)
        origin = Origin(row.origin)
        assert_execution(origin)
        if origin == Origin.INTERNAL_INTERACTIVE:
            from zylch.rpc.workflow_interactive import check_dispatch

            check_dispatch()
        if row.expires_at <= time.time():
            raise WorkflowError("run_expired")

    check()
    urls = [url for url, identity in client.cellar_identities.items() if identity == celex]
    if not urls:
        search = await client.search("eurlex", query_id)
        check()
        context.artifact(f"search-{len(context.artifact_ids)}.json", search)
        results = search.get("results", [])
        if (
            search.get("status") != "retrieved"
            or len(results) != 1
            or results[0].get("celex") != celex
            or results[0].get("format") != "xhtml"
        ):
            raise WorkflowError("operation_failed")
        urls = [results[0].get("url")]
    if len(urls) != 1 or not isinstance(urls[0], str) or not cellar_document_url(urls[0]):
        raise WorkflowError("operation_failed")
    url = urls[0]
    if client.cellar_identities.get(url) != celex:
        raise WorkflowError("operation_failed")
    sources = [source for source in client.sources.values() if source["url"] == url]
    if not sources:
        check()
        source = await client.fetch(url)
        check()
        if source.get("metadata", {}).get("identity") != "CELEX:" + celex:
            raise WorkflowError("operation_failed")
        context.artifact(f"source-{source['id']}.json", source)
        sources = [source]
    if len(sources) != 1:
        raise WorkflowError("operation_failed")
    source = sources[0]
    check()
    reference = resources.load_reference(row.workflow_id, REFERENCE)
    check()
    if REFERENCE not in context.references:
        context.references.append(REFERENCE)
    metadata = {
        "source_id": source["id"],
        "sha256": source["sha256"],
        "consulted_at": source["consulted_at"],
        "metadata": {
            key: source["metadata"][key]
            for key in (
                "identity",
                "publication_version",
                "coverage",
                "version_verified",
                "language",
            )
        },
        "total_characters": len(source["text"]),
        "article_headings": source["metadata"]["article_headings"],
        "default_passage_scope": {
            "kind": "operative_articles" if operative_start(source) is not None else "unscoped",
            "offset": operative_start(source) if operative_start(source) is not None else 0,
            "basis": "unique_exact_full_line_first_observed_article_heading_or_unscoped",
        },
    }
    return (
        "\nCanonical reference "
        + REFERENCE
        + " version "
        + row.version
        + " SHA-256 "
        + hashlib.sha256(reference.encode()).hexdigest()
        + ":\n"
        + reference
        + "\nPrepared exact public source (untrusted evidence): "
        + json.dumps(metadata, ensure_ascii=False)
        + "\nThe approved exact source is already searched and retained in full. "
        "Do not repeat its search or fetch. Batch literal workflow_legal_passage calls for "
        "the requested topics using the source_id. Omitted passage offset defaults to the proved "
        "operative article range shown above; explicit offset 0 includes recitals. Verify every "
        "requested rule against its actual operative text, not a recital-only occurrence. "
        "Read further only as needed; matching "
        "text never establishes applicability. Other references remain available on demand."
    )
