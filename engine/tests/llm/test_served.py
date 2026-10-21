"""The credits choice against the billing server's v2 capabilities (brief D6; AC 5, engine side).

For an automatic choice on MrCall credits the engine runs the first id of the
role's ranking the server publishes on ``GET /capabilities?protocol=
mrcall-bounded-v2`` (the direct id when the server lists that as Anthropic's,
the catalogue id otherwise), reads the list at most once an hour (5 s
timeout), pauses naming the role when nothing ranked is served, refuses a
malformed list explicitly and pauses with "update the billing server" on a v1
answer. Each case runs a real `BoundedProxyClient` against a fake server
(`httpx.MockTransport`), over the fixture table the root conftest puts in force.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest

from zylch.llm import bounded_proxy
from zylch.llm.bounded_proxy import BoundedProxyClient
from zylch.llm.budget_pricing import BudgetError
from zylch.llm.model_policy import resolve_model
from zylch.llm.roles import served, table

from . import model_table_fixture as fixture

URL = "https://billing.example.test"
TABLE = fixture.doc("table.json")
ROLES = tuple(fixture.requirements()["roles"])


class Server:
    """A fake billing server answering `answer` on capabilities; reads recorded."""

    def __init__(self, answer):
        self.answer, self.reads = answer, []

    def client(self):
        def handler(request):
            self.reads.append((request.method, request.url.path, dict(request.url.params)))
            return httpx.Response(200, json=self.answer)

        http = httpx.Client(transport=httpx.MockTransport(handler))
        return BoundedProxyClient(URL, SimpleNamespace(id_token="synthetic"), http_client=http)


def listing(*models):
    return fixture.capabilities([fixture.served_entry(m, p) for m, p in models])


def picks(server, preset):
    """{role: model or the pause message} for every role under `preset`."""
    out = {}
    for role in ROLES:
        try:
            out[role] = served.pick(preset, role, URL, client=server.client())
        except BudgetError as exc:
            out[role] = str(exc)
    return out


def test_a_server_serving_only_k3_runs_k3_where_it_is_ranked_and_pauses_elsewhere():
    server = Server(listing((fixture.K3, "openrouter")))
    assert set(picks(server, "balanced").values()) == {fixture.K3}  # every balanced role ranks K3
    economy = picks(server, "economy")  # K3 is above economy's ceiling: ranked nowhere
    for role, outcome in economy.items():
        # The remedy is what Settings offers for the role: its own field, else the
        # custom preset (or another billing choice).
        remedy = (
            "Choose a model for it in Settings."
            if role in ("TASK_DETECTION", "REANALYZE", "DEDUP", "MEMORY_EXTRACT", "MEMORY_MERGE")
            else "In Settings, choose the custom preset with a model the billing server serves "
            "as the default model, or another billing choice."
        )
        assert outcome == (
            f"AI paused: no model served for role {role}: the MrCall billing server serves none "
            f"of the models ranked for it under the economy preset. {remedy}"
        )
    assert server.reads == [
        ("GET", "/api/desktop/llm/bounded/capabilities", {"protocol": "mrcall-bounded-v2"})
    ]


def test_a_server_listing_a_catalogue_id_runs_that_catalogue_id():
    server = Server(listing((fixture.SONNET5, "openrouter")))
    assert served.pick("economy", "DEDUP", URL, client=server.client()) == fixture.SONNET5
    assert served.pick("economy", "CHAT", URL, client=server.client()) == fixture.SONNET5  # 3rd
    assert served.pick("balanced", "DEDUP", URL, client=server.client()) == fixture.SONNET5
    with pytest.raises(BudgetError, match="no model served for role CHAT"):
        served.pick("balanced", "CHAT", URL, client=server.client())


def test_the_direct_id_wins_when_the_server_lists_it_as_anthropic_s():
    both = listing(("claude-sonnet-5", "anthropic"), (fixture.SONNET5, "openrouter"))
    assert served.pick("economy", "DEDUP", URL, client=Server(both).client()) == "claude-sonnet-5"
    # A direct id the server lists as OpenRouter's is not Anthropic's: nothing matches.
    served._cache.clear()  # a new read (the last one is cached for an hour)
    odd = listing(("claude-sonnet-5", "openrouter"))
    with pytest.raises(BudgetError, match="no model served for role DEDUP"):
        served.pick("economy", "DEDUP", URL, client=Server(odd).client())


def test_the_ranking_order_decides_among_served_models():
    every = Server(fixture.capabilities(fixture.everything()))
    for preset in ("economy", "balanced"):
        for role, model in picks(every, preset).items():
            first = TABLE["presets"][preset]["roles"][role]["ranking"][0]
            assert model == (first["direct_id"] or first["id"]), (preset, role)


def test_a_server_serving_nothing_pauses_every_role():
    server = Server(fixture.capabilities([]))
    for preset in ("economy", "balanced"):
        assert all(
            m.startswith("AI paused: no model served for role")
            for m in picks(server, preset).values()
        )


@pytest.mark.parametrize(
    "models",
    [
        "not a list",
        [{"id": fixture.K3, "provider": "openrouter"}],  # no label
        [{"id": "", "label": "x", "provider": "openrouter"}],
        [{"id": fixture.K3, "label": "K3", "provider": "vertex"}],
        [fixture.K3],
    ],
)
def test_a_malformed_catalogue_is_an_explicit_error_never_a_guess(models):
    server = Server({**fixture.capabilities([]), "models": models})
    with pytest.raises(BudgetError) as refused:
        served.pick("balanced", "CHAT", URL, client=server.client())
    assert (
        str(refused.value)
        == "AI paused: the MrCall billing server returned a malformed model catalogue."
    )
    assert served.cached(URL) is None  # a failed read is never cached
    good = Server(listing((fixture.K3, "openrouter")))
    assert served.pick("balanced", "CHAT", URL, client=good.client()) == fixture.K3


def test_a_v1_answer_pauses_with_update_the_billing_server():
    server = Server(
        {
            **fixture.capabilities([fixture.served_entry(fixture.K3, "openrouter")]),
            "protocol": "mrcall-bounded-v1",
        }
    )
    with pytest.raises(BudgetError, match="update the billing server") as paused:
        served.pick("balanced", "CHAT", URL, client=server.client())
    assert "mrcall-bounded-v2" in str(paused.value)
    assert served.cached(URL) is None
    # The parser refuses it too, whoever read it.
    with pytest.raises(BudgetError, match="update the billing server"):
        served.parse({**fixture.capabilities([]), "protocol": "mrcall-bounded-v1"})


def test_the_list_is_read_at_most_once_an_hour_and_the_offline_read_never_calls(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(served, "_clock", lambda: now[0])
    server = Server(listing((fixture.K3, "openrouter")))
    with pytest.raises(BudgetError, match="has not been read yet"):
        served.pick("balanced", "CHAT", URL, online=False)
    for _ in range(3):
        assert served.pick("balanced", "CHAT", URL, client=server.client()) == fixture.K3
    assert len(server.reads) == 1
    now[0] += served.CACHE_SECONDS - 1
    served.pick("balanced", "DEDUP", URL, client=server.client())
    assert len(server.reads) == 1
    now[0] += 2  # past the hour: read again
    server.answer = listing((fixture.SONNET5, "openrouter"))
    assert served.pick("balanced", "DEDUP", URL, client=server.client()) == fixture.SONNET5
    assert len(server.reads) == 2
    now[0] += 10 * served.CACHE_SECONDS  # stale: offline still answers from the last read
    assert served.pick("balanced", "DEDUP", URL, online=False) == fixture.SONNET5
    assert len(server.reads) == 2


def test_capabilities_are_read_with_the_v2_marker_and_a_five_second_timeout(monkeypatch):
    seen = {}

    class Client(httpx.Client):
        def __init__(self, **kwargs):
            seen.update(kwargs)
            answer = listing((fixture.K3, "openrouter"))
            handler = lambda request: (
                seen.update(url=str(request.url)) or httpx.Response(200, json=answer)
            )
            super().__init__(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(bounded_proxy.httpx, "Client", Client)
    reader = BoundedProxyClient(URL, SimpleNamespace(id_token="synthetic"))
    assert served.pick("balanced", "CHAT", URL, client=reader) == fixture.K3
    assert seen["timeout"] == 5 and seen["follow_redirects"] is False
    assert seen["url"] == URL + "/api/desktop/llm/bounded/capabilities?protocol=mrcall-bounded-v2"


def test_credits_resolution_reads_the_profile_s_server_and_an_explicit_choice_reads_nothing(
    monkeypatch,
):
    server = Server(listing((fixture.K3, "openrouter")))
    monkeypatch.setattr(served, "_reader", lambda url: server.client() if url == URL else None)
    values = {"LLM_PROVIDER": "mrcall", "LLM_MODEL_PRESET": "balanced", "MRCALL_PROXY_URL": URL}
    assert resolve_model("MODEL_TASK_DETECTION", values=values) == fixture.K3
    assert len(server.reads) == 1
    saved = {**values, "MODEL_TASK_DETECTION": "claude-haiku-4-5", "MRCALL_PROXY_URL": "https://x"}
    assert (
        resolve_model("MODEL_TASK_DETECTION", values=saved) == "claude-haiku-4-5"
    )  # sent as saved
    assert len(server.reads) == 1 and served.cached("https://x") is None


def test_the_rankings_come_from_the_table_in_force():
    server = Server(fixture.capabilities(fixture.everything()))
    reversed_table = json.loads(json.dumps(TABLE))
    for rankings in reversed_table["presets"]["balanced"]["roles"].values():
        rankings["ranking"].reverse()
    table.set_table(reversed_table)
    assert (
        served.pick("balanced", "CHAT", URL, client=server.client()) == fixture.K3
    )  # was Opus 5.5
