> Cập nhật: 2026-11-09

- Đã thêm đăng nhập Claude Code OAuth/PKCE theo pattern ChatGPT Codex hiện có.
- Đã đọc tài liệu deploy `docs/deploy-gcp-cloudflare.vi.md` và push code lên repo GitHub người dùng cung cấp.
- Repo đang có nhiều thay đổi/template do người dùng tạo trước; không được xoá hoặc reset.
- Commit đã push: `f1c7a47` trên branch `master`.
- Đã nối provider `claude_code` riêng vào factory chung cho outline, slide, Smart generation, template và chat; dùng CLI chính thức `2.1.319`, không giả token thành API key.
- Credential chọn theo actor ID (không dùng owner ID bị ẩn trong shared workspace), tự refresh; CLI chạy cwd/HOME tạm, không thừa kế key/endpoint server, không cấp shell/filesystem/MCP, timeout/hủy/giới hạn hai process.
- Onboarding Next kiểm tra CLI + credential, chỉ yêu cầu model; Settings user thường cho tự link/disconnect. Provider/model vẫn theo cấu hình workspace admin.
- Chưa kiểm tra generation bằng tài khoản Claude thật hoặc build Docker Linux trên VM; đã test CLI flags chính thức không dùng credential. Subscription bên thứ ba cần xem quyền chấp thuận Anthropic.
- Sửa lỗi migration Claude tạo hai head khiến backend có thể không khởi động: nối sau `026c0ba8b35c`, cập nhật `REVISION_HEAD`, thêm test graph migration.
