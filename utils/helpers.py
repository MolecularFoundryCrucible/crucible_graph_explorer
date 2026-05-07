import re
import markdown as md_lib


def humanize_size(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return '—'
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if n < 1024 or unit == 'TB':
            return f'{n} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


def abbrev_name(first: str, last: str) -> str:
    """Format 'Fabrice Roncoroni' → 'F. Roncoroni', 'Devin G. Prendergast' → 'D. G. Prendergast'."""
    initials = ' '.join(w[0].upper() + '.' for w in (first or '').split() if w)
    last = (last or '').strip()
    if initials and last:
        return f"{initials} {last}"
    return (initials or last).strip()


def render_markdown(md_content: str, project_id: str) -> str:
    """Resolve wiki-style links then convert markdown to HTML.

    Supported link syntax:
      [[dataset:ID|Label]]  →  [Label](/<project_id>/dataset/ID)
      [[sample:ID|Label]]   →  [Label](/<project_id>/sample-graph/ID)
    """
    def replace_dataset_link(match):
        dataset_id = match.group(1)
        name = match.group(2) if match.group(2) else f'Dataset-{dataset_id}'
        return f'[{name}](/{project_id}/dataset/{dataset_id})'

    def replace_sample_link(match):
        sample_id = match.group(1)
        name = match.group(2) if match.group(2) else f'Sample-{sample_id}'
        return f'[{name}](/{project_id}/sample-graph/{sample_id})'

    md_content = re.sub(
        r'\[\[dataset:([^\]|]+)(?:\|([^\]]+))?\]\]',
        replace_dataset_link, md_content
    )
    md_content = re.sub(
        r'\[\[sample:([^\]|]+)(?:\|([^\]]+))?\]\]',
        replace_sample_link, md_content
    )
    return md_lib.markdown(md_content, extensions=['extra', 'codehilite', 'tables'])
