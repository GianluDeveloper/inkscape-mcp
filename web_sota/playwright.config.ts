import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./e2e",
  timeout: 60000,
  retries: 1,
  use: {
    baseURL: "http://localhost:11029",
    headless: true,
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "uv --directory .. run inkscape-mcp --mode http --host 127.0.0.1 --port 11028",
      port: 11028,
      timeout: 45000,
      reuseExistingServer: true,
      env: {
        INKSCAPE_MCP_METRICS_ENABLED: "false",
      },
    },
    {
      command: "bun run dev",
      port: 11029,
      timeout: 45000,
      reuseExistingServer: true,
    },
  ],
});
