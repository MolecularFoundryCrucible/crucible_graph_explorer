import cytoscape from 'cytoscape';
import dagre from 'cytoscape-dagre';

cytoscape.use(dagre);

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

  cy.on('mouseover', 'node', function(evt) {
    container.style.cursor = 'pointer';
  });

  cy.on('mouseout', 'node', function(evt) {
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
