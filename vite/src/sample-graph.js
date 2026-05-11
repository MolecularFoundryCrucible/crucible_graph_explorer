import cytoscape from 'cytoscape';
import elk from 'cytoscape-elk';

cytoscape.use(elk);

function elkLayout(rankDir, animate) {
  return {
    name: 'elk',
    nodeDimensionsIncludeLabels: false,
    fit: false,
    padding: 30,
    animate: !!animate,
    animationDuration: animate || 400,
    elk: {
      algorithm: 'layered',
      'elk.direction': rankDir === 'LR' ? 'RIGHT' : 'DOWN',
      'elk.spacing.nodeNode': 40,
      'elk.layered.spacing.nodeNodeBetweenLayers': 80,
      'elk.edgeRouting': 'ORTHOGONAL',
      'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
    }
  };
}

function getCSSVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

function createNodePopup() {
  const el = document.createElement('div');
  el.style.cssText = 'position:fixed;display:none;z-index:1050;max-width:272px;pointer-events:auto;font-family:inherit;';
  el.innerHTML = `
    <div class="cg-graph-popup">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:0.5rem;margin-bottom:0.4rem;">
        <span class="popup-badge" style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:0.7rem;font-weight:600;border:1px solid;white-space:nowrap;"></span>
        <button class="popup-close" style="background:none;border:none;cursor:pointer;padding:0;line-height:1;color:var(--bs-secondary-color);font-size:1.25rem;flex-shrink:0;margin-top:-2px;">&times;</button>
      </div>
      <div class="popup-title" style="font-weight:600;word-break:break-word;margin-bottom:0.3rem;line-height:1.35;font-size:0.88rem;"></div>
      <div class="popup-img" style="display:none;margin-bottom:0.4rem;">
        <img style="max-width:100%;max-height:96px;object-fit:contain;border-radius:4px;border:1px solid var(--bs-border-color);">
      </div>
      <a class="popup-link" href="#" style="display:inline-flex;align-items:center;gap:0.3rem;font-size:0.8rem;color:var(--cg-link);text-decoration:none;">
        View details <i class="bi bi-arrow-right" style="font-size:0.72rem;"></i>
      </a>
    </div>`;
  document.body.appendChild(el);

  let ignoreNextClick = false;

  el.querySelector('.popup-close').addEventListener('click', hide);
  document.addEventListener('keydown', e => { if (e.key === 'Escape') hide(); });
  document.addEventListener('click', e => {
    if (ignoreNextClick) { ignoreNextClick = false; return; }
    if (!el.contains(e.target)) hide();
  });

  function show(node, clientX, clientY) {
    ignoreNextClick = true;
    const label   = node.data('label') || node.data('name') || '';
    const type    = node.data('type') || 'sample';
    const measure = node.data('measurement') || '';
    const thumb   = node.data('thumbnail');
    const url     = node.data('url') || '#';

    const badge = el.querySelector('.popup-badge');
    const isDataset  = type === 'dataset';
    const badgeColor = isDataset ? getCSSVar('--cy-dataset-color') : getCSSVar('--cy-sample-color');
    badge.textContent = measure || (isDataset ? 'Dataset' : 'Sample');
    badge.style.color       = badgeColor;
    badge.style.borderColor = badgeColor + '66';
    badge.style.background  = badgeColor + '18';

    el.querySelector('.popup-title').textContent = label;

    const imgDiv = el.querySelector('.popup-img');
    if (thumb) {
      imgDiv.querySelector('img').src = thumb;
      imgDiv.style.display = '';
    } else {
      imgDiv.style.display = 'none';
    }

    el.querySelector('.popup-link').href = url;
    el.style.display = 'block';

    const rect = el.getBoundingClientRect();
    let x = clientX + 14;
    let y = clientY - rect.height / 2;
    if (x + rect.width > window.innerWidth - 8)  x = clientX - rect.width - 14;
    if (y < 8)                                    y = 8;
    if (y + rect.height > window.innerHeight - 8) y = window.innerHeight - rect.height - 8;
    el.style.left = x + 'px';
    el.style.top  = y + 'px';
  }

  function hide() { el.style.display = 'none'; }

  return { show, hide };
}

export function initEntityGraph(containerId, graphData) {
  const { nodes, edges, centerNodeId } = graphData;
  let currentRankDir = 'LR';

  const sampleColor  = getCSSVar('--cy-sample-color')  || '#4a7ba7';
  const datasetColor = getCSSVar('--cy-dataset-color') || '#5a9e6f';
  const accentMid    = getCSSVar('--cg-accent-mid')    || '#6fa4b0';
  const accent       = getCSSVar('--cg-accent')        || '#a8c4cd';

  const cyNodes = nodes.map(node => ({
    data: {
      id: node.id,
      label: node.label,
      type: node.type,
      url: node.url,
      description: node.description || '',
      measurement: node.measurement || '',
      ...(node.thumbnail ? { thumbnail: node.thumbnail } : {}),
      isCenterNode: node.id === centerNodeId
    }
  }));

  const cyEdges = edges.map(edge => ({
    data: {
      id: `${edge.source}-${edge.target}`,
      source: edge.source,
      target: edge.target
    }
  }));

  const cy = cytoscape({
    container: document.getElementById(containerId),
    elements: { nodes: cyNodes, edges: cyEdges },
    style: [
      {
        selector: 'node[type="sample"]',
        style: {
          'background-color': sampleColor,
          'label': 'data(label)',
          'color': '#fff',
          'text-valign': 'center',
          'text-halign': 'center',
          'font-size': '11px',
          'font-family': "'IBM Plex Sans', sans-serif",
          'width': node => Math.max(node.data('label').length * 7, 60),
          'height': 36,
          'shape': 'roundrectangle',
          'text-wrap': 'wrap',
          'text-max-width': '120px'
        }
      },
      {
        selector: 'node[type="dataset"]',
        style: {
          'background-color': datasetColor,
          'label': 'data(label)',
          'color': '#fff',
          'text-valign': 'center',
          'text-halign': 'center',
          'font-size': '10px',
          'font-family': "'IBM Plex Sans', sans-serif",
          'width': node => Math.max(node.data('label').length * 6, 60),
          'height': 28,
          'shape': 'roundrectangle',
          'text-wrap': 'wrap',
          'text-max-width': '120px'
        }
      },
      {
        selector: 'node[type="dataset"][thumbnail]',
        style: {
          'background-image': 'data(thumbnail)',
          'background-fit': 'contain',
          'background-color': '#f8f9fa',
          'border-width': 2,
          'border-color': datasetColor,
          'color': '#333',
          'width': 100,
          'height': 78,
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 6,
          'font-size': '10px'
        }
      },
      {
        selector: 'node[?isCenterNode]',
        style: {
          'border-width': 3,
          'border-color': accentMid,
          'font-weight': 'bold',
          'font-size': '12px',
          'shape': 'roundrectangle'
        }
      },
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'line-color': accent,
          'target-arrow-color': accent,
          'target-arrow-shape': 'triangle',
          'curve-style': 'unbundled-bezier',
          'arrow-scale': 1.1
        }
      },
      {
        selector: 'node.hovered:not([?isCenterNode])',
        style: {
          'border-width': 2,
          'border-color': accentMid,
          'border-opacity': 0.85
        }
      },
      {
        selector: 'node:selected',
        style: {
          'border-width': 3,
          'border-color': accentMid,
          'background-blacken': -0.15
        }
      }
    ],
    layout: elkLayout('LR'),
    minZoom: 0.2,
    maxZoom: 3,
    userZoomingEnabled: false
  });

  document.getElementById(containerId).addEventListener('wheel', e => {
    if (e.ctrlKey || e.metaKey) {
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
      cy.zoom({ level: Math.min(Math.max(cy.zoom() * factor, cy.minZoom()), cy.maxZoom()),
                renderedPosition: { x: e.offsetX, y: e.offsetY } });
    }
  }, { passive: false });

  const popup = createNodePopup();

  cy.on('tap', evt => { if (evt.target === cy) popup.hide(); });

  cy.on('tap', 'node', function(evt) {
    const node = evt.target;
    const orig = evt.originalEvent;
    if (orig.ctrlKey || orig.metaKey) {
      const url = node.data('url');
      if (url) {
        cy.nodes().style('opacity', 0.3);
        node.style('opacity', 1);
        document.body.style.cursor = 'wait';
        window.location.href = url;
      }
      return;
    }
    popup.show(node, orig.clientX, orig.clientY);
  });

  cy.on('mouseover', 'node', function(evt) {
    evt.target.addClass('hovered');
    document.getElementById(containerId).style.cursor = 'pointer';
  });
  cy.on('mouseout', 'node', function(evt) {
    evt.target.removeClass('hovered');
    document.getElementById(containerId).style.cursor = 'default';
  });

  cy.layoutDir = currentRankDir;

  cy.relayout = function(animate) {
    cy.layout(elkLayout(currentRankDir, animate !== false ? 400 : 0)).run();
  };

  cy.toggleLayout = function() {
    currentRankDir = currentRankDir === 'LR' ? 'TB' : 'LR';
    cy.layoutDir = currentRankDir;
    cy.relayout();
    return currentRankDir;
  };

  let thumbnailsVisible = true;
  cy.toggleThumbnails = function() {
    thumbnailsVisible = !thumbnailsVisible;
    const thumbNodes = cy.nodes('[type="dataset"][thumbnail]');
    if (thumbnailsVisible) {
      thumbNodes.removeStyle();
    } else {
      thumbNodes.style({
        'background-image': 'none',
        'background-color': datasetColor,
        'color': '#fff',
        'width': node => Math.max(node.data('label').length * 6, 60),
        'height': 28,
        'text-valign': 'center',
        'text-margin-y': 0
      });
    }
    return thumbnailsVisible;
  };

  return cy;
}

