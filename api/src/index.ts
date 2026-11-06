import { handleMcp } from "./mcp";
import { handleRest, json, optionsResponse } from "./rest";
import type { Env } from "./types";

/**
 * GitHired public REST API + remote MCP server.
 * Website stays on GitHub Pages (githired.ca). This Worker serves api.githired.ca.
 */
export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);

    if (request.method === "OPTIONS") {
      return optionsResponse();
    }

    try {
      if (url.pathname === "/mcp" || url.pathname.startsWith("/mcp/")) {
        return await handleMcp(request, env);
      }
      return await handleRest(request, env, url);
    } catch (err) {
      return json(
        {
          error: "internal_error",
          message: err instanceof Error ? err.message : String(err),
        },
        500,
      );
    }
  },
} satisfies ExportedHandler<Env>;
