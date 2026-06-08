# Setup
Branch for cloud testing
When changes are pushed to this branch, the image will be built and deployed at https://crucible-graph-explorer-776258882599.us-central1.run.app/
The main deployment is now available at https://crucible.lbl.gov/explore
 
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

## GCS access locally

Dataset views that use `gcs_access` (e.g. `pollux_oospec_gcs`) require credentials
to read from the `mf-storage-prod` bucket. Locally, use ADC with service account
impersonation:

```sh
gcloud auth application-default login \
    --impersonate-service-account=mf-storage-prod-reader@mf-crucible.iam.gserviceaccount.com
```

This writes credentials to `~/.config/gcloud/application_default_credentials.json`,
which `gcsfs.GCSFileSystem()` picks up automatically (no env vars needed).

To verify access:

```sh
uv run python -c "
import gcsfs
fs = gcsfs.GCSFileSystem()
print(fs.ls('mf-storage-prod', detail=False)[:3])
"
```

In production on Cloud Run, credentials are provided automatically via the
Cloud Run service identity — see below.

## Docker run locally

```sh
docker build -t crucible_graph_explorer .
docker run -p 8000:8000  --env-file .env --name crucible_graph_explorer crucible_graph_explorer
```

## Cloud Run — GCS credentials

Cloud Run services run as a **service identity** (a service account). `gcsfs` picks
up credentials automatically from the GCP metadata server — no key files or env vars
needed in the container.

### One-time setup

The service identity is `graph-explorer-cloudrun@mf-crucible.iam.gserviceaccount.com`.
Run these commands once to create it and grant the necessary permissions:

```sh
# Create the SA
gcloud iam service-accounts create graph-explorer-cloudrun \
    --project=mf-crucible \
    --display-name="Crucible Graph Explorer (Cloud Run)"

# GCS bucket read access
gcloud storage buckets add-iam-policy-binding gs://mf-storage-prod \
    --member="serviceAccount:graph-explorer-cloudrun@mf-crucible.iam.gserviceaccount.com" \
    --role="roles/storage.objectViewer"

# Secret Manager access — granted per secret (least privilege)
for SECRET in crucible_admin_apikey pyoidc_secret_key orcid_client_id_esb orcid_client_secret_esb mfdata-cborg-api-key; do
    gcloud secrets add-iam-policy-binding $SECRET \
        --project=mf-crucible \
        --member="serviceAccount:graph-explorer-cloudrun@mf-crucible.iam.gserviceaccount.com" \
        --role="roles/secretmanager.secretAccessor"
done
```

`cloudbuild.yaml` passes `--service-account` on every deploy, so no manual step is
needed after the initial setup.

No changes to application code are required. `gcsfs.GCSFileSystem()` with no
arguments authenticates via the GCP metadata server when running on Cloud Run.

# LLM Access via GCP VertexAI

In order for LLM chat interface `routes/chat.py` to work we need to connect 
to an LLM provider. 

### Run Once to add service account to Vertex AI:

Grant Vertex AI access to the service account:
```sh
gcloud projects add-iam-policy-binding mf-crucible \
--member="serviceAccount:graph-explorer-cloudrun@mf-crucible.iam.gserviceaccount.com" \
--role="roles/aiplatform.user"
```

Enable the Vertex AI API (if not already):
```sh
gcloud services enable aiplatform.googleapis.com --project=mf-crucible
```

### Local testing — two options:

Option A — your own credentials (simplest, but you need aiplatform.user on your account too):
```sh
gcloud auth application-default login
```

Option B — impersonate the service account exactly as Cloud Run does (recommended for parity):

#### One-time: give your account permission to impersonate the SA
```sh
gcloud iam service-accounts add-iam-policy-binding \
graph-explorer-cloudrun@mf-crucible.iam.gserviceaccount.com \
--member="user:YOUR_GOOGLE_ACCOUNT@lbl.gov" \
--role="roles/iam.serviceAccountTokenCreator"
```

#### Then locally:
```sh
gcloud auth application-default login \
--impersonate-service-account=graph-explorer-cloudrun@mf-crucible.iam.gserviceaccount.com

gcloud iam service-accounts keys create .secret/graph-explorer-sa-key.json \
--iam-account=graph-explorer-cloudrun@mf-crucible.iam.gserviceaccount.com
```

After either option, make sure your local .env has `VERTEX_PROJECT_ID=mf-crucible` and `VERTEX_REGION=us-central1` (matching .env.example).

