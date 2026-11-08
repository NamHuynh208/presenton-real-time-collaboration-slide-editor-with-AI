import { getApiErrorMessage, getApiUrl } from "@/utils/api";

export const DEFAULT_CLAUDE_CODE_MODEL = "claude-sonnet-4-6";

export async function checkClaudeCodeReady(): Promise<void> {
  const response = await fetch(getApiUrl("/api/v1/ppt/anthropic/auth/check"), { method: "POST" });
  if (!response.ok) {
    throw new Error(await getApiErrorMessage(response, "Connect your Claude Code account and rebuild the server image if the CLI is missing."));
  }
}
