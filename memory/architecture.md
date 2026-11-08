> Cập nhật: 2026-11-08

- Backend: FastAPI tại `servers/fastapi`, router API dưới `/api/v1/ppt`.
- Frontend: Next.js/TypeScript tại `servers/nextjs`; cấu hình nhà cung cấp nằm trong `LLMSelection` và `userConfig`.
- OAuth ChatGPT hiện có PKCE, endpoint dưới `api/v1/ppt/codex/auth`, token lưu env/userConfig.
- Deploy: Docker Compose trên Ubuntu Google Cloud, Cloudflare Tunnel, dữ liệu bền vững trong `app_data`.
