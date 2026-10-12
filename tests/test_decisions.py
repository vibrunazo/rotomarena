import asyncio

from rotomarena.config import AgentConfig, AppConfig
from rotomarena.llm.decisions import MAX_OPTIONS, DecisionClient, Question, Usage, _chunks


def _client(answer_for, **agent):
    """A client whose requests are answered by answer_for(question) -> chosen option; records each request."""
    client = DecisionClient.for_agent(AgentConfig(name="jev", type="decision", model="typesafe/jev-1.13", **agent),
                                      AppConfig())
    sent = []

    async def post(state, questions):
        sent.append(questions)
        answers = {}
        for name, q in questions.items():
            pick = answer_for(q)
            answers[name] = {"type": "choice", "choice": pick,
                             "probabilities": {k: (1.0 if k == pick else 0.0) for k in q["criteria"]}}
        return answers, Usage(requests=1, input_tokens=100, cost_usd=0.001)

    client._post = post
    return client, sent


def test_the_decisions_endpoint_sits_next_to_the_openai_one():
    client, _ = _client(lambda q: None)
    assert client.url == "https://openrouter.ai/api/alpha/decisions"


def test_a_local_decision_model_gets_its_port_and_its_settings():
    client, sent = _client(lambda q: sorted(q["criteria"])[0], provider="local", port=8091,
                           decision_request={"model": "multilingual", "max_len": 8192}, decision_max_options=24)
    assert client.url == "http://127.0.0.1:8091/v1/systemone" and client.api_key is None
    assert client.extra == {"model": "multilingual", "max_len": 8192}
    asyncio.run(client.choose("state", {"pick": Question("Which?", {f"mon{i}": "" for i in range(100)})}))
    assert len(sent[0]) == 5 and all(len(q["criteria"]) <= 24 for q in sent[0].values())


def test_long_option_lists_are_split_then_decided_in_a_final():
    assert [len(c) for c in _chunks({str(i): "" for i in range(826)})] == [207, 207, 207, 205]
    options = {f"mon{i}": f"mon{i}" for i in range(600)}
    client, sent = _client(lambda q: "mon450" if "mon450" in q["criteria"] else sorted(q["criteria"])[0])
    answers, usage = asyncio.run(client.choose("state", {"pick": Question("Which?", options),
                                                         "small": Question("Which?", {"a": "", "b": ""})}))
    assert answers["pick"].choice == "mon450" and answers["small"].choice == "a"
    assert len(sent) == 2 and len(sent[0]) == 4  # three chunks and the small question, then the final
    assert all(len(q["criteria"]) <= MAX_OPTIONS for q in sent[0].values())
    assert usage.requests == 2 and abs(usage.cost_usd - 0.002) < 1e-9


def test_turn_options_are_the_legal_actions_an_llm_sees():
    from types import SimpleNamespace

    from rotomarena.agents.decision import turn_options

    move = SimpleNamespace(id="earthquake")
    mon = SimpleNamespace(species="corviknight")
    battle = SimpleNamespace(available_moves=[move], available_switches=[mon], can_tera=True, can_mega_evolve=False)
    assert list(turn_options(battle)) == ["MOVE: earthquake", "MOVE: earthquake [TERA]", "SWITCH: corviknight"]
    assert turn_options(battle)["MOVE: earthquake [TERA]"] == (move, "tera")
    champions = SimpleNamespace(available_moves=[move], available_switches=[], can_tera=False, can_mega_evolve=True)
    assert turn_options(champions)["MOVE: earthquake [MEGA]"] == (move, "mega")


def test_a_question_with_one_option_is_not_sent():
    client, sent = _client(lambda q: sorted(q["criteria"])[0])
    answers, usage = asyncio.run(client.choose("state", {"ability": Question("Which?", {"Good as Gold": ""})}))
    assert answers["ability"].choice == "Good as Gold" and sent == [] and usage.requests == 0



def test_a_local_decision_model_loads_its_server_before_asking(monkeypatch):
    # Drex next to Ling 3.0 Tiny: the pair doesn't fit the GPU, so whichever model's turn it is gets loaded.
    # The decision client skipped that, and every one of Drex's requests was refused (15 void games in c4).
    from rotomarena import local_servers

    loaded, asked = [], []

    async def ensure_loaded(port):
        loaded.append(port)

    async def request(self, body, headers):
        asked.append(loaded[:])
        return {"answers": {"move": {"choice": "a", "probabilities": {"a": 1.0}}}}, 200

    monkeypatch.setattr(local_servers, "ensure_loaded", ensure_loaded)
    monkeypatch.setattr(DecisionClient, "_request", request)
    agent = AgentConfig(name="drex", type="decision", provider="local", model="drex-v1.5", port=8090)
    client = DecisionClient.for_agent(agent, AppConfig())
    asyncio.run(client._post({}, {"move": {"options": {"a": "x"}}}))
    assert asked == [[8090]]  # loaded first, then asked
