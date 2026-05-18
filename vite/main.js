// Lazy loaders — Vite code-splits these into separate chunks.
// Each chunk only downloads when the page actually needs it.
window.loadEntityGraph  = () => import('./src/sample-graph.js').then(m => m.initEntityGraph);
window.loadGraphRender  = () => import('./src/graph-render.js').then(m => m.mountGraph);
window.loadMDNoteEditor = () => import('./src/mdnote-editor.js').then(m => m.initMDNoteEditor);
