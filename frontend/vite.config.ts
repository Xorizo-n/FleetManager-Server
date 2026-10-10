import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(async ({ mode }) => ({
  // `npm run dev:mock` поднимает интерфейс на мок-API из mock/mockApi.ts (~1000 хостов)
  plugins: [react(), ...(mode === "mock" ? [(await import("./mock/mockApi")).mockApi()] : [])],
  server: {
    port: 5173,
  },
}));
