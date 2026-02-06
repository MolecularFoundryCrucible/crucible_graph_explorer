# Setup

 Environment variables needed, either normally or via `.env` file:

```sh
CRUCIBLE_API_KEY=<ADMINKEY> #SECRET!
PYOIDC_SECRET=<OIDC_SECRET-could-be-anything-you-want-for-a-given-instance> #local secret
ORCID_CLIENT_ID=<get-from-orcid-example:APP-E5VUS6XSJS5VFNEN> # not secret
ORCID_CLIENT_SECRET=<get-from-orcid-should-look-like-UUID> #SECRET!
OIDC_REDIRECT_URI=http://127.0.0.1:8000/redirect_uri # or similar, needs to match URL served and be added to ORCiD developer page.
```

# Testing

Run locally

```sh
uv run flask --app crucible_graph_explore_flask_app.py run --debug --port 8000
```

Running Flask-Vite frontend components for development
```sh
uv run flask --app crucible_graph_explore_flask_app.py vite start
```

## Docker run locally

```sh
docker build -t crucible_graph_explorer . 
docker run -p 8080:8080  --env-file .env --name crucible_graph_explorer crucible_graph_explorer 
```
