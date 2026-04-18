# Projbahn

This repo contains:

- A Django + django-ninja HTTP API for projects and features
- A terminal frontend built with `rich`

## Run the backend

```bash
uv run manage.py runserver 8001
```

## Run the terminal app

In a second terminal:

```bash
uv run manage.py projbahn_tui
```

The terminal app talks to the backend over `http://127.0.0.1:8001/api` and lets you:

- Create, edit, and delete projects
- Open a project and manage its features
- Create root-level or nested child features
- Re-parent features within the same project
