import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development, /api (and the admin, for the strategy pages it links to) is proxied to Django.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": process.env.API_URL || "http://localhost:8000",
      "/admin": process.env.API_URL || "http://localhost:8000",
      "/static": process.env.API_URL || "http://localhost:8000",
    },
  },
});
