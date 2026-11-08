> Cập nhật: 2026-11-09

- Đã thêm đăng nhập Claude Code OAuth/PKCE theo pattern ChatGPT Codex hiện có.
- Đã đọc tài liệu deploy `docs/deploy-gcp-cloudflare.vi.md` và push code lên repo GitHub người dùng cung cấp.
- Repo đang có nhiều thay đổi/template do người dùng tạo trước; không được xoá hoặc reset.
- Commit đã push: `f1c7a47` trên branch `master`.
- Đang chuyển OAuth Claude sang credential mã hóa theo từng user web; không còn gọi endpoint tạo API key bị 403.
- UI onboarding có tab Claude Code ngang hàng ChatGPT; cần adapter runtime Claude Code riêng để dùng token trực tiếp cho generation.
