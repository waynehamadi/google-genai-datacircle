# google-genai-datacircle

Find the best GTM APIs. We benchmark all the GTM APIs and we put the results on our website.

Our website: https://datacircle.dev

This package gives the [Google Gen AI Python SDK](https://github.com/googleapis/python-genai) four tools that call Datacircle's open API, https://api.datacircle.dev/v1. You put the four tools in your config's `tools`. The SDK then runs each function call the model makes. You need no key and no account for Datacircle.

| Tool | What the tool gives | Call |
| --- | --- | --- |
| `datacircle_list_apis` | Every GTM API on Datacircle, with the API's slug, number of plans, number of providers and best plan | `GET /apis` |
| `datacircle_best_plans` | One API's plans, sorted by score out of 100, best first. Each plan comes with a rank and a price per 1,000 calls | `GET /apis/{slug}/best` |
| `datacircle_search_plans` | Plans that match a provider or plan name, on all APIs or on one API. You can sort them by score, provider or price | `GET /plans` |
| `datacircle_provider` | The APIs a provider sells, and the provider's rank on each API | `GET /providers/{slug}` |

## Install

```bash
pip install google-genai-datacircle
```

google-genai-datacircle works with `google-genai` 1.0.0 and later, on Python 3.10 and later. It works on the Gemini API and on Vertex AI.

## Use the tools

Put the tools in your config. The SDK's automatic function calling runs each call and sends the answer back to the model:

```python
from google import genai
from google.genai import types
from google_genai_datacircle import datacircle_tools

client = genai.Client()
chat = client.chats.create(
    model="gemini-2.5-flash",
    config=types.GenerateContentConfig(tools=datacircle_tools()),
)
response = chat.send_message("Who are the 3 best providers for the email-finder API?")
print(response.text)
```

The same config works with `client.models.generate_content()`, `generate_content_stream()`, `send_message_stream()` and the `client.aio` forms of each. Each tool is a plain function. The SDK reads each function's declaration from the function's type hints and docstring.

## Use them beside your own tools

You can put the Datacircle tools in the same list as yours: `tools=[*datacircle_tools(), get_weather]`. To give the model only some of the tools, list their names: `datacircle_tools(["datacircle_best_plans"])`.

## Run the calls yourself

With automatic function calling turned off, `function_response_parts()` runs the Datacircle calls in a response. It gives you one function response part for each call, with the call's id. Calls of your own tools are left out, for your code to run:

```python
from google import genai
from google.genai import types
from google_genai_datacircle import datacircle_tools, function_response_parts

client = genai.Client()
config = types.GenerateContentConfig(
    tools=datacircle_tools(),
    automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
)
contents = [types.Content(role="user", parts=[types.Part(text="What does Bright Data sell?")])]
response = client.models.generate_content(model="gemini-2.5-flash", contents=contents, config=config)

while response.function_calls:
    contents.append(response.candidates[0].content)
    contents.append(types.Content(role="user", parts=function_response_parts(response)))
    response = client.models.generate_content(model="gemini-2.5-flash", contents=contents, config=config)

print(response.text)
```

With `client.aio`, use `await afunction_response_parts(response)`. It runs the calls at the same time. Your event loop keeps running.

## Call a tool yourself

You can call each tool without a model. You get the tool's answer as a dict:

```python
from google_genai_datacircle import datacircle_best_plans

answer = datacircle_best_plans("email-finder", limit=3)
print(answer["plans"])
```

## What the model reads

Each tool gives the model a JSON object. The SDK sends it as `{"result": ...}`. Each plan comes with a rank, provider, plan, score, price per 1,000 (`perThousand`, in dollars) and a page on datacircle.dev. That page lists every field.

You can give a provider's name in place of a slug. The tool turns `Bright Data` into `bright-data`.

The tool returns `{"error": "..."}` with the API's message when the API gives no data, such as for an unknown slug. The error for an unknown API slug lists every valid slug. The tool checks each number first. For a number out of range, the tool returns an error and makes no API call. If the network fails, the tool returns `{"error": "..."}` with the network error's message. The model can then call the tool again.

## Network

Each tool call makes one HTTPS GET request to https://api.datacircle.dev/v1 and nothing else. The request holds only the tool's own arguments: no key and nothing from your chats. The API takes up to 60 calls a minute from one IP address. The tool waits once, for a minute at most, when the API asks the tool to wait. Each call uses only Python's standard library. Nothing goes to disk.

## Links

- Datacircle: https://datacircle.dev
- The API: https://datacircle.dev/api
- The API's spec: https://api.datacircle.dev/v1/openapi.json
- What each key means: https://datacircle.dev/fields

MIT license.
