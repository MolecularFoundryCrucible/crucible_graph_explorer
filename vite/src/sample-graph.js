import cytoscape from 'cytoscape';
import dagre from 'cytoscape-dagre';

cytoscape.use(dagre);

function createNodePopup() {
  const el = document.createElement('div');
  el.style.cssText = 'position:fixed;display:none;z-index:1050;max-width:280px;pointer-events:auto;';
  el.innerHTML = `
    <div class="card shadow" style="font-size:0.85em;">
      <div class="card-body p-3">
        <button class="popup-close btn-close float-end" style="margin-top:-2px;margin-left:8px;"></button>
        <span class="popup-badge badge mb-1" style="font-size:0.75em;display:block;width:fit-content;"></span>
        <h6 class="popup-title mb-1" style="word-break:break-word;margin-top:4px;"></h6>
        <div class="popup-img mb-2" style="display:none;">
          <img style="max-width:100%;max-height:120px;object-fit:contain;border:2px solid #5a9e6f;border-radius:3px;">
        </div>
        <p class="popup-desc text-muted mb-2" style="display:none;font-size:0.8em;"></p>
        <a class="popup-link btn btn-sm btn-outline-primary" href="#">View Details →</a>
      </div>
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
    const label    = node.data('label') || node.data('name') || '';
    const type     = node.data('type') || 'sample';
    const desc     = node.data('description') || '';
    const measure  = node.data('measurement') || '';
    const thumb    = node.data('thumbnail');
    const url      = node.data('url') || '#';

    const badge = el.querySelector('.popup-badge');
    badge.textContent = measure || (type === 'dataset' ? 'Dataset' : 'Sample');
    badge.className = `popup-badge badge mb-1 ${type === 'dataset' ? 'bg-success' : 'bg-primary'}`;

    el.querySelector('.popup-title').textContent = label;

    const descEl = el.querySelector('.popup-desc');
    descEl.textContent = desc;
    descEl.style.display = desc ? '' : 'none';

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
    let x = clientX + 12;
    let y = clientY - rect.height / 2;
    if (x + rect.width > window.innerWidth - 8)  x = clientX - rect.width - 12;
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
          'background-color': '#4a7ba7',
          'label': 'data(label)',
          'color': '#fff',
          'text-valign': 'center',
          'text-halign': 'center',
          'font-size': '11px',
          'width': node => Math.max(node.data('label').length * 7, 60),
          'height': 40,
          'shape': 'roundrectangle',
          'text-wrap': 'wrap',
          'text-max-width': '120px'
        }
      },
      {
        selector: 'node[type="dataset"]',
        style: {
          'background-color': '#5a9e6f',
          'label': 'data(label)',
          'color': '#fff',
          'text-valign': 'center',
          'text-halign': 'center',
          'font-size': '10px',
          'width': node => Math.max(node.data('label').length * 6, 60),
          'height': 32,
          'shape': 'rectangle',
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
          'border-width': 3,
          'border-color': '#5a9e6f',
          'color': '#333',
          'width': 100,
          'height': 80,
          'text-valign': 'bottom',
          'text-halign': 'center',
          'text-margin-y': 6,
          'font-size': '10px',
        }
      },
      {
        selector: 'node[?isCenterNode]',
        style: {
          'border-width': 3,
          'border-color': '#001f3f',
          'font-weight': 'bold',
          'font-size': '13px',
          'shape': 'octagon'
        }
      },
      {
        selector: 'edge',
        style: {
          'width': 2,
          'line-color': '#aaa',
          'target-arrow-color': '#aaa',
          'target-arrow-shape': 'triangle',
          'curve-style': 'unbundled-bezier',
          'arrow-scale': 1.5
        }
      },
      {
        selector: 'node:selected',
        style: {
          'background-color': '#ff6b6b',
          'border-width': 3,
          'border-color': '#c92a2a'
        }
      }
    ],
    layout: {
      name: 'dagre',
      rankDir: 'LR',
      nodeSep: 40,
      rankSep: 80,
      padding: 30
    },
    minZoom: 0.2,
    maxZoom: 3
  });

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

  cy.on('mouseover', 'node', () => {
    document.getElementById(containerId).style.cursor = 'pointer';
  });
  cy.on('mouseout', 'node', () => {
    document.getElementById(containerId).style.cursor = 'default';
  });

  cy.toggleLayout = function() {
    currentRankDir = currentRankDir === 'LR' ? 'TB' : 'LR';
    cy.layout({
      name: 'dagre',
      rankDir: currentRankDir,
      nodeSep: 40,
      rankSep: 80,
      padding: 30,
      animate: true,
      animationDuration: 500
    }).run();
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
        'background-color': '#5a9e6f',
        'color': '#fff',
        'width': node => Math.max(node.data('label').length * 6, 60),
        'height': 32,
        'text-valign': 'center',
        'text-margin-y': 0
      });
    }
    return thumbnailsVisible;
  };

  return cy;
}

export function initSampleGraph(containerId, graphData) {
  console.log('Initializing sample graph:', { containerId, nodeCount: graphData.nodes?.length, edgeCount: graphData.edges?.length });
  const { nodes, edges, centerNodeId } = graphData;

  // Track current layout direction
  let currentRankDir = 'LR';

  const projectId = document.getElementById(containerId).dataset.projectId;

  // Transform nodes and edges to Cytoscape format
  const cyNodes = nodes.map(node => ({
    data: {
      id: node.id,
      label: node.label,
      name: node.name,
      description: node.description,
      type: 'sample',
      url: `/${projectId}/sample-graph/${node.id}`,
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

    elements: {
      nodes: cyNodes,
      edges: cyEdges
    },

    style: [
      {
        selector: 'node',
        style: {
          'background-color': '#666',
          'label': 'data(label)',
          'color': '#fff',
          'text-valign': 'center',
          'text-halign': 'center',
          'font-size': '12px',
          'width': (node) => node.data('name').length * 7,
          'height': 40,
          'padding': '10px',
          'shape': 'roundrectangle',
          'text-wrap': 'wrap',
          'text-max-width': '100px'
        }
      },
      {
        selector: 'node[?isCenterNode]',
        style: {
          'background-color': '#4a7ba7',
          'border-width': 3,
          'border-color': '#003366',
          'font-weight': 'bold',
          'font-size': '13px',
          'shape': 'octagon'
        }
      },
      {
        selector: 'edge',
        style: {
          'width': 2,
          'line-color': '#999',
          'target-arrow-color': '#999',
          'target-arrow-shape': 'triangle',
          'curve-style': 'unbundled-bezier',
          'arrow-scale': 1.5
        }
      },
      {
        selector: 'node:selected',
        style: {
          'background-color': '#ff6b6b',
          'border-width': 3,
          'border-color': '#c92a2a'
        }
      }
    ],

    layout: {
      name: 'dagre',
      rankDir: 'LR',
      nodeSep: 50,
      rankSep: 100,
      padding: 30
    },

    minZoom: 0.3,
    maxZoom: 3
    //wheelSensitivity: 0.2
  });

  console.log('Cytoscape instance created, nodes:', cy.nodes().length, 'edges:', cy.edges().length);

  const samplePopup = createNodePopup();

  cy.on('tap', evt => { if (evt.target === cy) samplePopup.hide(); });

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
    samplePopup.show(node, orig.clientX, orig.clientY);
  });

  // Add hover effects
  const container = document.getElementById(containerId);

  cy.on('mouseover', 'node', function() {
    container.style.cursor = 'pointer';
  });

  cy.on('mouseout', 'node', function() {
    container.style.cursor = 'default';
  });

  // Add layout toggle function
  cy.toggleLayout = function() {
    currentRankDir = currentRankDir === 'LR' ? 'TB' : 'LR';

    cy.layout({
      name: 'dagre',
      rankDir: currentRankDir,
      nodeSep: 50,
      rankSep: 100,
      padding: 30,
      animate: true,
      animationDuration: 500
    }).run();

    return currentRankDir;
  };

  return cy;
}
