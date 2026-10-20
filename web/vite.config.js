import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8787",
      "/grid.json": "http://127.0.0.1:8787",
      "/secretary.json": "http://127.0.0.1:8787",
    },
  },
});
