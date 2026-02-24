import cytoscape from 'cytoscape';
import dagre from 'cytoscape-dagre';

cytoscape.use(dagre);

export function initEntityGraph(containerId, graphData) {
  const { nodes, edges, centerNodeId } = graphData;
  let currentRankDir = 'LR';

  const cyNodes = nodes.map(node => ({
    data: {
      id: node.id,
      label: node.label,
      type: node.type,
      url: node.url,
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

  cy.on('tap', 'node', function(evt) {
    const node = evt.target;
    const url = node.data('url');
    if (url) {
      cy.nodes().style('opacity', 0.3);
      node.style('opacity', 1);
      node.style('background-color', '#ff6b6b');
      document.body.style.cursor = 'wait';
      window.location.href = url;
    }
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

  // Transform nodes and edges to Cytoscape format
  const cyNodes = nodes.map(node => ({
    data: {
      id: node.id,
      label: node.label,
      name: node.name,
      description: node.description,
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

  // Add click handler to nodes
  cy.on('tap', 'node', function(evt) {
    const node = evt.target;
    const nodeId = node.data('id');
    const nodeName = node.data('name');

    // Get project_id from the page (we'll add this as a data attribute)
    const projectId = document.getElementById(containerId).dataset.projectId;

    console.log('Node clicked:', { nodeId, nodeName, projectId });

    // Add visual feedback - highlight the clicked node
    cy.nodes().style('opacity', 0.3);
    node.style('opacity', 1);
    node.style('background-color', '#ff6b6b');

    // Show loading cursor
    document.body.style.cursor = 'wait';
    document.getElementById(containerId).style.cursor = 'wait';

    // Navigate to the sample graph page for this node
    window.location.href = `/${projectId}/sample-graph/${nodeId}`;
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
