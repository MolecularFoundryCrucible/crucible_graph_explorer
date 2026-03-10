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
