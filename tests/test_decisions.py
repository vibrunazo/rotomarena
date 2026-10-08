import asyncio

from rotomarena.config import ProviderConfig
from rotomarena.llm.decisions import MAX_OPTIONS, DecisionClient, Question, Usage, _chunks


def _client(answer_for):
    """A client whose requests are answered by answer_for(question) -> chosen option; records each request."""
    client = DecisionClient(ProviderConfig(base_url="https://openrouter.ai/api/v1", default_model="x"), "typesafe/jev-1.13")
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
    battle = SimpleNamespace(available_moves=[move], available_switches=[mon], can_tera=True)
    assert list(turn_options(battle)) == ["MOVE: earthquake", "MOVE: earthquake [TERA]", "SWITCH: corviknight"]
    assert turn_options(battle)["MOVE: earthquake [TERA]"] == (move, True)


def test_a_question_with_one_option_is_not_sent():
    client, sent = _client(lambda q: sorted(q["criteria"])[0])
    answers, usage = asyncio.run(client.choose("state", {"ability": Question("Which?", {"Good as Gold": ""})}))
    assert answers["ability"].choice == "Good as Gold" and sent == [] and usage.requests == 0
