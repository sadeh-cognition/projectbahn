# AGENTS

This file concatenates the rules from `.agents/rules/` in alphabetical order.

## endpoint-tests.md

Whenever you create a new endpoint or modify an existing one make sure the endpoint is tested functionally.
To test the endpoint use the TestClient of the django-ninja package.
For fixtures and test dependencies use pytest fixtures.
In tests that call the backend API use the ninja schemas that define the endpoints incoming request type. Also, use the response schema to parse the response from the HTTP API.
Do not use any mocks.
Do not monkeypatch anything.

## graphdb.md

To store data in a graph database use ladybugdb documented here: https://docs.ladybugdb.com/tutorials/python/

## http-api.md

Use django-ninja for creating HTTP APIs.
django-ninja docs are here: https://django-ninja.dev/

## llm-interactions.md

When interacting with a LLM use dspy for specifying the input and outputs using dspy signatures and modules.

## package-to-use-for-cli-comamnds.md

To create CLI commands use the Django built-in methods.
Use django-click to create CLI commands.
django-click is documented here: https://github.com/django-commons/django-click

## python-env-manager.md

Use uv for managing the python environment.
Use uv for managing python package dependencies: `uv add requests` instead of `pip install requests`.
Use uv for envoking python commands.

## running-backend-server.md

To run the backend Django server use this command:
`uv run manage.py runserver 8001`

Note: the port number is 8001

## tech-stack.md

This is a terminal based application i.e. a TUI.
The user interface should use the python `rich` package.
The backend is a Django HTTP API implemented using `django-ninja`.

When interacting with the backend, always use the HTTP API.
Do not use the database directly.
Always use the HTTP API for fetching, updating, or deleting data.

When writing Django code, try your hardest not to use Django signals.

## test-tools.md

For testing use the pytest-django package documented here: <https://pytest-django.readthedocs.io/en/latest/>
When creating fixtures that involve django ORM models use the model-bakery package documented here: <https://github.com/model-bakers/model_bakery>
When testing the Django admin use `curl` command instead of the browser agent.
When testing involves using LLMs use the "groq" provider and model name "llama-3.1-8b-instant".
Do not use ollama in tests.

## type-hints.md

Use type hints even when writing Django code. Use this package https://github.com/typeddjango/django-stubs for type hinting Django code.

## ui-backend-interactions.md

All TUI interactions with data should be done via the backend HTTP API.
All business logic should be extracted into functions which can be used without the TUI.
When calling the backend API use the ninja schemas that define the endpoints incoming request type. Also, use the response schema to parse the response from the HTTP API.

## vector-db.md

Use ChromaDB as vector db. Docs are here: https://docs.trychroma.com/docs/overview/getting-started
Use Chromadb for vector and text search features.
Do not monkeypatch Chroma in tests.
To create embeddings use the local LMStudio server I have running in my environment.
The embedding model and provider are configured in the `EmbeddingModelConfig` table.
