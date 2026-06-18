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
            project_id=project_id, limit=None, include_links=True
        )
        datasets_f = ex.submit(
            crucible_client.datasets.list,
            project_id=project_id, limit=None, include_metadata=include_metadata,
        )
    pc['samples']  = samples_f.result()
    pc['datasets'] = datasets_f.result()

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

    return pc
