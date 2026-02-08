import cytoscape from 'cytoscape';
import dagre from 'cytoscape-dagre';

cytoscape.use(dagre);

export function initSampleGraph(containerId, graphData) {
  const { nodes, edges, centerNodeId } = graphData;

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
          'width': 'label',
          'height': 'label',
          'padding': '10px',
          'shape': 'roundrectangle',
          'text-wrap': 'wrap',
          'text-max-width': '100px'
        }
      },
      {
        selector: 'node[isCenterNode]',
        style: {
          'background-color': '#336699',
          'border-width': 3,
          'border-color': '#003366',
          'font-weight': 'bold'
        }
      },
      {
        selector: 'edge',
        style: {
          'width': 2,
          'line-color': '#999',
          'target-arrow-color': '#999',
          'target-arrow-shape': 'triangle',
          'curve-style': 'bezier',
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
      rankDir: 'TB',
      nodeSep: 50,
      rankSep: 100,
      padding: 30
    },

    minZoom: 0.3,
    maxZoom: 3,
    wheelSensitivity: 0.2
  });

  // Add click handler to nodes
  cy.on('tap', 'node', function(evt) {
    const node = evt.target;
    const nodeId = node.data('id');
    const nodeName = node.data('name');

    // Get project_id from the page (we'll add this as a data attribute)
    const projectId = document.getElementById(containerId).dataset.projectId;

    // Navigate to the sample graph page for this node
    window.location.href = `/${projectId}/sample-graph/${nodeId}`;
  });

  // Add hover tooltip
  cy.on('mouseover', 'node', function(evt) {
    const node = evt.target;
    const description = node.data('description');

    // You can implement a tooltip here if desired
    node.style('cursor', 'pointer');
  });

  return cy;
}
