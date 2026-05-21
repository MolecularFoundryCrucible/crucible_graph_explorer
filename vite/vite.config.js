export default {
  server: {
    port: 3000,
    strictPort: true,
  },

  build: {
    manifest: true,
    outDir: 'dist',
    rollupOptions: {
      input: './main.js',
      output: {
        chunkFileNames: 'assets/chunks/[name]-[hash].js',
      }
    }
  },

  resolve: {
    alias: {
      '@': '/src',
    }
  }
};
