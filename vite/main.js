import "./src/styles.css";
import { initSampleGraph } from "./src/sample-graph.js";

// Make the function globally available for Flask templates
window.initSampleGraph = initSampleGraph;
