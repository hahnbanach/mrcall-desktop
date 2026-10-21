"""The admitted endpoint tags a provider's `only` names (roles/catalogue.py)."""


def test_only_names_a_duplicated_endpoint_tag_once(monkeypatch):
    """IR4b minor 2: the 2026-10-10 read lists `alibaba/fp8` twice for GLM 5.2
    (two endpoints at different prices); the provider's `only` names it once,
    as the billing server does."""
    from zylch.llm.roles import catalogue

    row = {"endpoints": [{"tag": "alibaba/fp8"}, {"tag": "z-ai/fp8"}, {"tag": "alibaba/fp8"}]}
    monkeypatch.setattr(catalogue, "_find", lambda model_id, key: row)
    assert catalogue.endpoint_tags("z-ai/glm-5.2") == ["alibaba/fp8", "z-ai/fp8"]
