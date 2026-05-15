// vite/src/graph-render.js
export async function mountGraph({ fetchUrl, showDatasetToggle = false }) {
  let cyInstance = null;
  let graphData  = null;
  let graphLoaded = false;
  let datasetsVisible = true;

  const spinner    = document.getElementById('cy-spinner');
  const errorEl    = document.getElementById('cy-error');
  const zoomHint   = document.getElementById('zoomHint');

  function _graphError(msg) {
    if (spinner) spinner.style.display = 'none';
    if (!errorEl) return;
    errorEl.innerHTML =
      `<i class="bi bi-exclamation-circle mb-2" style="font-size:1.5rem;color:var(--bs-warning);"></i>`
      + `<span style="font-size:0.85rem;">${msg}</span>`;
    errorEl.style.display = 'flex';
  }

  async function renderGraph() {
    if (spinner) spinner.style.display = 'flex';
    if (errorEl) errorEl.style.display = 'none';
    if (cyInstance) { cyInstance.destroy(); cyInstance = null; }
    const layoutBtn = document.getElementById('toggleLayoutBtn');
    if (layoutBtn) layoutBtn.innerHTML = '<i class="bi bi-arrow-left-right me-1"></i>Vertical';

    try {
      if (!graphData) {
        const r = await fetch(fetchUrl);
        if (!r.ok) throw new Error(`Graph API returned ${r.status}`);
        graphData = await r.json();
      }

      const initGraph = await window.loadEntityGraph();

      if (!graphData.nodes || graphData.nodes.length === 0) {
        _graphError('No graph data for this resource.');
        return;
      }

      cyInstance = initGraph('cy', graphData);

      if (showDatasetToggle && !datasetsVisible && cyInstance) {
        _applyDatasetVisibility(false);
      }

      if (zoomHint) {
        zoomHint.style.transition = 'none';
        zoomHint.style.opacity = '1';
        setTimeout(() => {
          zoomHint.style.transition = 'opacity 1.5s';
          zoomHint.style.opacity = '0';
        }, 2500);
      }
    } catch (err) {
      console.error('Graph render failed:', err);
      _graphError(err.message || 'Could not load graph');
    } finally {
      if (spinner) spinner.style.display = 'none';
    }
  }

  function _applyDatasetVisibility(visible) {
    if (!cyInstance) return;
    const display = visible ? 'element' : 'none';
    cyInstance.nodes('[type="dataset"]').style('display', display);
    cyInstance.edges().forEach(edge => {
      const hidden = edge.source().style('display') === 'none'
                  || edge.target().style('display') === 'none';
      edge.style('display', hidden ? 'none' : 'element');
    });
    cyInstance.one('layoutstop', () => {
      cyInstance.fit(cyInstance.nodes(':visible'), 30);
    });
    cyInstance.relayout(true, cyInstance.elements(':visible'));
    const thumbBtn = document.getElementById('toggleThumbnailsBtn');
    if (thumbBtn) thumbBtn.disabled = !visible;
  }

  const toggleLayoutBtn = document.getElementById('toggleLayoutBtn');
  if (toggleLayoutBtn) {
    toggleLayoutBtn.addEventListener('click', function() {
      if (cyInstance && cyInstance.toggleLayout) {
        const newLayout = cyInstance.toggleLayout();
        this.innerHTML = newLayout === 'LR'
          ? '<i class="bi bi-arrow-left-right me-1"></i>Vertical'
          : '<i class="bi bi-arrow-down me-1"></i>Horizontal';
        cyInstance.one('layoutstop', () => {
          cyInstance.resize();
          cyInstance.fit(cyInstance.nodes(':visible'), 30);
        });
      }
    });
  }

  const toggleThumbnailsBtn = document.getElementById('toggleThumbnailsBtn');
  if (toggleThumbnailsBtn) {
    toggleThumbnailsBtn.addEventListener('click', function() {
      if (cyInstance && cyInstance.toggleThumbnails) {
        const visible = cyInstance.toggleThumbnails();
        this.innerHTML = visible
          ? '<i class="bi bi-image me-1"></i>Thumbnails'
          : '<i class="bi bi-image-fill me-1"></i>No Thumbnails';
      }
    });
  }

  const fitBtn = document.getElementById('fitBtn');
  if (fitBtn) {
    fitBtn.addEventListener('click', () => { if (cyInstance) cyInstance.fit(); });
  }

  if (showDatasetToggle) {
    const toggleDatasetsBtn = document.getElementById('toggleDatasetsBtn');
    if (toggleDatasetsBtn) {
      toggleDatasetsBtn.addEventListener('click', function() {
        datasetsVisible = !datasetsVisible;
        _applyDatasetVisibility(datasetsVisible);
        this.innerHTML = datasetsVisible
          ? '<i class="bi bi-database me-1"></i>Hide Datasets'
          : '<i class="bi bi-database me-1"></i>Show Datasets';
      });
    }
  }

  const fullscreenBtn = document.getElementById('fullscreenBtn');
  if (fullscreenBtn) {
    fullscreenBtn.addEventListener('click', async () => {
      const section = document.getElementById('section-graph');
      const body    = section.querySelector('.res-section-body');
      if (!document.fullscreenElement) {
        if (body.style.display === 'none') {
          toggleSection(section.querySelector('.res-section-header'));
        }
        if (!graphLoaded) {
          graphLoaded = true;
          await renderGraph();
        } else if (cyInstance) {
          cyInstance.resize(); cyInstance.fit();
        }
        section.requestFullscreen().catch(err => console.error(err));
      } else {
        document.exitFullscreen();
      }
    });

    document.addEventListener('fullscreenchange', () => {
      fullscreenBtn.innerHTML = document.fullscreenElement
        ? '<i class="bi bi-fullscreen-exit me-1"></i>Exit'
        : '<i class="bi bi-fullscreen me-1"></i>Fullscreen';
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (cyInstance) { cyInstance.resize(); cyInstance.fit(); }
      }));
    });
  }

  window.toggleGraphSection = function(header) {
    toggleSection(header);
    const body = header.nextElementSibling;
    if (body.style.display !== 'none') {
      if (!graphLoaded) {
        graphLoaded = true;
        renderGraph();
      } else if (cyInstance) {
        cyInstance.resize(); cyInstance.fit();
      }
    }
  };

}
