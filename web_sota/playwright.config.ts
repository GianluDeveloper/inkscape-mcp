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
  webServer: {
    command: "uv run python -m inkscape_mcp.main --mode http --port 11028 --host 127.0.0.1",
    port: 11028,
    timeout: 45000,
    reuseExistingServer: true,
    env: {
      INKSCAPE_PATH: "C:\\Program Files\\Inkscape\\bin\\inkscape.exe",
      MCP_PORT: "11028",
      MCP_TRANSPORT: "http",
    },
  },
});
