> Cập nhật: 2026-11-09

- Backend: FastAPI tại `servers/fastapi`, router API dưới `/api/v1/ppt`.
- Frontend: Next.js/TypeScript tại `servers/nextjs`; cấu hình nhà cung cấp nằm trong `LLMSelection` và `userConfig`.
- OAuth ChatGPT hiện có PKCE, endpoint dưới `api/v1/ppt/codex/auth`, token lưu env/userConfig.
- Deploy: Docker Compose trên Ubuntu Google Cloud, Cloudflare Tunnel, dữ liệu bền vững trong `app_data`.
- Provider Claude Code: factory `utils/llm_client.py` chọn adapter `utils/claude_code_client.py`; CLI chính thức cài trong Docker, credential mã hóa bảng `claude_code_credentials` theo user web. Không mount ~/.claude chung và không lưu OAuth trong biến API key toàn cục.
- Shared workspace chỉ bỏ scoping nội dung; actor identity vẫn riêng để chọn credential. Provider/model workspace do admin chọn, user thường link ở Account Settings.
