"""Production voice reservations persist without test lifetime ceilings."""

from sqlalchemy import select

from zylch.storage.voice_production import ProductionMeter, ProductionVoiceLedger


def test_accrual_receipt_restart_and_next_call(tmp_path):
    path = tmp_path / "production-voice.db"
    ledger = ProductionVoiceLedger(path, "business-policy", 10_000_000)
    assert ledger.reserve_carrier("carrier-1", "hash-1", allowed=True, conversation_uuid="CON-1")
    assert not ledger.reserve_carrier("carrier-1", "hash-1", allowed=True, conversation_uuid="CON-1")
    assert ledger.bind_carrier("session-1", "hash-1", allowed=True) == "accept"
    ledger.accrue("session-1", 30, 70_000)
    ledger.record_provider_usage("session-1", seconds=30)
    ledger.record_carrier_receipt(
        "carrier-1", conversation_uuid="CON-1", direction="inbound",
        status="completed", price="0.003", currency=None,
    )
    ledger.record_carrier_receipt(
        "sip-leg-1", conversation_uuid="CON-1", direction="outbound",
        status="completed", price="0.002", currency=None,
    )
    ledger.finish("session-1", "closed", {"finalization": "confirmed"})
    ledger.close()

    reopened = ProductionVoiceLedger(path, "business-policy", 10_000_000)
    with reopened.engine.connect() as db:
        meter = db.execute(select(ProductionMeter.__table__).where(
            ProductionMeter.session_id == "session-1"
        )).mappings().one()
        assert meter["accrued_microusd"] == 35_000
        assert meter["provider_usage"] == {
            "voice_seconds": 30, "combined_exposure_estimate_microusd": 35_000
        }
        assert meter["carrier_receipt"] == {
            "legs": {
                "carrier-1": {
                    "status": "completed", "price": "0.003", "currency": "EUR",
                    "currency_source": "Vonage Voice webhook reference", "direction": "inbound",
                },
                "sip-leg-1": {
                    "status": "completed", "price": "0.002", "currency": "EUR",
                    "currency_source": "Vonage Voice webhook reference", "direction": "outbound",
                },
            },
            "covered": True, "usd_estimate_microusd": 10_000,
        }
        assert meter["reconciliation_state"] == "provisionally_covered"
        assert meter["state"] == "closed"
    assert reopened.rows()[0]["reserved_microusd"] == 10_000_000
    assert reopened.reserve_carrier("carrier-2", "hash-2", allowed=True, conversation_uuid="CON-2")
    reopened.close()


def test_uncertain_hold_blocks_new_admission(tmp_path):
    ledger = ProductionVoiceLedger(tmp_path / "production-voice.db", "business-policy", 10_000_000)
    assert ledger.reserve_carrier("carrier-1", "hash-1", allowed=True, conversation_uuid="CON-1")
    assert not ledger.reserve_carrier("carrier-2", "hash-2", allowed=True, conversation_uuid="CON-2")
    ledger.finish("vonage:carrier-1", "uncertain")
    assert not ledger.reserve_carrier("carrier-3", "hash-3", allowed=True, conversation_uuid="CON-3")
    ledger.close()


def test_hold_increases_before_estimated_exposure_exceeds_it(tmp_path):
    ledger = ProductionVoiceLedger(tmp_path / "production-voice.db", "business-policy", 10_000_000)
    assert ledger.reserve_carrier("carrier-1", "hash-1", allowed=True, conversation_uuid="CON-1")
    assert ledger.bind_carrier("session-1", "hash-1", allowed=True) == "accept"
    ledger.accrue("session-1", 120, 5_000_000)
    assert ledger.rows()[0]["reserved_microusd"] == 15_000_000
    with ledger.engine.connect() as db:
        meter = db.execute(select(ProductionMeter.__table__)).mappings().one()
        assert meter["hold_increase_microusd"] == 5_000_000
        assert meter["accrued_microusd"] == 10_000_000
    ledger.close()


def test_final_elapsed_is_accrued_with_terminal_state(tmp_path):
    ledger = ProductionVoiceLedger(
        tmp_path / "production-voice.db", "business-policy", 10_000_000,
        rate_per_minute=5_000_000,
    )
    assert ledger.reserve_carrier("carrier-1", "hash-1", allowed=True, conversation_uuid="CON-1")
    assert ledger.bind_carrier("session-1", "hash-1", allowed=True) == "accept"
    ledger.accrue("session-1", 60, 5_000_000)
    ledger.finish("session-1", "closed", {"observed_elapsed_ms": 180_000})
    with ledger.engine.connect() as db:
        meter = db.execute(select(ProductionMeter.__table__)).mappings().one()
        assert meter["accrued_microusd"] == 15_000_000
        assert meter["hold_increase_microusd"] == 5_000_000
        assert meter["state"] == "closed"
    assert ledger.rows()[0]["reserved_microusd"] == 15_000_000
    ledger.close()


def test_missing_receipt_blocks_next_paid_call_without_lifetime_cap(tmp_path):
    ledger = ProductionVoiceLedger(tmp_path / "production-voice.db", "policy", 10_000_000)
    assert ledger.admission_ready()
    assert ledger.reserve_carrier("carrier-1", "hash-1", allowed=True, conversation_uuid="CON-1")
    assert ledger.bind_carrier("session-1", "hash-1", allowed=True) == "accept"
    ledger.finish("session-1", "closed", {"observed_elapsed_ms": 10_000})
    assert not ledger.admission_ready()
    assert not ledger.reserve_carrier("carrier-2", "hash-2", allowed=True, conversation_uuid="CON-2")
    ledger.record_provider_usage("session-1", seconds=10)
    ledger.record_carrier_receipt(
        "carrier-1", conversation_uuid="CON-1", direction="inbound",
        status="completed", price="0.002", currency=None,
    )
    assert not ledger.admission_ready()
    ledger.record_carrier_receipt(
        "sip-leg-1", conversation_uuid="CON-1", direction="outbound",
        status="completed", price="0.002", currency=None,
    )
    assert ledger.admission_ready()
    assert ledger.reserve_carrier("carrier-3", "hash-3", allowed=True, conversation_uuid="CON-3")
    ledger.close()


def test_missing_meter_cannot_close_positive_hold(tmp_path):
    from sqlalchemy import delete
    import pytest

    ledger = ProductionVoiceLedger(tmp_path / "production-voice.db", "policy", 10_000_000)
    assert ledger.reserve_carrier("carrier-1", "hash-1", allowed=True, conversation_uuid="CON-1")
    with ledger.engine.begin() as db:
        db.execute(delete(ProductionMeter))
    with pytest.raises(ValueError, match="meter missing"):
        ledger.finish("vonage:carrier-1", "stopped")
    assert ledger.rows()[0]["state"] == "carrier_waiting"
    assert not ledger.reserve_carrier("carrier-2", "hash-2", allowed=True, conversation_uuid="CON-2")
    ledger.close()
