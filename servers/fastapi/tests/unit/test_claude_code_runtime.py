import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from llmai.shared import GenerationDefaults, JSONSchemaResponse, SystemMessage, Tool, UserMessage
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from api.v1.auth.context import get_current_actor_id, get_current_owner_id, reset_current_owner_id, set_current_owner_id
from models.sql.claude_code_credential import ClaudeCodeCredential
from models.sql.user import User
from services import claude_code_credentials as credentials
from utils import claude_code_client as runtime
from utils.oauth import anthropic_claude as oauth


def test_actor_identity_survives_shared_workspace(monkeypatch):
    monkeypatch.setenv("PRESENTON_SHARED_WORKSPACE", "true")
    user = uuid.uuid4()
    token = set_current_owner_id(user)
    try:
        assert get_current_owner_id() is None
        assert get_current_actor_id() == user
    finally:
        reset_current_owner_id(token)


def test_credentials_are_encrypted_selected_by_user_and_refreshed(monkeypatch, tmp_path):
    url = f"sqlite:///{tmp_path / 'credentials.db'}"
    monkeypatch.setattr(credentials, "get_database_url_and_connect_args", lambda: (url, {}))
    monkeypatch.setattr(credentials, "get_or_create_auth_secret", lambda: "stable-test-key")
    engine = create_engine(url)
    User.__table__.create(engine)
    ClaudeCodeCredential.__table__.create(engine)
    alice, bob = uuid.uuid4(), uuid.uuid4()
    with Session(engine) as session:
        for user_id, name in ((alice, "alice"), (bob, "bob")):
            session.add(User(id=user_id, username=name, hashed_password="unused"))
            session.add(ClaudeCodeCredential(
                user_id=user_id, access_token_encrypted=credentials._encrypt(name + "-token"),
                refresh_token_encrypted=credentials._encrypt(name + "-refresh"),
                token_expires_at=datetime.now(UTC) + timedelta(hours=1 if name == "bob" else -1),
            ))
        session.commit()
    refreshed = []

    def refresh(value):
        refreshed.append(value)
        return oauth.ClaudeTokens("alice-new-token", "alice-new-refresh", 3600)

    monkeypatch.setattr(credentials, "refresh_token", refresh)
    assert credentials.get_access_token(alice) == "alice-new-token"
    assert credentials.get_access_token(bob) == "bob-token"
    assert credentials.get_access_token(alice) == "alice-new-token"
    assert refreshed == ["alice-refresh"]
    with Session(engine) as session:
        row = session.scalar(select(ClaudeCodeCredential).where(ClaudeCodeCredential.user_id == alice))
        assert "alice-new-token" not in row.access_token_encrypted
    with pytest.raises(HTTPException) as failure:
        credentials.get_access_token(uuid.uuid4())
    assert failure.value.status_code == 401
    engine.dispose()


def test_oauth_parses_callback_and_rejects_wrong_state(monkeypatch):
    requests = []

    def post(url, **kwargs):
        import httpx
        requests.append(kwargs["json"])
        return httpx.Response(200, json={"access_token": "test-token", "expires_in": 3600}, request=httpx.Request("POST", url))

    monkeypatch.setattr(oauth.httpx, "post", post)
    oauth.exchange_code("code123#verifier", "verifier")
    oauth.exchange_code("https://console.anthropic.com/oauth/code/callback?code=code456&state=verifier", "verifier")
    assert [request["code"] for request in requests] == ["code123", "code456"]
    with pytest.raises(ValueError):
        oauth.exchange_code("code#someone-else", "verifier")
    assert len(requests) == 2


@pytest.fixture
def fake_cli(monkeypatch, tmp_path):
    script = tmp_path / "fake_cli.py"
    script.write_text(
        "import json,sys\n"
        "payload=json.loads(sys.stdin.readline())\n"
        "assert payload['type']=='user'\n"
        "print(json.dumps({'type':'result','result':'hello','usage':{'input_tokens':12,'output_tokens':4}}))\n",
        encoding="utf8",
    )
    real_popen = subprocess.Popen
    captured = []

    def popen(command, **kwargs):
        captured.append((command, kwargs))
        return real_popen([sys.executable, str(script)], **kwargs)

    monkeypatch.setattr(runtime, "cli_executable", lambda: "claude")
    monkeypatch.setattr(runtime, "get_access_token", lambda user_id: f"private-{user_id}")
    monkeypatch.setattr(runtime.subprocess, "Popen", popen)
    return script, captured


def test_cli_execution_isolated_from_server_secrets(fake_cli, monkeypatch):
    script, captured = fake_cli
    monkeypatch.setenv("ANTHROPIC_API_KEY", "server-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://untrusted.test")
    client = runtime.ClaudeCodeClient(user_id=uuid.uuid4(), generation_defaults=GenerationDefaults())
    events = list(client.generate(model="claude-sonnet-4-6", messages=[UserMessage(content="hello")], stream=True))
    assert events[-1].content == "hello"
    assert events[-1].usage.input_tokens == 12
    command, kwargs = captured[0]
    assert command[command.index("--tools") + 1] == ""
    assert "--safe-mode" in command and "--restricted" in command
    assert "--no-session-persistence" in command
    assert "ANTHROPIC_API_KEY" not in kwargs["env"]
    assert "ANTHROPIC_BASE_URL" not in kwargs["env"]
    assert kwargs["env"]["CLAUDE_CODE_OAUTH_TOKEN"].startswith("private-")
    assert kwargs["env"]["HOME"] == kwargs["cwd"]
    assert not os.path.exists(kwargs["cwd"])


def test_structured_output_and_presenton_tools(fake_cli):
    script, _ = fake_cli
    client = runtime.ClaudeCodeClient(user_id=uuid.uuid4(), generation_defaults=GenerationDefaults())
    schema = {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}
    script.write_text("import json,sys\njson.loads(sys.stdin.readline())\nprint(json.dumps({'type':'result','structured_output':{'title':'Slide'}}))", encoding="utf8")
    result = client.generate(model="claude-sonnet-4-6", messages=[UserMessage(content="outline")], response_format=JSONSchemaResponse(json_schema=schema))
    assert result.content == {"title": "Slide"}
    script.write_text("import json,sys\njson.loads(sys.stdin.readline())\nprint(json.dumps({'type':'result','structured_output':{'text':'','tool_calls':[{'name':'edit_slide','arguments':'{\"index\":1}'}]}}))", encoding="utf8")
    tool = Tool(name="edit_slide", description="Edit a slide", schema={"type": "object", "properties": {"index": {"type": "integer"}}, "required": ["index"]})
    result = client.generate(model="claude-sonnet-4-6", messages=[SystemMessage(content="edit"), UserMessage(content="slide 1")], tools=[tool])
    assert result.tool_calls[0].name == "edit_slide"
    assert json.loads(result.tool_calls[0].arguments) == {"index": 1}
    script.write_text("import json,sys\njson.loads(sys.stdin.readline())\nprint(json.dumps({'type':'result','structured_output':{'text':'','tool_calls':[],'answer':{'title':'Final slide'}}}))", encoding="utf8")
    result = client.generate(model="claude-sonnet-4-6", messages=[UserMessage(content="layout")], tools=[tool], response_format=JSONSchemaResponse(json_schema=schema))
    assert result.content == {"title": "Final slide"}


def test_cli_timeout_and_error_do_not_leak_secrets(fake_cli, monkeypatch):
    script, _ = fake_cli
    client = runtime.ClaudeCodeClient(user_id=uuid.uuid4(), generation_defaults=GenerationDefaults())
    script.write_text("import time\ntime.sleep(10)", encoding="utf8")
    monkeypatch.setattr(runtime, "CLI_TIMEOUT_SECONDS", 0.1)
    with pytest.raises(HTTPException) as failure:
        client.generate(model="claude-sonnet-4-6", messages=[UserMessage(content="hello")])
    assert failure.value.status_code == 504
    assert client._process is None
    script.write_text("import sys\nprint('secret-token',file=sys.stderr)\nsys.exit(1)", encoding="utf8")
    with pytest.raises(HTTPException) as failure:
        client.generate(model="claude-sonnet-4-6", messages=[UserMessage(content="hello")])
    assert "secret-token" not in failure.value.detail


def test_shared_factory_routes_cli_and_keeps_other_providers(monkeypatch):
    from utils import llm_client, llm_config, llm_provider
    user = uuid.uuid4()
    monkeypatch.setenv("LLM", "claude_code")
    monkeypatch.setenv("CLAUDE_CODE_MODEL", "claude-sonnet-4-6")
    token = set_current_owner_id(user)
    try:
        client = llm_client.get_client(config=llm_config.get_llm_config())
        assert isinstance(client, runtime.ClaudeCodeClient)
        assert client.user_id == user
        assert llm_provider.get_model() == "claude-sonnet-4-6"
    finally:
        reset_current_owner_id(token)
    monkeypatch.setenv("LLM", "openai")
    monkeypatch.setattr(llm_client, "get_provider_client", lambda **kwargs: "existing-client")
    assert llm_client.get_client(config=object()) == "existing-client"


def test_cli_missing_fails_before_a_generation_request(monkeypatch):
    monkeypatch.setattr(runtime.shutil, "which", lambda _: None)
    with pytest.raises(HTTPException) as failure:
        runtime.cli_executable()
    assert failure.value.status_code == 503
    assert "Rebuild" in failure.value.detail


def test_cancel_stops_cli_process(fake_cli):
    script, _ = fake_cli
    script.write_text("import time\ntime.sleep(30)", encoding="utf8")
    client = runtime.ClaudeCodeClient(user_id=uuid.uuid4(), generation_defaults=GenerationDefaults())
    errors = []
    def run():
        try:
            client.generate(model="claude-sonnet-4-6", messages=[UserMessage(content="hello")])
        except HTTPException as error:
            errors.append(error)
    worker = threading.Thread(target=run)
    worker.start()
    deadline = time.monotonic() + 5
    while client._process is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert client._process is not None
    client.cancel()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert errors
    assert client._process is None
