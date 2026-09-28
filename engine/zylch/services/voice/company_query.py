"""Deterministic company question routing for a bound call."""

import re

from .company_notes import company_note_detail, company_note_detail_exact, current_company_notes

_PERSONAL_QUESTION = re.compile(
    r"\b(?:cosa sai di me|cosa sapete di me|what do you know about me|"
    r"i miei dati|mie informazioni|my data|my information|cosa mi avete scritto|cosa mi hai scritto|"
    r"what did you write to me|(?:mio|mia|miei|mie|nostro|nostra|my|our|nostre)\s+"
    r"(?:ordine|ordini|order|orders|acquisto|purchase|storico|history|account|dati|data|information|email|mail))\b",
    re.I,
)
_PUBLIC_QUESTION = re.compile(
    r"\b(?:serviz\w*|offrit\w*|offerte|offer\w*|service\w*|"
    r"aziend\w*|company|fornite|provide|do you do|prezz\w*|price\w*|"
    r"cost\w*|tariff\w*|consegn\w*|deliver\w*|minimum|"
    r"minim\w*|tempi\w*|lead time|qualific\w*|variant\w*|"
    r"dettagl\w*|detail\w*|prodott\w*|product\w*|caratteristic\w*|"
    r"feature\w*|opzion\w*|option\w*|disponibil\w*|available|"
    r"ordine|ordini|order|orders|acquist\w*|purchas\w*)\b",
    re.I,
)
_PRICE_QUESTION = re.compile(r"\b(?:prezz\w*|price\w*|cost\w*|tariff\w*)\b", re.I)
_VOLUME_QUESTION = re.compile(r"\b(?:minimum|minim\w*|quantit\w*|volume)\b", re.I)
_LEAD_QUESTION = re.compile(r"\b(?:tempi\w*|lead time|quanto tempo|how long)\b", re.I)
_VARIANT_QUESTION = re.compile(
    r"\b(?:variant\w*|opzion\w*|option\w*|caratteristic\w*|feature\w*)\b", re.I
)
_PROPOSED_OFFER = re.compile(
    r"\b(?:offrite|offer|offrono|vendete|sell|fate|fornite|provide|avete|have)\s+(?=[A-Za-zÀ-ÿ])",
    re.I,
)
_ORDER_QUESTION = re.compile(r"\b(?:ordine|ordini|order|orders|acquist\w*|purchas\w*)\b", re.I)
_GENERAL_SERVICE_QUESTION = re.compile(r"\b(?:che\s+cosa|cosa)\s+fate\b", re.I)
_DEICTIC_FOLLOWUP = re.compile(
    r"^\s*(?:(?:e|and)\s+)?(?:(?:per|about)\s+)?(?:quello|quella|questo|questa|that|it)\s*[?!]?\s*$",
    re.I,
)


class CompanyQuery:
    def __init__(self, profile, snapshot, view):
        self.profile, self.snapshot, self.view = profile, snapshot, view
        self.last_detail = None

    def public_only(self, question):
        personal = bool(_PERSONAL_QUESTION.search(question))
        return bool(
            (self.last_detail and _DEICTIC_FOLLOWUP.fullmatch(question))
            or (
                not personal
                and (
                    _PUBLIC_QUESTION.search(question)
                    or _GENERAL_SERVICE_QUESTION.search(question)
                    or _PROPOSED_OFFER.search(question)
                )
            )
        )

    def current(self):
        if self.view.status != "supported":
            return True
        current = current_company_notes(self.profile, self.snapshot)
        return current.status == "supported" and current.source_hash == self.view.source_hash

    def __call__(self, question):
        followup = bool(_DEICTIC_FOLLOWUP.fullmatch(question))
        selected = self.last_detail if followup else None
        if not followup:
            self.last_detail = None
        if followup and selected is None:
            return ("Ask which company detail the caller means.", None, False)
        personal = bool(_PERSONAL_QUESTION.search(question))
        public = bool(
            _PUBLIC_QUESTION.search(question)
            or (
                not personal
                and (_GENERAL_SERVICE_QUESTION.search(question) or _PROPOSED_OFFER.search(question))
            )
        )
        if personal and not public:
            return None
        if self.view.status != "supported":
            if public:
                return (
                    "Current company information is unavailable for this call. "
                    "State the gap without confirming an offer or price.",
                    None,
                    personal,
                )
            return None
        detail = (
            company_note_detail_exact(
                self.profile, self.snapshot, selected[0], selected[1], self.view.source_hash
            )
            if selected
            else company_note_detail(
                self.profile, self.snapshot, question, expected_source_hash=self.view.source_hash
            )
        )
        if detail.status == "supported":
            evidence = {
                "source_hash": detail.source_hash,
                "category": detail.category,
                "key": detail.key,
                "start": detail.start,
                "end": detail.end,
            }
            return (
                f"Current source-backed company detail: {detail.text} "
                "Answer only this supported detail and its stated conditions.",
                evidence,
                personal,
            )
        if detail.status == "ambiguous":
            self.last_detail = None
            return (
                "Company detail is ambiguous. Ask which detail the caller means.",
                None,
                personal,
            )
        if detail.status == "unavailable":
            self.last_detail = None
            return (
                "Current company detail is unavailable. State the gap without guessing.",
                None,
                personal,
            )
        if not public:
            self.last_detail = None
            return None
        if _PRICE_QUESTION.search(question):
            answer = "A current public price is unavailable. Do not supply a figure."
        elif _VOLUME_QUESTION.search(question):
            answer = "A current minimum volume is unavailable. Do not supply a figure."
        elif _LEAD_QUESTION.search(question):
            answer = "A current lead time is unavailable. Do not supply a duration."
        elif _VARIANT_QUESTION.search(question):
            answer = "Requested variant or option details are unavailable in the current source."
        elif _ORDER_QUESTION.search(question):
            actions = next(
                (
                    line
                    for line in self.view.context.splitlines()
                    if line.startswith("Available actions:")
                ),
                "",
            )
            answer = (
                actions or "A current ordering procedure is unavailable in the selected source."
            )
        elif proposed := _PROPOSED_OFFER.search(question):
            services = next(
                (line for line in self.view.context.splitlines() if line.startswith("Services:")),
                "",
            )
            named = question[proposed.end() :].strip(" ?.!,")
            answer = (
                services
                if named and named.casefold() in services.casefold()
                else (
                    services + "\nThe caller's named offering is not established by this source. "
                    "Do not confirm it."
                )
            )
        else:
            answer = (
                "Current supported company context: "
                + self.view.context
                + "\nOnly confirm services stated there. A caller's proposed service is not evidence."
            )
        return (answer, None, personal)

    def commit(self, metadata):
        self.last_detail = (
            (metadata["category"], metadata["key"])
            if metadata and metadata["source_hash"] == self.view.source_hash
            else None
        )
