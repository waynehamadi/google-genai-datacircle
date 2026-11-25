"""Offline tests: the tools against a local stand-in for the API on 127.0.0.1, by their own call, by
function_response_parts() on the SDK's own types, and run by the SDK's automatic function calling in generate_content
and a chat sent to a stand-in of Gemini's API on the same server."""

import asyncio
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from google import genai
from google.genai import types

from google_genai_datacircle import (
    FUNCTIONS,
    TOOL_NAMES,
    afunction_response_parts,
    datacircle_best_plans,
    datacircle_list_apis,
    datacircle_provider,
    datacircle_search_plans,
    datacircle_tools,
    function_response_parts,
    run,
)
from google_genai_datacircle import _api

PLAN = {"api": "Employee email", "rank": 1, "provider": "Hunter", "plan": "Starter", "score": 80.1, "perThousand": 4.9,
        "page": "https://datacircle.dev/x", "terms": "long", "aggregators": ["a"]}
SEEN = []
BUSY = []
ASKED = []


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def send(self, status, body, headers=None):
        data = json.dumps(body).encode()
        self.send_response(status)
        for key, value in {"Content-Type": "application/json", "Content-Length": str(len(data)), **(headers or {})}.items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):  # Gemini's generateContent: calls best_plans and the app's own tool, then answers
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        ASKED.append(body)
        answers = [part["functionResponse"] for content in body["contents"] for part in content.get("parts", [])
                   if "functionResponse" in part]
        if answers:
            parts = [{"text": "done " + json.dumps([answer["response"] for answer in answers])}]
        else:
            parts = [{"functionCall": {"name": "datacircle_best_plans", "args": {"slug": "email-finder", "limit": 1}}},
                     {"functionCall": {"name": "add_two_numbers", "args": {"a": 1, "b": 2}}}]
        self.send(200, {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}]})

    def do_GET(self):
        url = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        SEEN.append((url.path, query, self.headers.get("User-Agent")))
        headers = {}
        if url.path == "/v1/plans" and query.get("query") == "busy" and not BUSY:
            BUSY.append(1)
            status, body, headers = 429, {"error": "slow down"}, {"Retry-After": "1"}
        elif url.path == "/v1/apis":
            status, body = 200, [{"api": "Employee email", "slug": "email-finder", "plans": 9, "providers": 3, "extra": 1},
                                 {"api": "Employee profile", "slug": "linkedin-profile", "plans": 4, "providers": 2}]
        elif url.path == "/v1/apis/email-finder/best":
            status, body = 200, {"api": "Employee email", "slug": "email-finder", "total": 1, "plans": [PLAN]}
        elif url.path.startswith("/v1/apis/"):
            status, body = 404, {"error": "no API has the slug nope", "slugs": ["email-finder", "linkedin-profile"]}
        elif url.path == "/v1/plans" and query.get("query") == "down":
            status, body = 503, {"error": "down for a minute"}
        elif url.path == "/v1/plans":
            status, body = 200, {"total": 1, "offset": 0, "plans": [PLAN]}
        elif url.path == "/v1/providers/bright-data":
            status, body = 200, {"provider": "Bright Data", "slug": "bright-data", "website": "https://brightdata.com",
                                 "apis": [{"api": "Employee email", "slug": "email-finder", "rank": 7, "sheetPage": "s",
                                           "plans": [dict(PLAN, rank=9, plan="B"), dict(PLAN, rank=7, plan="A")]}]}
        else:
            status, body = 404, {"error": "no provider has this slug"}
        self.send(status, body, headers)


@pytest.fixture(scope="module", autouse=True)
def stand_in():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    before = _api.BASE_URL
    _api.BASE_URL = f"http://127.0.0.1:{server.server_address[1]}/v1"
    yield server.server_address[1]
    _api.BASE_URL = before
    server.shutdown()


def calls_made(action):
    SEEN.clear()
    result = action()
    return result, list(SEEN)


def add_two_numbers(a: int, b: int) -> int:
    """Adds two numbers.

    Args:
      a: The first number.
      b: The second number.
    """
    return a + b


def test_declarations_as_the_sdk_makes_them():
    client = genai.Client(api_key="test")
    declared = {}
    for function in datacircle_tools():
        declaration = types.FunctionDeclaration.from_callable(client=client, callable=function)
        schema = declaration.model_dump(mode="json", exclude_none=True)
        declared[declaration.name] = (declaration.description, schema.get("parameters") or {})
    assert list(declared) == TOOL_NAMES == ["datacircle_list_apis", "datacircle_best_plans", "datacircle_search_plans",
                                            "datacircle_provider"]
    wanted = {"datacircle_list_apis": {"query": "STRING", "limit": "INTEGER"},
              "datacircle_best_plans": {"slug": "STRING", "limit": "INTEGER"},
              "datacircle_search_plans": {"api": "STRING", "query": "STRING", "sort": "STRING", "limit": "INTEGER",
                                          "offset": "INTEGER"},
              "datacircle_provider": {"slug": "STRING"}}
    for name, kinds in wanted.items():
        description, parameters = declared[name]
        assert "https://datacircle.dev" in description and "Args:" in description, name
        assert {key: value["type"] for key, value in parameters["properties"].items()} == kinds, name
        assert [key for key, value in parameters["properties"].items() if not value.get("nullable")] == \
            (["slug"] if "slug" in kinds else []), name
    assert "price ($ per 1,000, lowest first)" in declared["datacircle_search_plans"][0]


def test_some_tools_by_name():
    assert datacircle_tools(["datacircle_provider", "datacircle_best_plans"]) == [datacircle_provider, datacircle_best_plans]
    assert datacircle_tools() == list(FUNCTIONS.values())
    with pytest.raises(ValueError):
        datacircle_tools(["nope"])
    with pytest.raises(TypeError):
        datacircle_tools("datacircle_provider")


def test_each_tool_and_the_calls_it_makes():
    listed, seen = calls_made(lambda: datacircle_list_apis("profile", 1))
    assert listed == {"total": 1, "apis": [{"api": "Employee profile", "slug": "linkedin-profile", "plans": 4, "providers": 2}]}
    assert seen == [("/v1/apis", {}, _api.USER_AGENT)]
    assert datacircle_list_apis()["total"] == 2

    best, seen = calls_made(lambda: datacircle_best_plans("Email Finder", 1))
    assert best["plans"] == [{key: PLAN[key] for key in ("api", "rank", "provider", "plan", "score", "perThousand", "page")}]
    assert seen[0][:2] == ("/v1/apis/email-finder/best", {"limit": "1"})

    found, seen = calls_made(lambda: datacircle_search_plans(api="email-finder", query="hunter", sort="Price", limit=5))
    assert found["total"] == 1 and "terms" not in found["plans"][0]
    assert seen[0][:2] == ("/v1/plans", {"api": "email-finder", "query": "hunter", "sort": "price", "limit": "5"})

    seller, seen = calls_made(lambda: datacircle_provider("Bright Data"))
    assert seen[0][0] == "/v1/providers/bright-data"
    assert seller["apis"] == [{"api": "Employee email", "slug": "email-finder", "rank": 7, "plans": 2,
                               "best": {"plan": "A", "score": 80.1, "perThousand": 4.9, "page": "https://datacircle.dev/x"}}]


def test_refusals_in_the_apis_words():
    unknown = datacircle_best_plans("nope")
    assert unknown == {"error": "Datacircle's API answered 404: no API has the slug nope; the slugs: email-finder, linkedin-profile"}
    assert "503: down for a minute" in datacircle_search_plans(query="down")["error"]
    assert "no provider" in datacircle_provider("nobody")["error"]
    for refused in (lambda: datacircle_best_plans("email-finder", 51), lambda: datacircle_search_plans(sort="cheap"),
                    lambda: datacircle_search_plans(offset=-1), lambda: datacircle_list_apis(limit="many"),
                    lambda: datacircle_best_plans(""), lambda: datacircle_provider(None),
                    lambda: datacircle_search_plans(limit=True)):
        answer, seen = calls_made(refused)
        assert list(answer) == ["error"] and seen == [], answer


def test_a_429_is_waited_once():
    answer, seen = calls_made(lambda: datacircle_search_plans(query="busy"))
    assert answer["total"] == 1 and len(seen) == 2


def test_function_response_parts_on_the_sdks_types():
    ours = types.FunctionCall(id="c1", name="datacircle_best_plans", args={"slug": "email-finder", "limit": 1.0})
    theirs = types.FunctionCall(id="c2", name="add_two_numbers", args={"a": 1, "b": 2})
    plain = types.FunctionCall(name="datacircle_provider", args={"slug": "Bright Data", "nope": 1})
    response = types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(
        role="model", parts=[types.Part(text="let me look"), types.Part(function_call=ours),
                             types.Part(function_call=theirs), types.Part(function_call=plain)]))])
    parts = function_response_parts(response)
    assert [(p.function_response.id, p.function_response.name) for p in parts] == \
        [("c1", "datacircle_best_plans"), (None, "datacircle_provider")]
    assert parts[0].function_response.response["result"]["plans"][0]["rank"] == 1
    assert parts[1].function_response.response["result"]["slug"] == "bright-data"
    content = response.candidates[0].content
    for source in (content, content.parts):
        assert [p.function_response.name for p in function_response_parts(source)] == \
            ["datacircle_best_plans", "datacircle_provider"]
    for source in ([ours, theirs], [{"name": "datacircle_best_plans", "args": {"slug": "email-finder"}, "id": "c1"}],
                   {"function_call": ours.model_dump()}):
        assert [(p.function_response.id, p.function_response.name) for p in function_response_parts(source)] == \
            [("c1", "datacircle_best_plans")]
    assert function_response_parts(None) == [] and function_response_parts(types.GenerateContentResponse()) == []
    refused = function_response_parts([types.FunctionCall(name="datacircle_best_plans", args={"slug": "nope"})])
    assert "404" in refused[0].function_response.response["result"]["error"]
    # The parts go back to the SDK as they are.
    types.Content(role="user", parts=parts)
    with pytest.raises(ValueError):
        run("nope", {})
    assert run("datacircle_provider", {"slug": "bright-data", "nope": 1})["slug"] == "bright-data"
    assert "error" in run("datacircle_best_plans", None)


def test_async_parts_keep_the_calls_order():
    calls = [types.FunctionCall(id="a", name="datacircle_provider", args={"slug": "bright-data"}),
             types.FunctionCall(id="b", name="add_two_numbers", args={}),
             types.FunctionCall(id="c", name="datacircle_best_plans", args={"slug": "email-finder"})]
    parts = asyncio.run(afunction_response_parts(calls))
    assert [(p.function_response.id, p.function_response.name) for p in parts] == \
        [("a", "datacircle_provider"), ("c", "datacircle_best_plans")]


def client_of(port):
    return genai.Client(api_key="test", http_options=types.HttpOptions(base_url=f"http://127.0.0.1:{port}"))


def test_the_sdks_own_loop_runs_them(stand_in):
    ASKED.clear()
    config = types.GenerateContentConfig(tools=[*datacircle_tools(), add_two_numbers])
    client = client_of(stand_in)  # held: a client the SDK collects closes its connections
    response = client.models.generate_content(model="gemini-2.5-flash", contents="best email finder?", config=config)
    answers = json.loads(response.text[len("done "):])
    assert answers[0]["result"]["plans"][0]["provider"] == "Hunter" and answers[1] == {"result": 3}
    sent = [declaration["name"] for tool in ASKED[0]["tools"] for declaration in tool["functionDeclarations"]]
    assert sent == TOOL_NAMES + ["add_two_numbers"]

    chat = client.chats.create(model="gemini-2.5-flash", config=config)
    assert chat.send_message("best email finder?").text.startswith("done ")

    async def aio():
        return await client.aio.models.generate_content(model="gemini-2.5-flash", contents="best?", config=config)
    assert json.loads(asyncio.run(aio()).text[len("done "):])[0]["result"]["slug"] == "email-finder"
