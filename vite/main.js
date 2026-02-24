import "./src/styles.css";
import { initSampleGraph } from "./src/sample-graph.js";
import { initMDNoteEditor } from "./src/mdnote-editor.js";

// Make functions globally available for Flask templates
window.initSampleGraph = initSampleGraph;
window.initMDNoteEditor = initMDNoteEditor;
