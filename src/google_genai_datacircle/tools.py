"""Tools for the Google Gen AI Python SDK on Datacircle's open API, https://api.datacircle.dev/v1: no key, no account.

Each tool is a plain typed function with a Google-style docstring. Given in a config's tools, the SDK makes its
declaration from its signature and docstring, and its automatic function calling runs the calls the model makes, in
generate_content, its stream, chats and their async forms. A tool makes one HTTPS GET and gives the model the API's
answer as a dict. A refusal (an unknown slug, an argument out of range, the API out of reach) is {"error": the API's
words}, so the model can call again and the chat goes on. Each tool checks its own arguments before any call, as a loop
of the app's own sends them unchecked.

No `from __future__ import annotations`, no Literal and no Enum here: the SDK checks each argument the model gives with
isinstance against its type, which a Literal or an Enum fails.
"""

import asyncio
import urllib.parse
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from google.genai import types

from google_genai_datacircle import _api


def _answer(function: Callable[..., Dict[str, Any]], *args: Any) -> Dict[str, Any]:
    """What a tool gives the model: the API's answer, or {"error": ...} when the API or its checks refused."""
    try:
        return function(*args)
    except _api.DatacircleError as error:
        return {"error": str(error)}


def _best(plans: Any) -> Optional[Dict[str, Any]]:
    """A provider's best plan on an API: its lowest rank, a plan with no score having none."""
    ranked = sorted(plans, key=lambda plan: plan.get("rank") if isinstance(plan.get("rank"), (int, float)) else float("inf"))
    return _api.brief(ranked[0], ["plan", "score", "perThousand", "page"]) if ranked else None


def _list_apis(query: Any, limit: Any) -> Dict[str, Any]:
    count = _api.whole("limit", limit, 1, 200) or 20
    apis = _api.get("/apis")
    words = [word for word in str(query or "").lower().replace("-", " ").split() if word]
    held = []
    for index, api in enumerate(apis):
        name = f"{api.get('api', '')} {str(api.get('slug', '')).replace('-', ' ')}".lower()
        matched = sum(word in name for word in words)
        if matched or not words:
            held.append((-matched, index, api))
    found = [_api.brief(api, _api.API_KEYS) for _, _, api in sorted(held, key=lambda h: h[:2])]
    return {"total": len(found), "apis": found[:count]}


def _best_plans(slug: Any, limit: Any) -> Dict[str, Any]:
    made = _api.slug(slug)
    if not made:
        raise _api.DatacircleError("Give an API's slug, like 'email-finder': datacircle_list_apis gives every slug")
    answer = _api.get(f"/apis/{urllib.parse.quote(made)}/best", {"limit": _api.whole("limit", limit, 1, 50)})
    return {**answer, "plans": [_api.brief(plan) for plan in answer.get("plans") or []]}


def _search_plans(api: Any, query: Any, sort: Any, limit: Any, offset: Any) -> Dict[str, Any]:
    order = str(sort).strip().lower() if sort not in (None, "") else None
    if order is not None and order not in ("score", "provider", "price"):
        raise _api.DatacircleError(f"sort must be score, provider or price, not {sort!r}")
    params = {"api": api, "query": query, "sort": order, "limit": _api.whole("limit", limit, 1, 50),
              "offset": _api.whole("offset", offset, 0)}
    answer = _api.get("/plans", params)
    return {**answer, "plans": [_api.brief(plan) for plan in answer.get("plans") or []]}


def _provider(slug: Any) -> Dict[str, Any]:
    made = _api.slug(slug)
    if not made:
        raise _api.DatacircleError("Give a provider's slug or name, like 'bright-data' or 'Bright Data'")
    answer = _api.get(f"/providers/{urllib.parse.quote(made)}")
    apis = [{**_api.brief(entry, ["api", "slug", "rank", "bestPage"]), "plans": len(entry.get("plans") or []),
             "best": _best(entry.get("plans") or [])} for entry in answer.get("apis") or []]
    return {**answer, "apis": apis}


# The tools. The SDK sends each one's whole docstring as its description, Args and all, and reads each argument's type
# and default from its signature: an argument with a default is not required.

def datacircle_list_apis(query: Optional[str] = None, limit: Optional[int] = None) -> Dict[str, Any]:
    """Lists the GTM APIs on Datacircle's sheet (https://datacircle.dev), with each API's slug, how many plans and
    providers it has and its best plan. Call it to find an API's slug when you don't know it.

    Args:
      query: Words of the API's name or slug, like 'email' or 'linkedin profile'. The APIs that hold the most of them come first, in the sheet's order when left out.
      limit: How many APIs to give, 1 to 200. 20 when left out, of about 160.

    Returns:
      total, the APIs found, and apis, up to limit of them, or {"error": ...} in the API's words.
    """
    return _answer(_list_apis, query, limit)


def datacircle_best_plans(slug: str, limit: Optional[int] = None) -> Dict[str, Any]:
    """Gives an API's plans best first by their score out of 100 on Datacircle's benchmark (https://datacircle.dev),
    each with its rank, provider, plan, $ per 1,000 calls and its page: the best providers of an API.

    Args:
      slug: The API's slug, like 'email-finder' or 'linkedin-profile', as datacircle_list_apis gives it.
      limit: How many plans to give, 1 to 50. 10 when left out.

    Returns:
      The API and its plans, or {"error": ...} in the API's words. perThousand is a plan's price of 1,000 items in
      dollars, pay the plan's whole price in its currency.
    """
    return _answer(_best_plans, slug, limit)


def datacircle_search_plans(api: Optional[str] = None, query: Optional[str] = None, sort: Optional[str] = None,
                            limit: Optional[int] = None, offset: Optional[int] = None) -> Dict[str, Any]:
    """Searches every plan on Datacircle's sheet (https://datacircle.dev), or one API's, by provider or plan name,
    sorted by score, provider or price.

    Args:
      api: Only this API's plans, by its name or slug, like 'email-finder'. A provider's name goes in query, never here. Every API when left out.
      query: Words that must all appear in the provider's or plan's name, like 'bright data'.
      sort: score (best first, the default), provider (A to Z) or price ($ per 1,000, lowest first).
      limit: How many plans to give, 1 to 50. 10 when left out.
      offset: How many found plans to skip first. 0 when left out.

    Returns:
      total, offset and up to limit plans, or {"error": ...} in the API's words. perThousand is a plan's price of
      1,000 items in dollars, pay the plan's whole price in its currency.
    """
    return _answer(_search_plans, api, query, sort, limit, offset)


def datacircle_provider(slug: str) -> Dict[str, Any]:
    """Gives each API one provider sells and its rank on each on Datacircle's benchmark (https://datacircle.dev), with
    its best plan there.

    Args:
      slug: The provider's slug, like 'bright-data', or its name, like 'Bright Data', which is made a slug.

    Returns:
      The provider and its APIs, or {"error": ...} in the API's words.
    """
    return _answer(_provider, slug)


FUNCTIONS: Dict[str, Callable[..., Dict[str, Any]]] = {function.__name__: function for function in (
    datacircle_list_apis, datacircle_best_plans, datacircle_search_plans, datacircle_provider)}
TOOL_NAMES = list(FUNCTIONS)
_ARGUMENTS = {"datacircle_list_apis": ("query", "limit"), "datacircle_best_plans": ("slug", "limit"),
              "datacircle_search_plans": ("api", "query", "sort", "limit", "offset"),
              "datacircle_provider": ("slug",)}


def datacircle_tools(tool_names: Optional[Sequence[str]] = None) -> List[Callable[..., Dict[str, Any]]]:
    """The tools, for types.GenerateContentConfig(tools=datacircle_tools()) or beside one's own:
    tools=[*datacircle_tools(), my_tool]. tool_names keeps some of them only, in their order here; all four when left out."""
    if isinstance(tool_names, str):
        raise TypeError("tool_names is a list of names, like ['datacircle_best_plans']")
    for name in tool_names or []:
        if name not in FUNCTIONS:
            raise ValueError(f"Datacircle has no tool {name!r}: its tools are {', '.join(TOOL_NAMES)}")
    return [FUNCTIONS[name] for name in (TOOL_NAMES if tool_names is None else tool_names)]


def run(name: str, arguments: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """What a tool gives the model for these arguments: the API's answer, or {"error": its words}. The arguments the
    tool doesn't take are left out."""
    if name not in FUNCTIONS:
        raise ValueError(f"Datacircle has no tool {name!r}: its tools are {', '.join(TOOL_NAMES)}")
    given = arguments if isinstance(arguments, Mapping) else {}
    return FUNCTIONS[name](**{key: given.get(key) for key in _ARGUMENTS[name]})


def _field(item: Any, key: str) -> Any:
    return item.get(key) if isinstance(item, Mapping) else getattr(item, key, None)


def _calls(source: Any) -> List[Any]:
    """The function calls in a GenerateContentResponse, a Content, or a list of FunctionCall, Part or their dicts."""
    if source is None:
        return []
    if not isinstance(source, Mapping) and hasattr(source, "candidates"):
        return list(source.function_calls or [])
    if _field(source, "parts") is not None:
        source = _field(source, "parts")
    calls = []
    for item in source if isinstance(source, Iterable) and not isinstance(source, (str, bytes, Mapping)) else [source]:
        call = _field(item, "function_call") or _field(item, "functionCall") or item
        if _field(call, "name") is not None:
            calls.append(call)
    return calls


def _part(call: Any) -> types.Part:
    name = _field(call, "name")
    response = {"result": run(name, _field(call, "args"))}
    call_id = _field(call, "id")
    return types.Part(function_response=types.FunctionResponse(
        name=name, response=response, **({"id": call_id} if call_id else {})))


def function_response_parts(source: Any) -> List[types.Part]:
    """For a loop of the app's own, automatic function calling disabled: the function response part of each call of
    these four tools in a reply (a GenerateContentResponse, its content, or a list of its function calls or parts), in
    their order, each with its call's id and {"result": the tool's answer}, as the SDK's own loop gives it. Calls of
    other tools are left out, for the app to run."""
    return [_part(call) for call in _calls(source) if _field(call, "name") in FUNCTIONS]


async def afunction_response_parts(source: Any) -> List[types.Part]:
    """function_response_parts() for client.aio: the calls run at once, each HTTPS GET in a thread, their parts in the
    calls' order."""
    ours = [call for call in _calls(source) if _field(call, "name") in FUNCTIONS]
    return list(await asyncio.gather(*(asyncio.to_thread(_part, call) for call in ours)))


__all__: List[str] = ["FUNCTIONS", "TOOL_NAMES", "afunction_response_parts", "datacircle_best_plans",
                      "datacircle_list_apis", "datacircle_provider", "datacircle_search_plans", "datacircle_tools",
                      "function_response_parts", "run"]
