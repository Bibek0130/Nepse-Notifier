import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, /api is proxied to Django so no CORS setup is needed.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": process.env.API_URL || "http://localhost:8000",
    },
  },
});
