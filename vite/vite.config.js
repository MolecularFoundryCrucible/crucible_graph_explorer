export default {
  server: {
    port: 3000,
    strictPort: true,
  },

  build: {
    manifest: true,
    outDir: 'dist',
    rollupOptions: {
      input: './main.js'
    }
  },

  resolve: {
    alias: {
      '@': '/src',
    }
  }
};
