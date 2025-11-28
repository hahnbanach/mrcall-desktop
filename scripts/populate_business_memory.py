#!/usr/bin/env python3
"""Populate business namespace in zylch_memory with company info.

This script populates the '{owner}:{zylch_assistant_id}' namespace with:
- Services offered
- Pricing information
- Template structures
- Business policies

Run this script once to initialize business memory, or re-run to update.
"""

import os
import sys
from pathlib import Path

# Add parent directory to path to import zylch modules
sys.path.insert(0, str(Path(__file__).parent.parent))

# Add zylch_memory to path (same pattern as zylch/memory/__init__.py)
_zylch_memory_path = Path(__file__).parent.parent / "zylch_memory"
if _zylch_memory_path.exists():
    sys.path.insert(0, str(_zylch_memory_path))

from zylch_memory.core import ZylchMemory
from zylch_memory.config import ZylchMemoryConfig


def populate_business_memory():
    """Populate business namespace with company information."""

    # Get multi-tenant config from environment
    owner_id = os.getenv("OWNER_ID", "owner_default")
    zylch_assistant_id = os.getenv("ZYLCH_ASSISTANT_ID", "default_assistant")

    # Initialize zylch_memory
    print("🧠 Initializing zylch_memory...")
    cache_dir = Path("cache")
    cache_dir.mkdir(parents=True, exist_ok=True)

    config = ZylchMemoryConfig(
        db_path=cache_dir / "zylch_memory.db",
        index_dir=cache_dir / "indices"
    )
    memory = ZylchMemory(config=config)
    print("✅ ZylchMemory initialized\n")

    # Multi-tenant namespace for business info
    namespace = f"{owner_id}:{zylch_assistant_id}"
    print(f"📍 Using namespace: {namespace}\n")

    # Define business memories to populate
    business_memories = [
        # Services
        {
            "category": "business",
            "context": "MrCall servizi chiamate outbound",
            "pattern": (
                "Chiamate outbound: offriamo 4 livelli di servizio. "
                "Servizio A (Base): routing chiamate semplice, €500-1500/mese. "
                "Servizio B (Analytics): include dashboard e reportistica, €1500-3000/mese. "
                "Servizio C (Integrazione): API e CRM integration, €3000-5000/mese. "
                "Servizio D (AI Avanzato): AI sentiment analysis e auto-tagging, €5000+/mese. "
                "IMPORTANTE: Non accettiamo clienti per attività spam o telemarketing aggressivo."
            ),
            "examples": []
        },
        {
            "category": "business",
            "context": "MrCall servizi assistente telefonico",
            "pattern": (
                "Assistente telefonico AI (MrCall): risponde automaticamente alle chiamate in entrata, "
                "comprende richieste in linguaggio naturale, può prenotare appuntamenti, "
                "fornire informazioni, trasferire a umani se necessario. "
                "Prezzi: €2000-8000/mese base package + €0.10-0.30 per chiamata gestita. "
                "Richiede setup iniziale (€1000-3000 one-time)."
            ),
            "examples": []
        },
        {
            "category": "business",
            "context": "MrCall servizi WhatsApp Business",
            "pattern": (
                "WhatsApp Business Integration: chatbot automatico per WhatsApp, "
                "gestione code messaggi, integrazione CRM, analisi conversazioni. "
                "Prezzi: €1500-5000/mese + costi WhatsApp Business API. "
                "Ideale per customer support e sales follow-up."
            ),
            "examples": []
        },

        # Templates
        {
            "category": "business",
            "context": "Template offerte commerciali",
            "pattern": (
                "Struttura standard offerta commerciale: "
                "1. Intestazione con logo e dati aziendali. "
                "2. Saluto personalizzato (formale/informale in base alla relazione). "
                "3. Breve recap del bisogno/richiesta del cliente. "
                "4. Elenco servizi proposti (bullet points con dettagli). "
                "5. Range prezzi (sempre range, mai cifre esatte prima del primo contatto). "
                "6. Condizioni contrattuali base (durata minima, penali, etc). "
                "7. Next steps chiari (es: 'chiamata conoscitiva', 'demo gratuita'). "
                "8. Chiusura cordiale con firma personalizzata."
            ),
            "examples": []
        },
        {
            "category": "business",
            "context": "Template follow-up post-meeting",
            "pattern": (
                "Follow-up dopo meeting: "
                "1. Ringraziamento per il tempo dedicato. "
                "2. Recap punti chiave discussi (3-5 bullet points). "
                "3. Action items concordati (cosa faremo noi, cosa fa il cliente). "
                "4. Timeline proposta con date specifiche. "
                "5. Prossimo step chiaro (es: invio materiali, call di approfondimento). "
                "Tono: professionale ma cordiale, dimostra che hai preso appunti."
            ),
            "examples": []
        },

        # Policies
        {
            "category": "business",
            "context": "Policy spam e compliance",
            "pattern": (
                "POLICY IMPORTANTE: MrCall NON fornisce servizi per: "
                "spam telefonico, cold calling aggressivo senza consenso, "
                "telemarketing ingannevole, attività che violano GDPR o CAD. "
                "Richiediamo sempre verifica uso legittimo dei dati, "
                "conformità normative, opt-in esplicito per marketing. "
                "In caso di dubbi etici, consultare Mario prima di accettare cliente."
            ),
            "examples": []
        },
        {
            "category": "business",
            "context": "Policy pricing e sconti",
            "pattern": (
                "Pricing policy: "
                "Range pubblici sono orientativi. Sconto max 20% su volumi alti (>€5k/mese). "
                "Setup fee sempre richiesto per nuovi clienti (€500-3000). "
                "Contratti annuali: sconto 15% sul totale. "
                "Trial gratuito: max 14 giorni, richiede carta di credito. "
                "Rimborsi: entro 30 giorni se insoddisfatti (termini e condizioni apply)."
            ),
            "examples": []
        },

        # Company info
        {
            "category": "business",
            "context": "MrCall company background",
            "pattern": (
                "MrCall è una startup italiana fondata nel 2023, "
                "specializzata in soluzioni AI per comunicazione business. "
                "Team: 5 persone (2 dev, 1 sales, 1 CS, 1 founder). "
                "Clienti: principalmente PMI italiane e alcune enterprise. "
                "Settori: customer service, vendite, assistenza tecnica. "
                "Tecnologia: Python, FastAPI, Claude AI, integrazione VoIP."
            ),
            "examples": []
        },
        {
            "category": "business",
            "context": "MrCall valori e mission",
            "pattern": (
                "Mission: rendere l'AI accessibile alle PMI italiane per migliorare "
                "la comunicazione con i clienti senza sostituire l'umano. "
                "Valori: trasparenza, etica nell'uso dell'AI, supporto locale in italiano, "
                "nessun vendor lock-in (API aperte), privacy-first (dati in EU)."
            ),
            "examples": []
        }
    ]

    # Populate memories
    print(f"📝 Popolamento namespace '{namespace}'...")
    stored_count = 0

    for mem in business_memories:
        try:
            memory.store_memory(
                namespace=namespace,
                category=mem["category"],
                context=mem["context"],
                pattern=mem["pattern"],
                examples=mem["examples"],
                confidence=0.8  # High confidence for manually curated business info
            )
            stored_count += 1
            print(f"  ✅ Salvato: {mem['context'][:50]}...")
        except Exception as e:
            print(f"  ❌ Errore salvando '{mem['context'][:30]}...': {e}")

    print(f"\n✅ Completato! {stored_count}/{len(business_memories)} memorie salvate.\n")

    # Show statistics
    print("📊 Statistiche namespace 'business':")
    print(f"   - Categorie: services, templates, policies, company")
    print(f"   - Confidence: 0.8 (curated)")
    print(f"   - Semantic search: abilitato")

    # Test retrieval
    print("\n🔍 Test retrieval:")
    test_queries = [
        "servizi outbound prezzi",
        "template offerta commerciale",
        "policy spam compliance"
    ]

    for query in test_queries:
        results = memory.retrieve_memories(
            query=query,
            namespace=namespace,
            limit=2
        )
        print(f"\n   Query: '{query}'")
        if results:
            print(f"   Risultati: {len(results)} memorie trovate")
            print(f"   Top match: {results[0]['context'][:40]}...")
        else:
            print(f"   Nessun risultato")

    print("\n" + "="*70)
    print("✅ Business memory popolata con successo!")
    print("="*70)
    print("\nOra puoi usare il tool 'draft_email_from_memory' che automaticamente")
    print("recupererà queste informazioni quando crei email o offerte.")
    print("\nPer aggiungere nuove memorie business, modifica questo script e ri-esegui.")


if __name__ == "__main__":
    populate_business_memory()
