import assert from "node:assert/strict";
import { getLLMConfigValidationError } from "../utils/storeHelpers";

const config = {
  LLM: "claude_code",
  CLAUDE_CODE_MODEL: "claude-sonnet-4-6",
  DISABLE_IMAGE_GENERATION: true,
  WEB_GROUNDING: false,
};
assert.equal(getLLMConfigValidationError(config), null);
assert.equal(getLLMConfigValidationError({ ...config, CLAUDE_CODE_MODEL: " " }), "Enter a Claude Code model ID.");
assert.equal(getLLMConfigValidationError({ ...config, LLM: "anthropic" }), "Anthropic API key is required.");
assert.equal(getLLMConfigValidationError({ ...config, DISABLE_IMAGE_GENERATION: false }), "Select an image provider, or turn off image generation.");
console.log("Claude Code validation checks passed");
