import "./src/styles.css";
import { initEntityGraph } from "./src/sample-graph.js";
import { initMDNoteEditor } from "./src/mdnote-editor.js";

// Make functions globally available for Flask templates
window.initEntityGraph = initEntityGraph;
window.initMDNoteEditor = initMDNoteEditor;
