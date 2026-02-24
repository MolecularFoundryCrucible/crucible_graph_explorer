import { EditorState } from '@codemirror/state';
import { EditorView, keymap, lineNumbers, highlightActiveLine } from '@codemirror/view';
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { markdown } from '@codemirror/lang-markdown';
import { autocompletion, completionKeymap } from '@codemirror/autocomplete';
import MarkdownIt from 'markdown-it';

function wikiLinkPlugin(md, projectId) {
  md.inline.ruler.push('wiki_links', (state, silent) => {
    // Must start with [[
    if (state.src.charCodeAt(state.pos) !== 0x5B ||
        state.src.charCodeAt(state.pos + 1) !== 0x5B) {
      return false;
    }

    const start = state.pos + 2;
    const end = state.src.indexOf(']]', start);
    if (end === -1) return false;

    const content = state.src.slice(start, end);
    const colonIdx = content.indexOf(':');
    if (colonIdx === -1) return false;

    const type = content.slice(0, colonIdx);
    if (type !== 'sample' && type !== 'dataset') return false;

    const rest = content.slice(colonIdx + 1);
    const pipeIdx = rest.indexOf('|');
    const id = pipeIdx === -1 ? rest : rest.slice(0, pipeIdx);
    const name = pipeIdx === -1
      ? `${type === 'sample' ? 'Sample' : 'Dataset'}-${id}`
      : rest.slice(pipeIdx + 1);

    if (!silent) {
      const href = type === 'sample'
        ? `/${projectId}/sample-graph/${id}`
        : `/${projectId}/dataset/${id}`;

      const tokenOpen = state.push('link_open', 'a', 1);
      tokenOpen.attrSet('href', href);
      tokenOpen.attrSet('class', `wiki-link wiki-link-${type}`);

      const tokenText = state.push('text', '', 0);
      tokenText.content = name;

      state.push('link_close', 'a', -1);
    }

    state.pos = end + 2;
    return true;
  });
}

export function initMDNoteEditor({ containerId, previewId, projectId, initialContent, saveUrl }) {
  const mdRenderer = new MarkdownIt({ linkify: true, typographer: true });
  wikiLinkPlugin(mdRenderer, projectId);

  function updatePreview(content) {
    const previewEl = document.getElementById(previewId);
    if (previewEl) {
      previewEl.innerHTML = mdRenderer.render(content);
    }
  }

  function wikiLinkCompletion(context) {
    const match = context.matchBefore(/\[\[(sample|dataset):[^\]]*/);
    if (!match) return null;

    const innerMatch = match.text.match(/^\[\[(sample|dataset):(.*)$/);
    if (!innerMatch) return null;

    const type = innerMatch[1];
    const query = innerMatch[2];
    const apiPath = type === 'sample' ? 'samples' : 'datasets';

    return fetch(`/${projectId}/api/${apiPath}?q=${encodeURIComponent(query)}`)
      .then(r => r.json())
      .then(items => ({
        from: match.from,
        filter: false,
        options: items.map(item => ({
          label: item.name,
          detail: item.id.slice(0, 13),
          apply: `[[${type}:${item.id}|${item.name}]]`
        }))
      }))
      .catch(() => null);
  }

  const state = EditorState.create({
    doc: initialContent,
    extensions: [
      lineNumbers(),
      history(),
      highlightActiveLine(),
      markdown(),
      autocompletion({ override: [wikiLinkCompletion], activateOnTyping: true, icons: false }),
      keymap.of([...defaultKeymap, ...historyKeymap, ...completionKeymap]),
      EditorView.updateListener.of(update => {
        if (update.docChanged) {
          updatePreview(update.state.doc.toString());
        }
      }),
      EditorView.theme({
        '&': { height: '100%' },
        '.cm-scroller': { overflow: 'auto', fontFamily: 'monospace', fontSize: '14px' },
      }),
    ]
  });

  const view = new EditorView({
    state,
    parent: document.getElementById(containerId)
  });

  updatePreview(initialContent);

  async function save() {
    const content = view.state.doc.toString();
    const saveBtn = document.getElementById('mdnote-save-btn');
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = 'Saving...';
    }

    try {
      const response = await fetch(saveUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content })
      });

      if (response.ok) {
        if (saveBtn) saveBtn.textContent = 'Saved!';
        setTimeout(() => {
          if (saveBtn) {
            saveBtn.disabled = false;
            saveBtn.textContent = 'Save';
          }
        }, 2000);
      } else {
        throw new Error(`HTTP ${response.status}`);
      }
    } catch (err) {
      console.error('Save failed:', err);
      if (saveBtn) {
        saveBtn.disabled = false;
        saveBtn.textContent = 'Save Failed - Retry';
      }
    }
  }

  const saveBtn = document.getElementById('mdnote-save-btn');
  if (saveBtn) saveBtn.addEventListener('click', save);

  return { view, save };
}
