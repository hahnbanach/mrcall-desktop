"""Text processing utilities for memory system."""

import re
from typing import List

ABBREVIATIONS = {
    # Titles (EN/PT/ES/FR/IT/DE)
    'mr', 'mrs', 'ms', 'dr', 'prof', 'sr', 'jr',
    'sra', 'srta',  # PT/ES
    'mme', 'mlle',  # FR
    'sig', 'dott', 'dottssa', 'ing', 'avv', 'arch',  # IT
    'herr', 'frau',  # DE

    # Corporate (EN/PT/ES/FR/IT/DE)
    'inc', 'ltd', 'corp', 'co', 'llc',
    'ltda', 'cia',  # PT/ES
    'sa', 'sarl', 'sas',  # FR (also ES/IT/PT)
    'srl', 'spa', 'snc', 'sas',  # IT
    'gmbh', 'ag', 'kg', 'ohg', 'ug',  # DE
    'sl', 'sau',  # ES

    # Latin/Common (universal)
    'vs', 'etc', 'eg', 'ie', 'al', 'cf', 'nb', 'ps', 'ca', 'approx',

    # Months - English
    'jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'sept', 'oct', 'nov', 'dec',
    # Months - Portuguese
    'fev', 'abr', 'mai', 'ago', 'set', 'out', 'dez',
    # Months - Spanish
    'ene', 'abr', 'ago', 'dic',
    # Months - French
    'janv', 'févr', 'avr', 'juil', 'août', 'sept', 'déc',
    # Months - Italian
    'gen', 'mag', 'giu', 'lug', 'sett', 'ott', 'dic',
    # Months - German
    'jän', 'mär', 'mai', 'okt', 'dez',

    # Days (common abbreviations)
    'mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun',
    'lun', 'mar', 'mer', 'jeu', 'ven', 'sam', 'dim',  # FR
    'lun', 'mié', 'jue', 'vie', 'sáb', 'dom',  # ES
    'seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom',  # PT
    'lun', 'gio', 'sab',  # IT
    'mo', 'di', 'mi', 'do', 'fr', 'sa', 'so',  # DE

    # Units/Misc
    'kg', 'km', 'cm', 'mm', 'ml', 'mg', 'nr', 'no', 'tel', 'fax', 'ext',
    'apt', 'st', 'ave', 'blvd', 'rd',
    'pag', 'vol', 'ed', 'cap', 'art', 'num',
}

def split_sentences(text: str) -> List[str]:
    """Split text into sentences, handling abbreviations and edge cases.

    Handles:
    - Abbreviations (Dr., Mr., Inc., etc.)
    - Decimal numbers (3.14)
    - Ellipsis (...)
    - URLs (preserved, not split)
    - Split on . ! ? only at sentence boundaries

    Returns:
        List of sentences preserving order
    """
    # Protect abbreviations
    protected = text
    for abbr in ABBREVIATIONS:
        pattern = rf'\b({abbr})\.(?=\s)'
        protected = re.sub(pattern, rf'\1<DOT>', protected, flags=re.IGNORECASE)

    # Protect decimal numbers
    protected = re.sub(r'(\d)\.(\d)', r'\1<DOT>\2', protected)

    # Protect ellipsis
    protected = protected.replace('...', '<ELLIPSIS>')

    # Split on sentence boundaries
    sentences = re.split(r'(?<=[.!?])\s+', protected)

    # Restore protected characters
    result = []
    for s in sentences:
        s = s.replace('<DOT>', '.')
        s = s.replace('<ELLIPSIS>', '...')
        s = s.strip()
        if s:
            result.append(s)

    return result
