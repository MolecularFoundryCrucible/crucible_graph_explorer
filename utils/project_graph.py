import logging

logger = logging.getLogger(__name__)


def generate_project_cache(project_id, crucible_client, include_metadata=True, save=False):
    """Fetch and index all samples and datasets for a project.

    Returns a dict with keys: project_id, samples, datasets,
    samples_by_id, samples_by_name, datasets_by_id.
    """
    from concurrent.futures import ThreadPoolExecutor

    logger.debug("Fetching project cache: project_id=%s include_metadata=%s", project_id, include_metadata)
    pc = dict(project_id=project_id)

    with ThreadPoolExecutor(max_workers=2) as ex:
        samples_f  = ex.submit(
            crucible_client.samples.list,
            project_id=project_id, limit=None, include_links=True,
        )
        datasets_f = ex.submit(
            crucible_client.datasets.list,
            project_id=project_id, limit=None, include_metadata=include_metadata,
        )
    pc['samples']  = samples_f.result()
    pc['datasets'] = datasets_f.result()

    # Normalize 'datasets' on each sample: with include_links=True the API puts associated
    # datasets into 'links' (as LinkedResource objects); 'datasets' compat field is null.
    for s in pc['samples']:
        if not s.get('datasets'):
            s['datasets'] = [
                {'unique_id': lnk['unique_id'], 'dataset_name': lnk.get('name', '')}
                for lnk in (s.get('links') or [])
                if lnk.get('resource_type') == 'dataset' and lnk.get('relationship') == 'associated'
            ]

    pc['samples_by_id'] = {s['unique_id']: s for s in pc['samples']}
    pc['samples_by_name'] = {s['sample_name']: s for s in pc['samples']}
    pc['datasets_by_id'] = {ds['unique_id']: ds for ds in pc['datasets']}

    # Pull in datasets linked to project samples but not in the project dataset list.
    # These synthetic dicts only have unique_id/dataset_name; use them as-is since we
    # can't fetch full info here without extra API calls. Callers must use .get() for
    # optional fields like measurement, instrument_name, etc.
    for s in pc['samples_by_id'].values():
        for ds in s.get('datasets') or []:
            uid = ds['unique_id']
            if uid not in pc['datasets_by_id']:
                pc['datasets_by_id'][uid] = ds
                pc['datasets'].append(ds)

    return pc
