import cytoscape from 'cytoscape';
import elk from 'cytoscape-elk';

cytoscape.use(elk);

function elkLayout(rankDir, animate) {
  return {
    name: 'elk',
    nodeDimensionsIncludeLabels: false,
    fit: false,
    padding: 40,
    animate: !!animate,
    animationDuration: animate || 400,
    elk: {
      algorithm: 'layered',
      'elk.direction': rankDir === 'LR' ? 'RIGHT' : 'DOWN',
      'elk.spacing.nodeNode': 44,
      'elk.layered.spacing.nodeNodeBetweenLayers': 88,
      'elk.edgeRouting': 'POLYLINE',
      'elk.layered.crossingMinimization.strategy': 'LAYER_SWEEP',
    }
  };
}

function getCSSVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

// Matches base.html's hashColor — same function, inlined for use inside the module.
function hashColor(str) {
  let h = 0;
  for (let i = 0; i < str.length; i++) h = (Math.imul(31, h) + str.charCodeAt(i)) | 0;
  const u = h >>> 0;
  const hue = u % 360;
  const sat = 45 + ((u >>> 9)  % 30);
  const lit = 28 + ((u >>> 18) % 15);
  const s = sat / 100, l = lit / 100;
  const c = (1 - Math.abs(2*l - 1)) * s;
  const x = c * (1 - Math.abs((hue / 60) % 2 - 1));
  const m = l - c / 2;
  const [ri, gi, bi] =
    hue < 60  ? [c,x,0] : hue < 120 ? [x,c,0] : hue < 180 ? [0,c,x] :
    hue < 240 ? [0,x,c] : hue < 300 ? [x,0,c] : [c,0,x];
  return '#' + [ri+m, gi+m, bi+m].map(v => Math.round(v*255).toString(16).padStart(2,'0')).join('');
}

function createNodePopup() {
  const el = document.createElement('div');
  el.style.cssText = 'position:fixed;display:none;z-index:1050;max-width:272px;pointer-events:auto;font-family:inherit;';
  el.innerHTML = `
    <div class="cg-graph-popup">
      <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:0.5rem;margin-bottom:0.4rem;">
        <span class="popup-badge" style="display:inline-block;padding:2px 8px;border-radius:10px;font-size:var(--fs-xs);font-weight:600;border:1px solid;white-space:nowrap;"></span>
        <button class="popup-close" style="background:none;border:none;cursor:pointer;padding:0;line-height:1;color:var(--bs-secondary-color);font-size:1.25rem;flex-shrink:0;margin-top:-2px;">&times;</button>
      </div>
      <div class="popup-title" style="font-weight:600;word-break:break-word;margin-bottom:0.3rem;line-height:1.35;font-size:var(--fs-md);"></div>
      <div class="popup-img" style="display:none;margin-bottom:0.4rem;">
        <img style="max-width:100%;max-height:96px;object-fit:contain;border-radius:4px;border:1px solid var(--bs-border-color);">
      </div>
      <a class="popup-link" href="#" style="display:inline-flex;align-items:center;gap:0.3rem;font-size:var(--fs-sm);color:var(--cg-link);text-decoration:none;">
        View details <i class="bi bi-arrow-right" style="font-size:var(--fs-xs);"></i>
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
    const colorKey   = isDataset ? (measure || 'dataset') : (node.data('sampleType') || 'sample');
    const badgeColor = hashColor(colorKey);
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

export function initEntityGraph(containerId, graphData, { onReady } = {}) {
  const { nodes, edges, centerNodeId } = graphData;
  let currentRankDir = 'LR';

  const accentMid  = getCSSVar('--cg-accent-mid') || '#3a7a87';
  // --bs-body-color is light in dark mode, dark in light mode — use directly
  const bodyColor  = getCSSVar('--bs-body-color') || '#333';

  const cyNodes = nodes.map(node => {
    const colorKey = node.type === 'dataset'
      ? (node.measurement || 'dataset')
      : (node.sampleType  || 'sample');
    return {
      data: {
        id: node.id,
        label: node.label,
        type: node.type,
        url: node.url,
        description: node.description || '',
        measurement: node.measurement || '',
        sampleType: node.sampleType || '',
        color: hashColor(colorKey),
        ...(node.thumbnail ? { thumbnail: node.thumbnail } : {}),
        isCenterNode: node.id === centerNodeId
      }
    };
  });

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
      // ── sample nodes ────────────────────────────────────────────────
      {
        selector: 'node[type="sample"]',
        style: {
          'background-color': 'data(color)',
          'label': 'data(label)',
          'color': '#fff',
          'text-valign': 'center',
          'text-halign': 'center',
          'font-size': '11px',
          'font-family': "'IBM Plex Sans', sans-serif",
          'font-weight': '500',
          'width': node => Math.max(node.data('label').length * 7, 70),
          'height': 38,
          'shape': 'roundrectangle',
          'corner-radius': 6,
          'text-wrap': 'wrap',
          'text-max-width': '130px',
          'shadow-blur': 10,
          'shadow-color': 'rgba(0,0,0,0.28)',
          'shadow-offset-x': 0,
          'shadow-offset-y': 3,
          'shadow-opacity': 1,
        }
      },
      // ── dataset nodes ────────────────────────────────────────────────
      {
        selector: 'node[type="dataset"]',
        style: {
          'background-color': 'data(color)',
          'label': 'data(label)',
          'color': '#fff',
          'text-valign': 'center',
          'text-halign': 'center',
          'font-size': '10px',
          'font-family': "'IBM Plex Sans', sans-serif",
          'font-weight': '500',
          'width': node => Math.max(node.data('label').length * 6.5, 65),
          'height': 30,
          'shape': 'roundrectangle',
          'corner-radius': 5,
          'text-wrap': 'wrap',
          'text-max-width': '120px',
          'shadow-blur': 8,
          'shadow-color': 'rgba(0,0,0,0.22)',
          'shadow-offset-x': 0,
          'shadow-offset-y': 2,
          'shadow-opacity': 1,
        }
      },
      // ── thumbnail dataset nodes ───────────────────────────────────────
      {
        selector: 'node[type="dataset"][thumbnail]',
        style: {
          'background-image': 'data(thumbnail)',
          'background-fit': 'contain',
          'background-color': '#f8f9fa',
          'border-width': 2,
          'border-color': 'data(color)',
          'color': '#333',
          'width': 100,
          'height': 78,
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 6,
          'font-size': '10px'
        }
      },
      // ── center node (current resource) ───────────────────────────────
      {
        selector: 'node[?isCenterNode]',
        style: {
          'font-weight': 'bold',
          'font-size': '13px',
          'width': node => Math.max(node.data('label').length * 8.5, 95),
          'height': 48,
          'border-width': 4,
          'border-color': bodyColor,
          'border-opacity': 0.85,
          // Strong glow in the node's own color
          'shadow-blur': 28,
          'shadow-color': 'data(color)',
          'shadow-offset-x': 0,
          'shadow-offset-y': 0,
          'shadow-opacity': 0.8,
        }
      },
      // ── edges ────────────────────────────────────────────────────────
      {
        selector: 'edge',
        style: {
          'width': 1.5,
          'line-color': bodyColor,
          'target-arrow-color': bodyColor,
          'target-arrow-shape': 'triangle',
          'curve-style': 'straight',
          'arrow-scale': 1.0,
        }
      },
      // ── hover state ──────────────────────────────────────────────────
      {
        selector: 'node.hovered:not([?isCenterNode])',
        style: {
          'border-width': 2,
          'border-color': accentMid,
          'shadow-blur': 16,
          'shadow-color': accentMid,
          'shadow-offset-x': 0,
          'shadow-offset-y': 0,
          'shadow-opacity': 0.4,
        }
      },
      // ── selected state ───────────────────────────────────────────────
      {
        selector: 'node:selected',
        style: {
          'border-width': 3,
          'border-color': accentMid,
          'background-blacken': -0.12
        }
      }
    ],
    layout: elkLayout('LR'),
    minZoom: 0.15,
    maxZoom: 3,
    userZoomingEnabled: false,
    userPanningEnabled: true,
    boxSelectionEnabled: false,
  });

  // ── re-apply theme-sensitive styles on theme change ─────────────────
  function applyThemeStyles() {
    const color = getCSSVar('--bs-body-color');
    cy.style()
      .selector('edge')
        .style({ 'line-color': color, 'target-arrow-color': color })
      .selector('node[?isCenterNode]')
        .style({ 'border-color': color })
      .update();
  }
  const themeObserver = new MutationObserver(applyThemeStyles);
  themeObserver.observe(document.documentElement, {
    attributes: true, attributeFilter: ['data-bs-theme']
  });
  cy.on('destroy', () => themeObserver.disconnect());

  // ── fit viewport after layout, centered on current resource ─────────
  cy.one('layoutstop', () => {
    const centerNode = cy.$('[?isCenterNode]');
    cy.fit(cy.nodes(':visible'), 40);
    // If there's a clear center node and graph is small enough, zoom in slightly
    if (centerNode.length && cy.nodes().length <= 30) {
      cy.animate({ fit: { eles: cy.nodes(':visible'), padding: 40 } }, { duration: 200 });
    }
    if (onReady) onReady(cy);
  });

  // ── ctrl+wheel zoom ──────────────────────────────────────────────────
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

  cy.relayout = function(animate, eles) {
    const opts = elkLayout(currentRankDir, animate !== false ? 400 : 0);
    if (eles) opts.eles = eles;
    cy.layout(opts).run();
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
        'background-color': node => node.data('color'),
        'color': '#fff',
        'width': node => Math.max(node.data('label').length * 6.5, 65),
        'height': 30,
        'text-valign': 'center',
        'text-margin-y': 0
      });
    }
    return thumbnailsVisible;
  };

  return cy;
}
