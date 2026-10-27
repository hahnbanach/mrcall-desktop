import json
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
from bs4 import BeautifulSoup

from .errors import WorkflowError

CELLAR_HOST = "publications.europa.eu"
CELLAR_ENDPOINT = f"https://{CELLAR_HOST}/webapi/rdf/sparql"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
BASE = f"http://{CELLAR_HOST}/resource/cellar/"
FIELDS = {"work", "expr", "manif", "langCode", "format", "item"}


def celex_identifier(value: str) -> str | None:
    value = value.removeprefix("CELEX:")
    return value if re.fullmatch(r"3(?:19|20)[0-9]{2}[RL][0-9]{4}", value) else None


def cellar_document_url(url: str) -> bool:
    parsed = urlsplit(url)
    return bool(
        parsed.scheme == "https"
        and parsed.hostname == CELLAR_HOST
        and parsed.port in (None, 443)
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment
        and re.fullmatch(
            rf"/resource/cellar/{UUID}\.[0-9]{{4}}\.[0-9]{{2}}/DOC_[1-9][0-9]{{0,2}}", parsed.path
        )
    )


def cellar_query_url(celex: str) -> str:
    if celex_identifier(celex) != celex:
        raise WorkflowError("invalid_input")
    query = (
        "prefix cdm: <http://publications.europa.eu/ontology/cdm#> \r\n"
        "prefix purl: <http://purl.org/dc/elements/1.1/> \r\n"
        "select distinct ?work, ?expr, ?manif, ?langCode, str(?format) as ?format, ?item \r\n"
        "where {\r\n"
        f"?work owl:sameAs <http://publications.europa.eu/resource/celex/{celex}> .\r\n"
        "?expr cdm:expression_belongs_to_work ?work ;\r\n"
        "cdm:expression_uses_language ?lang .\r\n"
        "?lang purl:identifier ?langCode .\r\n"
        "?manif cdm:manifestation_manifests_expression ?expr;\r\n"
        "cdm:manifestation_type ?format.\r\n"
        "?item cdm:item_belongs_to_manifestation ?manif.\r\n"
        'FILTER(str(?langCode)="ITA")\r\n'
        "} LIMIT 5\r\n"
    )
    return str(
        httpx.URL(
            CELLAR_ENDPOINT, params={"query": query, "format": "application/sparql-results+json"}
        )
    )


def valid_search_url(url: str, celex: str) -> bool:
    return url == cellar_query_url(celex) and set(parse_qs(urlsplit(url).query)) == {
        "query",
        "format",
    }


def cellar_results(content: bytes, celex: str) -> list[dict[str, str]]:
    if celex_identifier(celex) != celex:
        raise WorkflowError("invalid_input")
    try:
        if len(content) > 65536:
            raise ValueError
        document = json.loads(content)
        if not isinstance(document, dict) or set(document["head"]["vars"]) != FIELDS:
            raise ValueError
        bindings = document["results"]["bindings"]
        if not isinstance(bindings, list) or len(bindings) > 5:
            raise ValueError
        results = {}
        for binding in bindings:
            if not isinstance(binding, dict) or set(binding) != FIELDS:
                raise ValueError
            values = {}
            for field in FIELDS:
                term = binding[field]
                expected = "literal" if field in {"langCode", "format"} else "uri"
                if (
                    not isinstance(term, dict)
                    or set(term) != {"type", "value"}
                    or term["type"] != expected
                    or not isinstance(term["value"], str)
                ):
                    raise ValueError
                values[field] = term["value"]
            work, expr, manifestation, item = (values[k] for k in ("work", "expr", "manif", "item"))
            if (
                not re.fullmatch(re.escape(BASE) + UUID, work)
                or not re.fullmatch(re.escape(work) + r"\.[0-9]{4}", expr)
                or not re.fullmatch(re.escape(expr) + r"\.[0-9]{2}", manifestation)
                or not re.fullmatch(re.escape(manifestation) + r"/DOC_[1-9][0-9]{0,2}", item)
                or values["langCode"] != "ITA"
                or values["format"] not in {"xhtml", "pdfa1a", "fmx4"}
            ):
                raise ValueError
            if values["format"] == "xhtml":
                url = "https:" + item.removeprefix("http:")
                if not cellar_document_url(url):
                    raise ValueError
                results[url] = {
                    "url": url,
                    "title": f"CELEX:{celex} — Italian original publication (XHTML)",
                    "celex": celex,
                    "format": "xhtml",
                }
        return list(results.values())
    except (KeyError, TypeError, ValueError, RecursionError):
        raise WorkflowError("operation_failed") from None


def extract_cellar(content: bytes, celex: str) -> dict[str, Any]:
    if celex_identifier(celex) != celex:
        raise WorkflowError("invalid_input")
    page = BeautifulSoup(content, "html.parser")
    title = page.select_one(".oj-doc-ti")
    text = page.body.get_text("\n", strip=True) if page.body else ""
    kind = {"R": "REGOLAMENTO", "L": "DIRETTIVA"}[celex[5]]
    identity = rf"{kind}\s+\(UE\)\s+(?:n\.\s*)?{celex[1:5]}/{int(celex[6:])}\b"
    if (
        not title
        or not re.search(identity, title.get_text(" ", strip=True), re.I)
        or not re.search(
            r"PARLAMENTO EUROPEO|CONSIGLIO|COMMISSIONE", title.get_text(" ", strip=True)
        )
        or not page.select_one(".oj-ti-art")
        or not re.search(r"Articolo\s+1\b", text)
        or len(text) < 300
        or len(text) > 2_000_000
        or re.search(r"captcha|verify you are human|access denied", text, re.I)
    ):
        raise WorkflowError("operation_failed")
    headings = [node.get_text(" ", strip=True) for node in page.select(".oj-ti-art")]
    return {
        "text": text,
        "related_urls": [],
        "metadata": {
            "identity": f"CELEX:{celex}",
            "source_kind": "eu_act",
            "repository": "official_publications_office_cellar",
            "format": "xhtml",
            "language": "ITA",
            "publication_version": "original_publication_not_consolidated",
            "coverage": "identified_primary_text_completeness_unverified",
            "version_verified": False,
            "extraction": "observed_official_xhtml_title_and_article_structure",
            "article_headings": headings,
        },
    }
