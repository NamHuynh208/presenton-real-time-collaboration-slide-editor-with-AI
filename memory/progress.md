> Cập nhật: 2026-11-09

- [x] Thêm backend Claude Code OAuth.
- [x] Thêm credential Claude mã hóa theo từng user và link-session chống gắn nhầm tài khoản.
- [x] Thêm UI Claude Code ngang hàng ChatGPT trong onboarding.
- [x] Chạy Python syntax check, Next.js production build và diff check.
- [x] Thêm adapter CLI Claude Code và nối các caller generation/chat, credential theo user và refresh.
- [x] Sửa Next/Save onboarding: provider riêng, model ID, kiểm tra CLI/token thay cho API key.
- [x] Test unit/integration cho credential, CLI mock, timeout/cancel, OAuth session ownership, migration; build Next.js thành công.
- [x] 55 backend test qua; frontend validation self-check qua; lint UI mới không lỗi. Docker daemon local không chạy nên chưa build image Linux.
- [ ] Kiểm thử model thật bằng tài khoản user sau rebuild Docker trên VM (không có credential trong môi trường local).
- [x] Sửa chuỗi migration Claude; thêm self-check đảm bảo chỉ có một head.
- [x] Đọc tài liệu deploy; hướng dẫn deploy sẽ gửi trong câu trả lời.
