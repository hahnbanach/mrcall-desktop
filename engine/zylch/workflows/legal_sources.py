import asyncio
from datetime import datetime, timezone
import hashlib
import ipaddress
import socket
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from zylch.qonto.logging import private_scope
from .legal_cellar import (
    CELLAR_HOST,
    cellar_document_url,
    cellar_query_url,
    cellar_results,
    celex_identifier,
    extract_cellar,
    valid_search_url,
)
from .errors import WorkflowError
from .legal_adapters import (
    HOSTS,
    RETRIEVAL_HOSTS,
    administrative_document_url,
    administrative_form,
    extract_source,
    extract_normattiva_fullact,
    normattiva_detail,
    normattiva_identity,
    normattiva_source_evidence,
    search_results,
)

MAX_BYTES = 4 * 1024 * 1024
MAX_REQUESTS = 100
SUPPORTED_SEARCH_SITES = frozenset({"normattiva", "eurlex", "giustizia"})
SOURCE_CAPABILITIES = {
    site: {
        "search": site in SUPPORTED_SEARCH_SITES,
        "retrieval": True,
        "mode": "search_and_retrieval" if site in SUPPORTED_SEARCH_SITES else "retrieval_only",
    }
    for site in HOSTS
}


def validate_url(url: str, *, internal_celex: str | None = None) -> str:
    try:
        parsed = urlsplit(url)
        if (
            len(url) > 4096
            or parsed.scheme != "https"
            or parsed.hostname not in RETRIEVAL_HOSTS
            or parsed.port not in (None, 443)
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise ValueError
        if internal_celex is not None and not valid_search_url(url, internal_celex):
            raise ValueError
        if not parsed.path.startswith("/"):
            raise ValueError
        if (
            parsed.hostname == "mdp.giustizia-amministrativa.it"
            and not administrative_document_url(url)
        ):
            raise ValueError
        if parsed.hostname == CELLAR_HOST and not (
            cellar_document_url(url)
            or (internal_celex is not None and valid_search_url(url, internal_celex))
        ):
            raise ValueError
        return str(parsed.hostname)
    except (ValueError, TypeError):
        raise WorkflowError("invalid_input") from None


async def public_dns(host: str) -> None:
    try:
        addresses = await asyncio.get_running_loop().getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        if not addresses or any(
            not ipaddress.ip_address(item[4][0]).is_global for item in addresses
        ):
            raise ValueError
    except (OSError, ValueError):
        raise WorkflowError("operation_failed") from None


class LegalSourceClient:
    def __init__(
        self,
        public_queries: dict[str, str] | None = None,
        approved_public_queries: list[str] | None = None,
        approved_urls: list[str] | None = None,
    ) -> None:
        if public_queries is None:
            public_queries = {f"q{i + 1}": q for i, q in enumerate(approved_public_queries or [])}
        if (
            not isinstance(public_queries, dict)
            or len(public_queries) > 20
            or any(
                not isinstance(k, str) or not isinstance(v, str) or not 1 <= len(v) <= 300
                for k, v in public_queries.items()
            )
        ):
            raise WorkflowError("invalid_input")
        self.public_queries = dict(public_queries)
        self.allowed_urls = set(approved_urls or [])
        if len(self.allowed_urls) > 50:
            raise WorkflowError("invalid_input")
        for url in self.allowed_urls:
            validate_url(url)
        self.cellar_identities: dict[str, str] = {}
        self.normattiva_exports: dict[str, dict[str, Any]] = {}
        self.normattiva_reprime: set[str] = set()
        self.sources: dict[str, dict[str, Any]] = {}
        self.requests = 0
        self.retained_bytes = 0
        self.client = httpx.AsyncClient(timeout=20, follow_redirects=False)

    async def close(self) -> None:
        await self.client.aclose()

    async def _request(
        self,
        method: str,
        url: str,
        data: dict[str, str] | None = None,
        *,
        internal_celex: str | None = None,
        internal_normattiva: tuple[str, str] | None = None,
    ) -> tuple[bytes, str]:
        with private_scope():
            try:
                for _ in range(6):
                    host = validate_url(url, internal_celex=internal_celex)
                    if internal_normattiva is not None and (
                        normattiva_identity(url) != internal_normattiva
                        or urlsplit(url).path != "/esporta/attoCompleto"
                    ):
                        raise WorkflowError("invalid_input")
                    await public_dns(host)
                    self.requests += 1
                    if self.requests > MAX_REQUESTS:
                        raise WorkflowError("quota_exceeded")
                    async with self.client.stream(method, url, data=data) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            url = urljoin(url, response.headers.get("location", ""))
                            validate_url(url, internal_celex=internal_celex)
                            if internal_celex is not None and not valid_search_url(
                                url, internal_celex
                            ):
                                raise WorkflowError("invalid_input")
                            if response.status_code in (301, 302, 303):
                                method, data = "GET", None
                            continue
                        if response.status_code != 200:
                            raise WorkflowError("operation_failed")
                        if (
                            internal_celex is not None
                            and response.headers.get("content-type", "").split(";", 1)[0]
                            != "application/sparql-results+json"
                        ):
                            raise WorkflowError("operation_failed")
                        payload = bytearray()
                        async for block in response.aiter_bytes():
                            payload.extend(block)
                            if len(payload) > MAX_BYTES:
                                raise WorkflowError("quota_exceeded")
                        if not payload:
                            raise WorkflowError("operation_failed")
                        self.retained_bytes += len(payload)
                        if self.retained_bytes > 20 * 1024 * 1024:
                            raise WorkflowError("quota_exceeded")
                        return bytes(payload), str(response.url)
                raise WorkflowError("operation_failed")
            except WorkflowError:
                raise
            except Exception:
                raise WorkflowError("operation_failed") from None

    async def search(self, site: str, query_id: str, page: int = 1) -> dict[str, Any]:
        if (
            site not in HOSTS
            or query_id not in self.public_queries
            or type(page) is not int
            or page != 1
        ):
            raise WorkflowError("invalid_input")
        if site not in SUPPORTED_SEARCH_SITES:
            raise WorkflowError("unsupported_search")
        query = self.public_queries[query_id]
        root = f"https://{HOSTS[site]}"
        with private_scope():
            try:
                if site == "normattiva":
                    await self._request("GET", root + "/")
                    content, url = await self._request(
                        "POST",
                        root + "/ricerca/veloce/0",
                        {
                            "testoRicerca": query,
                            "tabID": "engine-workflow",
                            "title": "lbl.risultatoRicerca",
                        },
                    )
                elif site == "eurlex" and (celex := celex_identifier(query)) is not None:
                    content, url = await self._request(
                        "GET", cellar_query_url(celex), internal_celex=celex
                    )
                    results = cellar_results(content, celex)
                    for result in results:
                        previous = self.cellar_identities.get(result["url"])
                        if previous is not None and previous != celex:
                            raise WorkflowError("operation_failed")
                    self.cellar_identities.update({result["url"]: celex for result in results})
                elif site == "eurlex":
                    url = str(
                        httpx.URL(
                            root + "/search.html",
                            params={
                                "scope": "EURLEX",
                                "text": query,
                                "lang": "it",
                                "type": "quick",
                            },
                        )
                    )
                    content, url = await self._request("GET", url)
                elif site == "giustizia":
                    content, url = await self._request("GET", root + "/web/guest/dcsnprr")
                    form = administrative_form(content, url, query)
                    if form is None:
                        raise WorkflowError("operation_failed")
                    content, url = await self._request("POST", form[0], form[1])
                if not (site == "eurlex" and celex_identifier(query) is not None):
                    results = search_results(content, url, site)
                if not results:
                    return {"site": site, "status": "retrieval_unavailable", "results": []}
                for result in results:
                    validate_url(result["url"])
                    self.allowed_urls.add(result["url"])
                return {
                    **(
                        {
                            "cellar_evidence": {
                                "query_id": query_id,
                                "celex": celex,
                                "endpoint": cellar_query_url(celex),
                                "response_original_hex": content.hex(),
                                "response_sha256": hashlib.sha256(content).hexdigest(),
                            }
                        }
                        if site == "eurlex" and celex_identifier(query) is not None
                        else {}
                    ),
                    "site": site,
                    "status": "retrieved",
                    "results": results,
                    "page": 1,
                    "coverage": (
                        "bounded_five_bindings_italian_xhtml_only_not_exhaustive"
                        if site == "eurlex" and celex_identifier(query) is not None
                        else "first_page_only_not_exhaustive"
                    ),
                }
            except WorkflowError as exc:
                return {
                    "site": site,
                    "status": "retrieval_unavailable",
                    "results": [],
                    "outcome": exc.outcome,
                }

    def restore_search(self, search: dict[str, Any]) -> None:
        try:
            results = search["results"]
            if not isinstance(results, list):
                raise ValueError
            evidence = search.get("cellar_evidence")
            cellar_urls = [
                item["url"] for item in results if urlsplit(item["url"]).hostname == CELLAR_HOST
            ]
            if evidence is None:
                if cellar_urls:
                    raise ValueError
                for item in results:
                    validate_url(item["url"])
                self.allowed_urls.update(item["url"] for item in results)
                return
            if (
                not isinstance(evidence, dict)
                or set(evidence)
                != {"query_id", "celex", "endpoint", "response_original_hex", "response_sha256"}
                or search["site"] != "eurlex"
                or search["status"] != "retrieved"
                or type(search["page"]) is not int
                or search["page"] != 1
                or search["coverage"] != "bounded_five_bindings_italian_xhtml_only_not_exhaustive"
                or evidence["query_id"] not in self.public_queries
            ):
                raise ValueError
            celex = celex_identifier(self.public_queries[evidence["query_id"]])
            if (
                celex is None
                or celex != evidence["celex"]
                or evidence["endpoint"] != cellar_query_url(celex)
            ):
                raise ValueError
            encoded = evidence["response_original_hex"]
            if not isinstance(encoded, str) or len(encoded) > 2 * 65536:
                raise ValueError
            content = bytes.fromhex(encoded)
            if hashlib.sha256(content).hexdigest() != evidence["response_sha256"]:
                raise ValueError
            if cellar_results(content, celex) != results or not results:
                raise ValueError
            for result in results:
                previous = self.cellar_identities.get(result["url"])
                if previous is not None and previous != celex:
                    raise ValueError
            self.cellar_identities.update({result["url"]: celex for result in results})
            self.allowed_urls.update(result["url"] for result in results)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise WorkflowError("operation_failed") from None

    def _normattiva_evidence(self, source: dict[str, Any]) -> dict[str, Any]:
        return normattiva_source_evidence(source, self.allowed_urls, MAX_BYTES)

    def _bind_normattiva_detail(
        self, evidence: dict[str, Any], *, restored: bool = False, bind: bool = True
    ) -> dict[str, Any]:
        url = evidence["url"]
        if url not in self.allowed_urls:
            raise ValueError
        encoded = evidence["original_bytes_hex"]
        if not isinstance(encoded, str) or len(encoded) > 2 * MAX_BYTES:
            raise ValueError
        content = bytes.fromhex(encoded)
        digest = hashlib.sha256(content).hexdigest()
        detail = normattiva_detail(content, url)
        if (
            detail is None
            or evidence["sha256"] != digest
            or evidence["source_id"] != "source_" + digest[:24]
        ):
            raise ValueError
        if not bind:
            return detail
        for export in detail["export_urls"]:
            validate_url(export)
            self.normattiva_exports[export] = evidence
            self.allowed_urls.add(export)
            if restored:
                self.normattiva_reprime.add(export)
        return detail

    def restore_source(self, source: dict[str, Any]) -> None:
        try:
            url = source["url"]
            host = validate_url(url)
            if host == HOSTS["normattiva"]:
                evidence = self._normattiva_evidence(source)
                content = bytes.fromhex(evidence["original_bytes_hex"])
                if urlsplit(url).path == "/esporta/attoCompleto":
                    detail_evidence = source["normattiva_detail_evidence"]
                    detail = self._bind_normattiva_detail(detail_evidence, bind=False)
                    extracted = extract_normattiva_fullact(content, url, detail)
                else:
                    extracted = extract_source(content, url, "normattiva")
                if not extracted["text"] or any(
                    source[key] != extracted[key] for key in ("text", "metadata", "related_urls")
                ):
                    raise ValueError
                if source.get("text_pages", []) != []:
                    raise ValueError
                if urlsplit(url).path == "/esporta/attoCompleto":
                    self._bind_normattiva_detail(detail_evidence, restored=True)
                if extracted["metadata"].get("normattiva_detail") is not None:
                    self._bind_normattiva_detail(evidence, restored=True)
            if host == CELLAR_HOST:
                celex = self.cellar_identities.get(url)
                if celex is None or source["site"] != "eurlex":
                    raise ValueError
                content = bytes.fromhex(source["original_bytes_hex"])
                digest = hashlib.sha256(content).hexdigest()
                extracted = extract_cellar(content, celex)
                if (
                    source["sha256"] != digest
                    or source["id"] != "source_" + digest[:24]
                    or source["source_id"] != source["id"]
                    or source["text"] != extracted["text"]
                    or source["metadata"] != extracted["metadata"]
                    or source["related_urls"] != []
                ):
                    raise ValueError
            for related in source.get("related_urls", []):
                validate_url(related)
            self.sources[source["id"]] = source
            self.allowed_urls.update([url, *source.get("related_urls", [])])
        except (KeyError, TypeError, ValueError, AttributeError):
            raise WorkflowError("operation_failed") from None

    async def fetch(self, url: str) -> dict[str, Any]:
        if url not in self.allowed_urls:
            raise WorkflowError("invalid_input")
        host = validate_url(url)
        site = RETRIEVAL_HOSTS[host]
        celex = self.cellar_identities.get(url)
        if host == CELLAR_HOST and celex is None:
            raise WorkflowError("invalid_input")
        detail_evidence = self.normattiva_exports.get(url)
        detail = None
        if site == "normattiva" and urlsplit(url).path == "/esporta/attoCompleto":
            if detail_evidence is None:
                raise WorkflowError("invalid_input")
            detail = normattiva_detail(
                bytes.fromhex(detail_evidence["original_bytes_hex"]), detail_evidence["url"]
            )
            if url in self.normattiva_reprime:
                primed, primed_url = await self._request("GET", detail_evidence["url"])
                if (
                    primed_url != detail_evidence["url"]
                    or normattiva_detail(primed, primed_url) != detail
                ):
                    raise WorkflowError("operation_failed")
                self.normattiva_reprime.remove(url)
            content, final_url = await self._request(
                "GET", url, internal_normattiva=tuple(detail["identity"])
            )
        else:
            content, final_url = await self._request("GET", url)
        with private_scope():
            if celex is not None:
                if final_url != url:
                    raise WorkflowError("operation_failed")
                extracted = extract_cellar(content, celex)
            elif detail is not None:
                extracted = extract_normattiva_fullact(content, final_url, detail)
            else:
                if (
                    site == "normattiva"
                    and normattiva_identity(url) is not None
                    and normattiva_identity(final_url) != normattiva_identity(url)
                ):
                    raise WorkflowError("operation_failed")
                extracted = extract_source(content, final_url, site)
        if not extracted["text"]:
            raise WorkflowError("operation_failed")
        for related in extracted["related_urls"]:
            validate_url(related)
            self.allowed_urls.add(related)
        digest = hashlib.sha256(content).hexdigest()
        source_id = "source_" + digest[:24]
        record = {
            "source_id": source_id,
            "id": source_id,
            "url": final_url,
            "site": site,
            "sha256": digest,
            "consulted_at": datetime.now(timezone.utc).isoformat(),
            "original_bytes_hex": content.hex(),
            "text": extracted["text"],
            "metadata": extracted["metadata"],
            "text_pages": extracted.get("text_pages", []),
            "related_urls": extracted["related_urls"],
        }
        if detail_evidence is not None:
            record["normattiva_detail_evidence"] = detail_evidence
        if extracted["metadata"].get("normattiva_detail") is not None:
            self._bind_normattiva_detail(self._normattiva_evidence(record))
        self.sources[source_id] = record
        return record

    async def read(self, source_id: str, offset: int = 0, limit: int = 12000) -> dict[str, Any]:
        if (
            source_id not in self.sources
            or type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= 12000
        ):
            raise WorkflowError("invalid_input")
        text = self.sources[source_id]["text"]
        return {
            "source_id": source_id,
            "offset": offset,
            "text": text[offset : offset + limit],
            "total_characters": len(text),
            "next_offset": offset + limit if offset + limit < len(text) else None,
        }
