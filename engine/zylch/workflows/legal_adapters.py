from datetime import date
import hashlib
from io import BytesIO
import re
from typing import Any
from urllib.parse import urljoin, urlsplit, parse_qs

from pypdf import PdfReader

from bs4 import BeautifulSoup

HOSTS = {
    "normattiva": "www.normattiva.it",
    "gazzetta": "www.gazzettaufficiale.it",
    "eurlex": "eur-lex.europa.eu",
    "giustizia": "www.giustizia-amministrativa.it",
}


RETRIEVAL_HOSTS = {
    **{host: site for site, host in HOSTS.items()},
    "mdp.giustizia-amministrativa.it": "giustizia",
    "publications.europa.eu": "eurlex",
}


def administrative_document_url(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != "mdp.giustizia-amministrativa.it":
        return False
    if parsed.path not in {"/visualizza/", "/visualizzah2/"}:
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    if set(query) != {"nodeRef", "schema", "nrg", "nomeFile", "subDir"} or any(
        len(value) != 1 for value in query.values()
    ):
        return False
    return bool(
        query["nodeRef"] == [""]
        and re.fullmatch(r"[a-z][a-z0-9_]{1,30}", query["schema"][0])
        and re.fullmatch(r"[0-9]{9}", query["nrg"][0])
        and re.fullmatch(r"[0-9]{9}_[0-9]{2}\.(?:pdf|html)", query["nomeFile"][0])
        and query["subDir"] == ["Provvedimenti"]
    )


def soup(content: bytes) -> BeautifulSoup:
    return BeautifulSoup(content, "html.parser")


def search_results(content: bytes, url: str, site: str) -> list[dict[str, str]]:
    page = soup(content)
    routes = {
        "normattiva": "/atto/caricaDettaglioAtto",
        "gazzetta": "/atto/",
        "eurlex": "/legal-content/",
        "giustizia": "/portale/pages/istituzionale/visualizza",
    }
    results: dict[str, dict[str, str]] = {}
    for link in page.select("a[href], a[onclick]"):
        href = str(link.get("href", "")).strip()
        target = urljoin(url, href)
        if site == "giustizia":
            if not administrative_document_url(target):
                continue
            title = link.get_text(" ", strip=True)
            if title or target not in results:
                results[target] = {"url": target, "title": title}
            continue
        if routes[site] not in href:
            continue
        results[target] = {"url": target, "title": link.get_text(" ", strip=True)}
    if site == "giustizia":
        for link in page.select("a[onclick]"):
            match = re.match(
                r"visualizzaProvvedimentoHighlighted\(\s*[\"']([^\"']+)[\"']",
                str(link.get("onclick", "")),
            )
            if match and administrative_document_url(match.group(1)):
                target = match.group(1)
                plain = target.replace("/visualizzah2/", "/visualizza/", 1)
                target = plain if plain in results else target
                results[target] = {"url": target, "title": link.get_text(" ", strip=True)}
    return list(results.values())[:50]


def normattiva_source_evidence(
    source: dict[str, Any], allowed_urls: set[str], max_bytes: int
) -> dict[str, Any]:
    url = source["url"]
    if url not in allowed_urls or source["site"] != "normattiva":
        raise ValueError
    encoded = source["original_bytes_hex"]
    if not isinstance(encoded, str) or len(encoded) > 2 * max_bytes:
        raise ValueError
    content = bytes.fromhex(encoded)
    digest = hashlib.sha256(content).hexdigest()
    if (
        source["sha256"] != digest
        or source["id"] != "source_" + digest[:24]
        or source["source_id"] != source["id"]
    ):
        raise ValueError
    return {
        "url": url,
        "original_bytes_hex": encoded,
        "sha256": digest,
        "source_id": source["id"],
    }


def normattiva_identity(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    if parsed.scheme != "https" or parsed.netloc != HOSTS["normattiva"]:
        return None
    fields = [
        query.get("atto.codiceRedazionale", []),
        query.get("atto.dataPubblicazioneGazzetta", []),
    ]
    if any(len(value) != 1 for value in fields):
        return None
    code, published = (value[0] for value in fields)
    if not re.fullmatch(r"[0-9A-Z]{8}", code) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", published):
        return None
    return code, published


def normattiva_detail(content: bytes, url: str) -> dict[str, Any] | None:
    identity = normattiva_identity(url)
    if identity is None or urlsplit(url).path != "/atto/caricaDettaglioAtto":
        return None
    page = soup(content)
    exports = []
    for link in page.select("a[href]"):
        target = urljoin(url, str(link["href"]))
        if (
            urlsplit(target).path == "/esporta/attoCompleto"
            and normattiva_identity(target) == identity
        ):
            exports.append(target)
    articles = []
    for link in page.select("a.numero_articolo"):
        match = re.search(r"showArticle\('([^']+)'", str(link.get("onclick", "")))
        label = re.sub(r"\s+", "-", link.get_text(" ", strip=True))
        if not match or not re.fullmatch(r"[0-9]+(?:-[a-z]+)?", label):
            return None
        article = urlsplit(urljoin(url, match.group(1)))
        if (
            article.scheme != "https"
            or article.netloc != HOSTS["normattiva"]
            or article.path != "/atto/caricaArticolo"
        ):
            return None
        query = parse_qs(article.query)
        if query.get("art.codiceRedazionale") != [identity[0]] or query.get(
            "art.dataPubblicazioneGazzetta"
        ) != [identity[1]]:
            return None
        articles.append("art_" + label)
    if not exports or not articles or len(articles) != len(set(articles)):
        return None
    title = page.title.get_text(" ", strip=True).removesuffix(" - Normattiva") if page.title else ""
    if not title:
        return None
    return {
        "identity": list(identity),
        "title": re.sub(r"\s+", "", title),
        "article_ids": articles,
        "export_urls": list(dict.fromkeys(exports)),
    }


def extract_normattiva_fullact(content: bytes, url: str, detail: dict[str, Any]) -> dict[str, Any]:
    empty = {"text": "", "metadata": {}, "related_urls": []}
    if (
        url not in detail["export_urls"]
        or list(normattiva_identity(url) or ()) != detail["identity"]
    ):
        return empty
    page = soup(content)
    node = page.select_one("#printThis")
    if node is None:
        return empty
    headings = node.select("h2.article-num-akn")
    if [str(h.get("id", "")) for h in headings] != detail["article_ids"]:
        return empty
    articles = []
    for heading in headings:
        block = heading.find_parent("div", class_="bodyTesto")
        bodies = (
            block.select(".art-commi-div-akn, .art-just-text-akn, .article-pre-comma-text-akn")
            if block
            else []
        )
        body = "\n".join(item.get_text("\n", strip=True) for item in bodies)
        label = heading.get_text(" ", strip=True)
        label_id = "art_" + re.sub(r"\s+", "-", label.removeprefix("Art.").strip())
        if (
            not body.strip()
            or len(block.select("h2.article-num-akn")) != 1
            or label_id != heading["id"]
        ):
            return empty
        articles.append(
            {
                "id": heading["id"],
                "label": heading.get_text(" ", strip=True),
                "explicit_abrogation": bool(re.search(r"ARTICOLO ABROGATO", body, re.I)),
            }
        )
    title = node.select_one("p.grassetto")
    marker = node.select_one("pre.rosso")
    marker_text = marker.get_text(" ", strip=True) if marker else ""
    match = re.fullmatch(r"Vigente al:\s*(\d{2})-(\d{2})-(\d{4})", marker_text)
    if (
        not title
        or re.sub(r"\s+", "", title.get_text()) != detail["title"]
        or not match
        or not any(item.get_text(strip=True) for item in node.select(".preamble-before-title-akn"))
        or not any(item.get_text(strip=True) for item in node.select(".conclusion-formula-akn"))
    ):
        return empty
    try:
        day, month, year = map(int, match.groups())
        snapshot = date(year, month, day).isoformat()
    except ValueError:
        return empty
    text = node.get_text("\n", strip=True)
    if re.search(
        r"captcha|verify you are human|access denied|temporaneamente non disponibile", text, re.I
    ):
        return empty
    return {
        "text": text,
        "metadata": {
            "identity": detail["identity"],
            "source_kind": "italian_act",
            "title": title.get_text(" ", strip=True),
            "coverage": "full_act_matching_detail_article_index",
            "article_ids": detail["article_ids"],
            "articles": articles,
            "portal_version_statement": marker_text,
            "portal_snapshot_date": snapshot,
            "version_verified": False,
        },
        "related_urls": [],
    }


def extract_source(content: bytes, url: str, site: str) -> dict[str, Any]:
    if content.startswith(b"%PDF-"):
        return extract_pdf(content, url, site)
    page = soup(content)
    for element in page.select("script, style, nav, header, footer, form"):
        element.decompose()
    if site != "normattiva":
        return extract_primary_html(page, url, site)
    selectors = {
        "normattiva": "#testoNormalizzato",
    }
    if site not in selectors:
        return {"text": "", "metadata": {}, "related_urls": []}
    node = page.select_one(selectors[site])
    if node is None:
        return {"text": "", "metadata": {}, "related_urls": []}
    text = node.get_text("\n", strip=True)
    metadata: dict[str, Any] = {"coverage": "retrieved_document_only", "version_verified": False}
    related: list[str] = []
    if site == "normattiva":
        metadata["coverage"] = "single_article_not_full_act"
        start = page.select_one("#artInizio")
        end = page.select_one("#artFine")
        for field, value in [("valid_from", start), ("valid_to", end)]:
            match = re.search(r"(\d{1,2})-(\d{1,2})-(\d{4})", value.get_text() if value else "")
            if match:
                day, month, year = map(int, match.groups())
                metadata[field] = date(year, month, day).isoformat()
        metadata["version_verified"] = "valid_from" in metadata
        metadata["version_date"] = metadata.get("valid_from")
        for link in page.select("[onclick]"):
            match = re.search(r"showArticle\('([^']+)'", str(link.get("onclick", "")))
            if match:
                related.append(urljoin(url, match.group(1)))
        for link in page.select("a[href]"):
            href = str(link.get("href", "")).strip()
            if "/atto/caricaDettaglioAtto?" in href:
                related.append(urljoin(url, href))
    detail = normattiva_detail(content, url)
    if detail is not None:
        metadata["normattiva_detail"] = detail
        related.extend(detail["export_urls"])
    return {"text": text, "metadata": metadata, "related_urls": list(dict.fromkeys(related))}


def administrative_form(content: bytes, url: str, query: str) -> tuple[str, dict[str, str]] | None:
    page = soup(content)
    for form in page.select("form[action]"):
        fields = {}
        for node in form.select("input[name], select[name], button[name][type=submit]"):
            if node.get("type") in ("radio", "checkbox") and not node.has_attr("checked"):
                continue
            if node.name == "select":
                selected = node.select_one("option[selected]") or node.select_one("option")
                value = str(selected.get("value", "")) if selected else ""
            else:
                value = str(node.get("value", ""))
            fields[str(node["name"])] = "" if value == "null" else value
        matches = [key for key in fields if key.endswith("searchtextProvvedimenti")]
        if matches:
            fields[matches[0]] = query
            return urljoin(url, str(form["action"])), fields
    return None


def identify_primary(text: str, url: str, site: str) -> dict[str, Any] | None:
    path = urlsplit(url).path
    query = parse_qs(urlsplit(url).query)
    if len(text) < 300 or re.search(
        r"captcha|verify you are human|access denied|temporaneamente non disponibile", text, re.I
    ):
        return None
    if site == "eurlex":
        if "/legal-content/" not in path or not re.search(r"REGOLAMENTO|DIRETTIVA|DECISIONE", text):
            return None
        if not re.search(r"Articolo\s+1\b", text) or not re.search(
            r"PARLAMENTO EUROPEO|CONSIGLIO|COMMISSIONE", text
        ):
            return None
        identity = query.get("uri", [""])[0]
        if not re.fullmatch(r"CELEX:[0-9A-Z-]{8,40}", identity):
            return None
        return {
            "identity": identity,
            "source_kind": "eu_act",
            "coverage": "identified_primary_text_completeness_unverified",
            "version_verified": False,
        }
    if site == "gazzetta":
        if "/atto/" not in path and "/eli/" not in path:
            return None
        if not re.search(r"Art\.?\s*\d+\b", text) or not re.search(
            r"LEGGE|DECRETO|ORDINANZA|REGOLAMENTO", text
        ):
            return None
        identity = query.get("atto.codiceRedazionale", [""])[0]
        if not identity:
            match = re.search(r"/eli/id/\d{4}/\d{2}/\d{2}/([^/]+)", path)
            identity = match.group(1) if match else ""
        if not identity:
            return None
        return {
            "identity": identity,
            "source_kind": "promulgated_act",
            "coverage": (
                "single_article_not_full_act"
                if "caricaArticolo" in path
                else "identified_primary_text_completeness_unverified"
            ),
            "version_verified": False,
        }
    if site == "giustizia":
        number = re.search(r"N\.?\s*(\d{3,8})\s*/\s*(\d{4})\s*REG\.?\s*PROV", text)
        compact = re.sub(r"\s+", "", text)
        if (
            not number
            or "REPUBBLICAITALIANA" not in compact
            or "INNOMEDELPOPOLOITALIANO" not in compact
        ):
            return None
        if not re.search(r"P\.?\s*Q\.?\s*M\.?", text) or not re.search(
            r"DEPOSITAT|Pubblicat", text, re.I
        ):
            return None
        return {
            "identity": f"{number.group(1)}/{number.group(2)}",
            "source_kind": "administrative_decision",
            "coverage": "decision_text_with_disposition_and_publication_marker",
            "version_verified": False,
        }
    return None


def extract_primary_html(page: BeautifulSoup, url: str, site: str) -> dict[str, Any]:
    node = page.select_one('main, article, [role="main"]') or page.body
    text = node.get_text("\n", strip=True) if node else ""
    metadata = identify_primary(text, url, site)
    if metadata is None:
        return {"text": "", "metadata": {}, "related_urls": []}
    metadata["extraction"] = "structural_primary_identity_checks_not_live_template_verified"
    return {"text": text, "metadata": metadata, "related_urls": []}


def extract_pdf(content: bytes, url: str, site: str) -> dict[str, Any]:
    try:
        reader = PdfReader(BytesIO(content), strict=True)
        if reader.is_encrypted or not 1 <= len(reader.pages) <= 200:
            return {"text": "", "metadata": {}, "related_urls": []}
        pages = []
        characters = 0
        for index, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            characters += len(text)
            if characters > 2_000_000 or len(text.strip()) < 20:
                return {"text": "", "metadata": {}, "related_urls": []}
            pages.append({"page": index + 1, "text": text})
        text = "\n\n".join(page["text"] for page in pages)
        metadata = identify_primary(text, url, site)
        if metadata is None:
            return {"text": "", "metadata": {}, "related_urls": []}
        metadata.update(
            format="pdf", pages=len(pages), extraction="all_pdf_pages_no_signature_verification"
        )
        return {"text": text, "metadata": metadata, "related_urls": [], "text_pages": pages}
    except Exception:
        return {"text": "", "metadata": {}, "related_urls": []}
