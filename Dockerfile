FROM python:3.11-trixie
#UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Copy the project into the image
COPY . /app

# Disable development dependencies
ENV UV_NO_DEV=1

# Sync the project into a new environment, asserting the lockfile is up to date
WORKDIR /app
# note that this will rebuild uv enviroment everytime because any changes to /app
# will require a rebuild of the following layers
# -- there are solutions but are more complex, so lets leave it for now
RUN uv sync --locked 

#CMD ["gunicorn", "--bind", ":8080", "--workers", "1", "--threads", "8", "app:app"]
# We use 'sh -c' so that the $PORT variable is expanded at runtime
CMD ["sh", "-c", "uv run gunicorn --bind :${PORT:-8080} --workers 1 --threads 8 crucible_graph_explore_flask_app:app"]