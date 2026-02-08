FROM python:3.11-trixie

# Install Node.js for building Vite assets
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    rm -rf /var/lib/apt/lists/*

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

# Build Vite assets for production
WORKDIR /app/vite
RUN npm install && npm run build

# Return to app directory
WORKDIR /app

# Set Flask-Vite to production mode
ENV FLASK_ENV=production

#CMD ["gunicorn", "--bind", ":8080", "--workers", "1", "--threads", "8", "app:app"]
# We use 'sh -c' so that the $PORT variable is expanded at runtime
CMD ["sh", "-c", "uv run gunicorn --bind :${PORT:-8080} --workers 1 --threads 8 crucible_graph_explore_flask_app:app"]