"""Validated source selections for company telephone notes."""

import json
import re
import unicodedata
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MAX_CONTEXT_CHARS = 2_000

_DENIED = re.compile(
    r"(?i)(?:@|https?://|\b(?:e-?mail|firma|signature|persona|prompt|system|"
    r"instruction|istruzion|scrivi|rispondi|password|secret|token|"
    r"api.?key|credential|credenzial|\bcost\b|\bcost[oi]\b|margin|margine|"
    r"prezz|price|"
    r"tariff|quotazion|€|\$|£|\beuros?\b|\bdollars?\b|\bmoq\b|minimum|"
    r"quantit[aà] minim|volume minim|lead time|tempi di consegna|"
    r"giorni lavorativi|consegna entro|delivery within|\b\d+(?:[.,]\d+)?\s*"
    r"(?:pcs|pieces|units?|pezzi|giorni?|days?|weeks?|settimane|mesi|months?|"
    r"hours?|ore)\b|%|\b(?:[a-z0-9-]+\.)+(?:it|com|eu|org|net)\b))"
)
_INSTRUCTION = re.compile(
    r"(?i)\b(?:disregard|ignore|forget|override|bypass|pretend|obey|"
    r"tell\s+(?:callers?|customers?|people|the\s+caller)|"
    r"say\s+(?:to|that)|do\s+not\s+(?:tell|mention|disclose)|"
    r"(?:reply|response|answer|risposta|replica)\b[^.!?\n]{0,50}\b"
    r"(?:brief|short|concise|breve|corta|sintetica|concisa)|"
    r"(?:suggest|recommend|advise|sugger\w*|consigli\w*|raccomand\w*)"
    r"\b[^.!?\n]{0,100}\b(?:scroll\w*|select(?:ing)?|choose|scorr\w*|"
    r"selezion\w*|scegl\w*)|"
    r"(?:how\s+to|come)\s+(?:handle|manage|process|gestire|trattare)|"
    r"(?:do\s+not|don't|non)\s+(?:invent|reuse|inventare|riusare|riutilizzare|riciclare)|"
    r"(?:explain|spiega(?:re)?)\s+(?:that|che)|"
    r"(?:first|then|prima|poi|quindi)\s+(?:gather|collect|propose|explain|enter|insert|"
    r"raccogli(?:ere)?|proponi|proporre|spiega(?:re)?|inserisci|inserire)|"
    r"ignora|fingi|devi|dovete|clicca|cliccare|seleziona|tocca|"
    r"tap|click|naviga|carrello|menu|non\s+(?:dire|menzionare)|"
    r"d[iì]\s+(?:al|ai|alla|alle)|"
    r"(?:create|open|assign|track|update|close|complete|record|creare|crea|aprire|apri|"
    r"assegnare|assegna|tracciare|registrare|aggiornare|chiudere|completare)"
    r"\b[^.!?\n]{0,60}\b(?:tasks?|work[- ]?items?|to[- ]?do)|"
    r"(?:tasks?|work[- ]?items?|to[- ]?do)\b[^.!?\n]{0,60}\b"
    r"(?:created|assigned|tracked|updated|closed|completed|creat[oaie]|assegnat[oaie]|"
    r"tracciat[oaie]|registrat[oaie]|aggiornat[oaie]|chius[oaie]|completat[oaie])|"
    r"(?:operator[si]?|operatore|operatori|staff)\s+(?:must|should|shall|deve|devono)|"
    r"(?:mark(?:ed)?|flag(?:ged)?|consider(?:ed)?|record(?:ed)?|set)\b"
    r"[^.!?\n]{0,80}\b(?:complete|completed|closed)|"
    r"(?:considerat[oaie]|considera(?:no)?|considerare|segnat[oaie]|registrat[oaie])"
    r"\b[^.!?\n]{0,40}\b"
    r"(?:completat[oaie]|conclus[oaie]|chius[oaie])|"
    r"(?:must|should|shall|need\s+to)\s+(?:check|verify|record|track|update|close|complete)|"
    r"(?:bisogna|occorre|deve|devono|va|vanno)\s+(?:verificar[ei]|controllar[ei]|"
    r"registrar[ei]|tracciar[ei]|aggiornar[ei]|chiuder[ei]|completar[ei]))\b|"
    r"(?:^|[.!?:]\s+|\n\s*[-*]?\s*)(?:check|verify|record|track|update|assign|close|"
    r"complete|gather|collect|propose|explain|enter|insert|verificare|controllare|"
    r"registrare|tracciare|aggiornare|assegnare|chiudere|completare|ricontattare|"
    r"archiviare|raccogli(?:ere)?|proponi|proporre|spiega(?:re)?|inserisci|inserire)\b"
)
_NONPUBLIC = re.compile(
    r"(?i)\b(?:(?:co[- ]?)?founders?|staff|personnel|fondator[ei]|fondatric[ei]|"
    r"soci(?:\s+fondatori)?|titolari)\s*:|"
    r"\b(?:variants?|options?|offers?|services?|products?|varianti|opzioni|offerte|"
    r"servizi|prodotti|formati)\s+(?:observed|seen|recorded|historical|previous|past|"
    r"vist[oaie]|osservat[oaie]|riscontrat[oaie]|precedent[ei]|storic[oaie])\b|"
    r"\b(?:observed|seen|recorded|historical|previous|past|vist[oaie]|osservat[oaie]|"
    r"precedent[ei]|storic[oaie])\s+(?:variants?|options?|offers?|services?|products?|"
    r"varianti|opzioni|offerte|servizi|prodotti|formati)\b|"
    r"\b(?:previously|historically|formerly)\s+(?:offered|supplied|provided|available)\b|"
    r"\b(?:might|may|could)\s+be\s+(?:offered|available|provided)\b|"
    r"\b(?:forse|eventualmente)\s+(?:disponibile|disponibili|offerto|offerti)\b"
)
_GAPS = {
    "price": "Public price unavailable",
    "minimum_volume": "General minimum volume unavailable",
    "lead_time": "Lead time unavailable",
    "service": "Service details unavailable",
    "qualification": "Qualification unavailable",
    "exclusion": "Service exclusions unavailable in initial context",
    "action": "Available action unclear",
    "ambiguous": "Some source details are ambiguous",
}
_CATEGORIES = frozenset(
    {"service", "process", "qualification", "exclusion", "action", "contact", "location", "other"}
)
_KEY = re.compile(r"\A[a-z][a-z0-9_ -]{0,63}\Z")
_GENERIC = frozenset(
    "a ad ai al alla alle con da dal della delle di e ed il la le lo per un una uno "
    "che cosa quali quale quando come dove quanto informazioni informazione dettaglio dettagli "
    "servizio servizi offerta offerte offrite offre offrono fate fai azienda aziendale "
    "voi voi vostra vostro vostri vostre mi me si i posso possiamo puoi potete "
    "potrei potrebbe vorrei voglio avere ricevo ricevere richiedere richiesta "
    "what which when how where who why do does you your yours we our of the a an "
    "to for from in on with about any all more information detail details "
    "service services offer offers offered offering company business available provide "
    "can could would should want get have receive request".split()
)
_TIMING_QUESTION = re.compile(
    r"\b(?:when|quando|how long|quanto tempo|in quanto|arrival (?:time|date)|"
    r"delivery date)\b"
)
_TIMING_EVIDENCE = re.compile(
    r"\b(?:daily|weekly|monthly|yearly|hourly|weekdays?|weekends?|"
    r"quotidian[oaie]|settimanale|mensile|annuale|ogni (?:giorno|settimana|mese)|"
    r"every (?:day|week|month)|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"lunedi|martedi|mercoledi|giovedi|venerdi|sabato|domenica)\b"
)
_ARRIVAL = re.compile(r"\b(?:arriv[a-z]*|receiv[a-z]*|ricev[a-z]*)\b")


def _specific_phrase(value: str) -> bool:
    tokens = _normalize(value).split()
    return len(tokens) >= 2 and any(token not in _GENERIC for token in tokens)


def _timing_alias_supported(alias: str, claim: "Claim") -> bool:
    question, evidence = _normalize(alias), _normalize(claim.text)
    if not _TIMING_QUESTION.search(question):
        return True
    return bool(_TIMING_EVIDENCE.search(evidence)) and (
        not _ARRIVAL.search(question) or bool(_ARRIVAL.search(evidence))
    )


def _restricted(text: str) -> bool:
    return any(
        _DENIED.search(value) or _INSTRUCTION.search(value) or _NONPUBLIC.search(value)
        for value in (text, " ".join(text.split()))
    )


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Claim(_Strict):
    text: str = Field(min_length=1, max_length=600)
    start: int = Field(ge=0)
    end: int = Field(gt=0)


class Detail(_Strict):
    category: str = Field(min_length=1, max_length=32)
    key: str = Field(min_length=1, max_length=64)
    aliases: list[str] = Field(min_length=1, max_length=8)
    claim: Claim


class Notes(_Strict):
    identity: Claim | None = None
    services: list[Claim] = Field(default_factory=list, max_length=20)
    qualifications: list[Claim] = Field(default_factory=list, max_length=20)
    exclusions: list[Claim] = Field(default_factory=list, max_length=20)
    actions: list[Claim] = Field(default_factory=list, max_length=20)
    details: list[Detail] = Field(default_factory=list, max_length=60)
    missing: list[str] = Field(default_factory=list, max_length=30)


SourceGroup = Annotated[list[int], Field(min_length=1, max_length=500)]
Category = Literal[
    "service", "process", "qualification", "exclusion", "action", "contact", "location", "other"
]


class SelectedDetail(_Strict):
    ids: SourceGroup
    category: Category
    key: str = Field(min_length=1, max_length=64)
    aliases: list[str] = Field(min_length=1, max_length=8)


class Selection(_Strict):
    identity: int | None
    services: list[SourceGroup] = Field(max_length=4)
    qualifications: list[SourceGroup] = Field(max_length=3)
    exclusions: list[SourceGroup] = Field(max_length=3)
    actions: list[SourceGroup] = Field(max_length=3)
    details: list[SelectedDetail] = Field(max_length=8)
    missing: list[str] = Field(max_length=8)


def _parse_selection(raw: str) -> Selection:
    value = raw.strip()
    if value.startswith("```"):
        fenced = re.fullmatch(r"```json[ \t]*\r?\n([^`]*?)\r?\n```", value, re.DOTALL)
        if fenced is None:
            raise ValueError("Invalid voice-note JSON fence")
        value = fenced.group(1)
    return Selection.model_validate(json.loads(value))


def _units(source: str) -> tuple[Claim, ...]:
    """Give the model IDs while retaining exact source offsets locally."""
    cursor = 0
    result = []
    for chunk in re.split(r"(?<=[.!?])\s+|\n\s*\n", source):
        value = chunk.strip()
        if not value:
            continue
        start = source.find(value, cursor)
        if start < 0 or len(value) > 600:
            raise ValueError("Voice-note source cannot be segmented")
        result.append(Claim(text=value, start=start, end=start + len(value)))
        cursor = start + len(value)
        if len(result) > 500:
            raise ValueError("Too many voice-note source units")
    return tuple(result)


def _materialize(selection: Selection, units: tuple[Claim, ...], source: str) -> Notes:
    used: set[int] = set()
    skipped = False

    def select(indexes: list[int]) -> Claim | None:
        nonlocal skipped
        if not indexes or any(
            type(index) is not int or index < 0 or index >= len(units) or index in used
            for index in indexes
        ):
            raise ValueError("Invalid voice-note source ID")
        if indexes != list(range(indexes[0], indexes[-1] + 1)):
            raise ValueError("Voice-note source group is not contiguous")
        used.update(indexes)
        start, end = units[indexes[0]].start, units[indexes[-1]].end
        for index in indexes:
            unit = units[index]
            if source[unit.start : unit.end] != unit.text:
                raise ValueError("Unsupported voice-note source unit")
        claim = Claim(text=source[start:end], start=start, end=end)
        if _restricted(claim.text):
            skipped = True
            return None
        return claim

    def section(groups: list[list[int]]) -> list[Claim]:
        return [claim for group in groups if (claim := select(group)) is not None]

    identity = select([selection.identity]) if selection.identity is not None else None
    services = section(selection.services)
    qualifications = section(selection.qualifications)
    exclusions = section(selection.exclusions)
    actions = section(selection.actions)
    details = []
    for item in selection.details:
        claim = select(item.ids)
        if claim is not None:
            aliases = [alias for alias in item.aliases if _timing_alias_supported(alias, claim)]
            skipped |= len(aliases) != len(item.aliases)
            if aliases:
                details.append(
                    Detail(category=item.category, key=item.key, aliases=aliases, claim=claim)
                )
    missing = list(dict.fromkeys([*selection.missing, "price", "minimum_volume", "lead_time"]))
    if not exclusions and "exclusion" not in missing:
        missing.append("exclusion")
    if not details and "service" not in missing:
        missing.append("service")
    if skipped and "ambiguous" not in missing:
        missing.append("ambiguous")
    return Notes(
        identity=identity,
        services=services,
        qualifications=qualifications,
        exclusions=exclusions,
        actions=actions,
        details=details,
        missing=missing,
    )


def _claims(notes: Notes):
    if notes.identity is not None:
        yield notes.identity
    for section in (notes.services, notes.qualifications, notes.exclusions, notes.actions):
        yield from section
    for detail in notes.details:
        yield detail.claim


def _validate(notes: Notes, source: str) -> None:
    for claim in _claims(notes):
        if claim.start >= claim.end or source[claim.start : claim.end] != claim.text:
            raise ValueError("Unsupported voice-note evidence")
        if (
            _restricted(claim.text)
            or any(ord(char) < 32 and char not in "\n\r\t" for char in claim.text)
        ):
            raise ValueError("Restricted voice-note claim")
    for detail in notes.details:
        if (
            detail.category not in _CATEGORIES
            or not _KEY.fullmatch(detail.key)
            or _DENIED.search(detail.key)
        ):
            raise ValueError("Restricted voice-note category")
        if any(
            len(alias) > 64
            or not _specific_phrase(alias)
            or _DENIED.search(alias)
            or _INSTRUCTION.search(alias)
            or not _timing_alias_supported(alias, detail.claim)
            for alias in detail.aliases
        ):
            raise ValueError("Restricted voice-note alias")
    if len({(item.category, item.key) for item in notes.details}) != len(notes.details):
        raise ValueError("Duplicate voice-note detail")
    if any(item not in _GAPS for item in notes.missing):
        raise ValueError("Restricted voice-note omission")
    if not notes.exclusions and "exclusion" not in notes.missing:
        raise ValueError("Missing voice-note exclusion gap")
    if not notes.details and "service" not in notes.missing:
        raise ValueError("Missing voice-note detail gap")
    if not notes.services:
        raise ValueError("No supported service")
    _context(notes)


def _context(notes: Notes) -> str:
    lines = []
    if notes.identity:
        lines.append(f"Company: {notes.identity.text}")
    for label, claims in (
        ("Services", notes.services),
        ("Qualifications", notes.qualifications),
        ("Exclusions", notes.exclusions),
        ("Available actions", notes.actions),
    ):
        if claims:
            lines.append(f"{label}: " + "; ".join(" ".join(claim.text.split()) for claim in claims))
    if notes.missing:
        lines.append("Missing or ambiguous: " + "; ".join(_GAPS[item] for item in notes.missing))
    context = "\n".join(lines)
    if len(context) > MAX_CONTEXT_CHARS:
        raise ValueError("Voice-note context too large")
    return context


def _normalize(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        re.findall(
            r"[a-z0-9]+", "".join(char for char in decomposed if not unicodedata.combining(char))
        )
    )
