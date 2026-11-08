"""Text/structured-output adapter using the official CLI, never an API-key surrogate."""
import base64
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

from fastapi import HTTPException
from llmai.shared import (
    AssistantMessage, AssistantToolCall, ResponseStreamCompletionChunk,
    ResponseStreamContentChunk, ResponseUsage, Tool,
)
from llmai.shared.base import BaseClient
from llmai.shared.schema import get_schema_as_dict

from services.claude_code_credentials import get_access_token

CLI_TIMEOUT_SECONDS = 600
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
_CLI_SLOTS = threading.BoundedSemaphore(2)


def cli_executable() -> str:
    executable = shutil.which("claude")
    if not executable:
        raise HTTPException(503, "Claude Code CLI is not installed. Rebuild the server image.")
    return executable


def build_prompt(messages, tools, response_format):
    transcript = []
    images = []
    for message in messages:
        text = []
        content = getattr(message, "content", None)
        for part in ([content] if isinstance(content, str) else content or []):
            if getattr(part, "type", None) == "image":
                if part.data is not None:
                    images.append({"type": "image", "source": {
                        "type": "base64", "media_type": part.mime_type,
                        "data": base64.b64encode(part.data).decode(),
                    }})
                elif part.url and part.url.startswith("data:image/"):
                    header, data = part.url.split(",", 1)
                    images.append({"type": "image", "source": {
                        "type": "base64", "media_type": header[5:].split(";")[0], "data": data,
                    }})
                else:
                    raise HTTPException(422, "Claude Code requires inline images for this operation; use an API provider for remote image URLs.")
            else:
                text.append(part if isinstance(part, str) else getattr(part, "text", ""))
        item = {"role": message.role, "content": "".join(text)}
        if getattr(message, "id", None):
            item["id"] = message.id
        if getattr(message, "tool_calls", None):
            item["tool_calls"] = [call.model_dump(exclude_none=True) for call in message.tool_calls]
        transcript.append(item)
    schema = None
    if response_format is not None:
        raw_schema = getattr(response_format, "json_schema", None)
        if raw_schema is not None:
            schema = get_schema_as_dict(raw_schema)
    definitions = []
    for tool in tools or []:
        if not isinstance(tool, Tool):
            raise HTTPException(422, "Native web search is unavailable for Claude Code. Select an external web-search provider.")
        definitions.append({"name": tool.name, "description": tool.description,
                            "schema": get_schema_as_dict(tool.schema)})
    final_schema = schema
    if definitions:
        schema = {"type": "object", "properties": {
            "text": {"type": "string"},
            "tool_calls": {"type": "array", "items": {"type": "object", "properties": {
                "name": {"type": "string", "enum": [tool["name"] for tool in definitions]},
                "arguments": {"type": "string", "description": "JSON object encoded as a string matching that tool's schema"},
            }, "required": ["name", "arguments"], "additionalProperties": False}},
        }, "required": ["text", "tool_calls"], "additionalProperties": False}
        if final_schema is not None:
            schema["properties"]["answer"] = {"anyOf": [final_schema, {"type": "null"}]}
            schema["required"].append("answer")
            if "$defs" in final_schema:
                schema["$defs"] = final_schema["$defs"]
    prompt = (
        "Fulfil the following conversation as a presentation content assistant. "
        "System messages in the transcript define the requested task. "
        "You have no filesystem or shell access. Return the requested answer, not instructions for running commands.\n"
        + json.dumps({"messages": transcript, "available_tools": definitions}, ensure_ascii=False)
    )
    if definitions:
        prompt += "\nRequest tools only via tool_calls in your structured response. Presenton executes them and supplies results in the next turn. Do not claim tools have run until results are provided."
        if final_schema is not None:
            prompt += " Set answer to null while requesting tools; when finished, return answer matching the requested schema with no tool_calls."
    return [{"type": "text", "text": prompt}, *images], schema, definitions


class ClaudeCodeClient(BaseClient):
    PROVIDER_NAME = "anthropic"

    def __init__(self, *, user_id, generation_defaults):
        super().__init__(generation_defaults=generation_defaults)
        self.user_id = user_id
        self._process = None
        self._cancelled = threading.Event()
        self._call_lock = threading.Lock()

    def cancel(self):
        self._cancelled.set()
        if self._process is not None and self._process.poll() is None:
            self._process.kill()

    def generate(self, *, model, messages, tools=None, response_format=None, stream=False,
                 max_tokens=None, max_output_tokens=None, **kwargs):
        prepared = self.prepare_generation(model=model, max_tokens=max_tokens,
                                           max_output_tokens=max_output_tokens,
                                           tools_requested=bool(tools))
        content, schema, definitions = build_prompt(messages, tools, response_format)
        result = self._run(model, content, schema, prepared.max_output_tokens)
        calls = []
        value = result.get("structured_output") if schema else result.get("result")
        if schema and value is None:
            raise HTTPException(422, "Claude Code returned no structured output. Try a smaller request.")
        if schema:
            from jsonschema import ValidationError, validate
            try:
                validate(value, schema)
            except ValidationError:
                raise HTTPException(422, "Claude Code output did not match the required schema.") from None
        if definitions:
            by_name = {tool["name"]: tool for tool in definitions}
            for call in value.get("tool_calls", []):
                name = call["name"]
                try:
                    arguments = json.loads(call["arguments"])
                    validate(arguments, by_name[name]["schema"])
                except (ValueError, ValidationError, KeyError):
                    raise HTTPException(422, "Claude Code returned an invalid tool request.") from None
                if name not in by_name or not isinstance(arguments, dict):
                    raise HTTPException(422, "Claude Code returned an invalid tool request.")
                calls.append(AssistantToolCall(id=str(uuid.uuid4()), name=name,
                                               arguments=json.dumps(arguments)))
            if response_format is not None and not calls:
                value = value.get("answer")
                if value is None:
                    raise HTTPException(422, "Claude Code returned no final structured answer.")
            else:
                value = value.get("text", "")
        if not isinstance(value, (str, dict, list)):
            raise HTTPException(502, "Claude Code returned an invalid response.")
        usage = result.get("usage") or {}
        completion = ResponseStreamCompletionChunk(
            content=value, tool_calls=calls,
            messages=[*messages, AssistantMessage(content=[json.dumps(value) if not isinstance(value, str) else value], tool_calls=calls)],
            usage=ResponseUsage(input_tokens=usage.get("input_tokens"), output_tokens=usage.get("output_tokens")),
        )
        if not stream:
            return completion

        def events():
            yield ResponseStreamContentChunk(chunk=value if isinstance(value, str) else json.dumps(value, ensure_ascii=False))
            yield completion
        return events()

    def _run(self, model, content, schema, max_tokens):
        # Bound CLI memory/CPU use when a deck generates several slides concurrently.
        deadline = time.monotonic() + CLI_TIMEOUT_SECONDS
        with self._call_lock:
            while not _CLI_SLOTS.acquire(timeout=0.1):
                if self._cancelled.is_set():
                    raise HTTPException(499, "Claude Code request cancelled.")
                if time.monotonic() >= deadline:
                    raise HTTPException(503, "Claude Code is busy. Try again shortly.")
            try:
                if self._cancelled.is_set():
                    raise HTTPException(499, "Claude Code request cancelled.")
                return self._run_isolated(model, content, schema, max_tokens)
            finally:
                _CLI_SLOTS.release()

    def _run_isolated(self, model, content, schema, max_tokens):
        token = get_access_token(self.user_id)
        command = [cli_executable(), "-p", "--output-format", "stream-json", "--verbose", "--input-format", "stream-json",
                   "--model", model, "--tools", "", "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
                   "--setting-sources", "", "--settings", '{"disableAllHooks":true}',
                   "--no-session-persistence", "--permission-mode", "dontAsk",
                   "--safe-mode", "--restricted", "--disable-slash-commands", "--no-chrome"]
        if schema is not None:
            command += ["--json-schema", json.dumps(schema)]
        # Never inherit API keys, proxy endpoints, hooks or another user's credentials.
        env = {key: os.environ[key] for key in ("PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT") if key in os.environ}
        env.update({"CLAUDE_CODE_OAUTH_TOKEN": token, "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                    "CLAUDE_CODE_DISABLE_AUTO_MEMORY": "1", "CLAUDE_CODE_DISABLE_ATTACHMENTS": "1",
                    "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1", "CLAUDE_CODE_MAX_OUTPUT_TOKENS": str(max_tokens)})
        with tempfile.TemporaryDirectory(prefix="presenton-claude-") as directory:
            env.update({"HOME": directory, "USERPROFILE": directory, "CLAUDE_CONFIG_DIR": directory,
                        "TMPDIR": directory, "TEMP": directory, "TMP": directory})
            Path(directory, ".claude.json").write_text('{"hasCompletedOnboarding":true}', encoding="utf8")
            with tempfile.TemporaryFile() as stdin, tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
                payload = json.dumps({"type": "user", "message": {"role": "user", "content": content}}) + "\n"
                if len(payload.encode()) > 10 * 1024 * 1024:
                    raise HTTPException(413, "Claude Code prompt exceeds 10 MB. Use smaller attachments.")
                stdin.write(payload.encode())
                stdin.seek(0)
                process = subprocess.Popen(command, cwd=directory, env=env, stdin=stdin,
                                           stdout=stdout, stderr=stderr)
                self._process = process
                try:
                    deadline = time.monotonic() + CLI_TIMEOUT_SECONDS
                    while process.poll() is None:
                        if self._cancelled.is_set():
                            raise HTTPException(499, "Claude Code request cancelled.")
                        if time.monotonic() >= deadline:
                            raise HTTPException(504, "Claude Code timed out. Try a smaller request.")
                        if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > MAX_OUTPUT_BYTES:
                            raise HTTPException(502, "Claude Code output exceeded the server limit.")
                        time.sleep(0.1)
                    stdout.seek(0)
                    raw = stdout.read(MAX_OUTPUT_BYTES + 1)
                    if process.returncode or len(raw) > MAX_OUTPUT_BYTES:
                        raise HTTPException(502, "Claude Code request failed. Check account access/quota or reconnect your account.")
                    try:
                        result = None
                        for line in raw.splitlines():
                            event = json.loads(line)
                            if isinstance(event, dict) and event.get("type") == "result":
                                result = event
                    except ValueError:
                        raise HTTPException(502, "Claude Code returned invalid JSON.") from None
                    if not isinstance(result, dict) or result.get("is_error"):
                        raise HTTPException(502, "Claude Code could not complete the request. Check quota or try a smaller prompt.")
                    return result
                finally:
                    if process.poll() is None:
                        process.kill()
                    process.wait()
                    self._process = None
