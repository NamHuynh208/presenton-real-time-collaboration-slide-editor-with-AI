# Đưa Presenton (bản đã sửa) lên Google Cloud + Cloudflare

Mục tiêu: chạy **bản Presenton đã sửa trong thư mục này** (có cộng tác thời gian thực, xuất HTML) trên một máy ảo Google Cloud, mở tại **https://presenton.namprojects.site**. Tên miền `namprojects.site` đang quản lý DNS ở Cloudflare.

> Quy ước trong tài liệu:
> - Khối lệnh ghi **[Windows]** chạy trên máy bạn (PowerShell).
> - Khối lệnh ghi **[VM]** chạy trên máy ảo, sau khi đã SSH vào.
> - Chỗ `<...>` là giá trị bạn tự thay.

---

## 0. Tổng quan và chi phí

```
Trình duyệt ──HTTPS──► Cloudflare (DNS + Tunnel + Access tuỳ chọn)
                                │  (đường hầm do cloudflared mở từ VM ra ngoài)
                                ▼
                 VM Google Cloud (Ubuntu 24.04, Docker)
                 └─ container "presenton"  (nginx :80)
                       ├─ Next.js :3000          (giao diện)
                       ├─ FastAPI :8000          (API, lưu dữ liệu)
                       └─ Yjs collab :1234       (sửa song song, nginx proxy ở /collab/)
                 └─ thư mục ./app_data  (CSDL fastapi.db, ảnh, template, file xuất)
```

- VM **không mở cổng HTTP/HTTPS ra internet**. Cloudflare Tunnel do VM tự kết nối ra ngoài, nên không cần firewall rule, không cần IP tĩnh, không cần chứng chỉ SSL.
- Cổng container được gắn vào `127.0.0.1` của VM, người ngoài không chạm tới được.

**Chi phí ước tính mỗi tháng** (tham khảo, kiểm tra lại bằng [Pricing Calculator](https://cloud.google.com/products/calculator)):

| Hạng mục | Cấu hình | Ước tính |
|---|---|---|
| VM | e2-standard-2 (2 vCPU, 8 GB RAM), asia-southeast1 (Singapore), chạy 24/7 | ~55–65 USD |
| Ổ đĩa | 50 GB balanced persistent disk | ~6 USD |
| Snapshot sao lưu | vài GB, giữ 7 ngày | ~1–2 USD |
| Cloud Storage (bản sao app_data) | vài GB | < 1 USD |
| Cloudflare Tunnel + Access (≤ 50 người) | gói Free | 0 USD |
| **Tổng** | | **~65–75 USD/tháng** |

Tài khoản Google Cloud mới thường được **300 USD tín dụng dùng trong 90 ngày**. Muốn rẻ hơn có thể dùng `e2-medium` (4 GB RAM, khoảng một nửa giá). Nhưng bước build image và lúc xuất PDF/PPTX dễ thiếu RAM, nên bắt buộc phải có swap (mục 3.3).

Tiền gọi AI (Anthropic, OpenAI…) tính riêng theo API key của bạn.

---

## 1. Tài khoản Google Cloud, project, thanh toán

### 1.1. Tạo tài khoản và project (trên web)

1. Vào https://console.cloud.google.com, đăng nhập bằng tài khoản Google.
2. Nếu được mời dùng thử miễn phí, bấm **Start free / Dùng thử miễn phí** và nhập thẻ để xác minh. Thẻ không bị trừ tiền cho đến khi bạn chủ động nâng cấp.
3. Ở thanh trên cùng, bấm ô chọn project, chọn **New Project**:
   - **Project name:** `presenton`
   - **Project ID:** ghi nhớ giá trị hiện ra, ví dụ `presenton-123456`. Tài liệu gọi giá trị này là `<PROJECT_ID>`.
   - Bấm **Create**.
4. **Billing:** menu ☰, chọn **Billing**, rồi kiểm tra project `presenton` đã gắn với một billing account. Nếu chưa, bấm **Link a billing account**.

### 1.2. Đặt cảnh báo ngân sách (nên làm)

1. ☰, chọn **Billing**, rồi **Budgets & alerts**, bấm **Create budget**.
2. **Scope:** chọn project `presenton`.
3. **Amount:** ví dụ `80` USD/tháng.
4. **Thresholds:** 50 %, 90 %, 100 %, gửi email cho bạn.
5. Bấm **Finish**.

Ngân sách chỉ gửi **cảnh báo**, không tự tắt máy.

### 1.3. Bật Compute Engine API

☰, chọn **APIs & Services**, rồi **Library**, tìm **Compute Engine API** và bấm **Enable**. Lần đầu mất 1–2 phút.

### 1.4. Cài gcloud CLI trên Windows

**[Windows]** Mở PowerShell:

```powershell
winget install --id Google.CloudSDK -e
```

Hoặc tải bộ cài `GoogleCloudSDKInstaller.exe` từ https://cloud.google.com/sdk/docs/install rồi chạy.

Đóng PowerShell, mở lại rồi chạy:

```powershell
gcloud init
```

- Chọn **Log in with a new account**. Trình duyệt mở ra, bạn đăng nhập Google.
- Chọn project `<PROJECT_ID>`.
- Khi được hỏi Compute region/zone, chọn `asia-southeast1-b`.

Kiểm tra:

```powershell
gcloud config list
gcloud services enable compute.googleapis.com
```

---

## 2. Tạo máy ảo (VM)

### Cách A: bằng lệnh (nhanh, chính xác)

**[Windows]**

```powershell
gcloud compute instances create presenton-vm `
  --zone=asia-southeast1-b `
  --machine-type=e2-standard-2 `
  --image-family=ubuntu-2404-lts-amd64 `
  --image-project=ubuntu-os-cloud `
  --boot-disk-size=50GB `
  --boot-disk-type=pd-balanced `
  --scopes=default,storage-rw `
  --labels=app=presenton
```

- `--scopes=default,storage-rw` cho phép VM ghi bản sao lưu vào Cloud Storage (mục 11.3).
- **Không** thêm `--tags=http-server,https-server` và **không** tạo firewall rule mở cổng 80/443, vì Cloudflare Tunnel không cần.

### Cách B: bằng giao diện web

1. ☰, chọn **Compute Engine**, rồi **VM instances**, bấm **Create instance**.
2. **Name:** `presenton-vm`. **Region:** `asia-southeast1 (Singapore)`. **Zone:** `asia-southeast1-b`.
3. **Machine configuration:** series **E2**, machine type **e2-standard-2 (2 vCPU, 8 GB memory)**.
4. **Boot disk**, bấm **Change**:
   - Operating system **Ubuntu**, version **Ubuntu 24.04 LTS** (bản **x86/64**, không chọn Arm).
   - Boot disk type **Balanced persistent disk**, size **50 GB**. Bấm **Select**.
5. **Identity and API access**, mục Access scopes: chọn **Set access for each API**, đặt **Storage** là **Read Write**.
6. **Firewall:** **bỏ trống** cả hai ô *Allow HTTP traffic* và *Allow HTTPS traffic*.
7. Bấm **Create**.

### 2.1. SSH vào VM

**[Windows]**

```powershell
gcloud compute ssh presenton-vm --zone=asia-southeast1-b
```

Lần đầu gcloud tự tạo SSH key; cứ bấm Enter. Bạn cũng có thể bấm nút **SSH** cạnh VM trên trang web.

---

## 3. Cài Docker và swap trên VM

### 3.1. Cập nhật hệ thống

**[VM]**

```bash
sudo apt-get update && sudo apt-get -y upgrade
sudo apt-get install -y ca-certificates curl git python3 sqlite3
```

### 3.2. Cài Docker Engine + Compose plugin (kho apt chính thức của Docker)

**[VM]**

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo usermod -aG docker $USER
```

Thoát SSH (`exit`) rồi SSH vào lại để quyền nhóm `docker` có hiệu lực. Sau đó kiểm tra:

```bash
docker version
docker compose version
```

### 3.3. Thêm 4 GB swap

Bước build image (Next.js + Python + tải model) ngốn RAM. Swap giúp không bị "Killed".

**[VM]**

```bash
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h
```

---

## 4. Đưa mã nguồn đã sửa lên VM

Thư mục mã nguồn trên máy bạn: `D:\Project\Template slide USCC s2\presenton-main\presenton-main`. Chọn **một** trong hai cách.

### Cách A: qua GitHub private (nên dùng, dễ cập nhật về sau)

**1. Tạo repo trống trên GitHub:** https://github.com/new, đặt tên `presenton-uscc`, chọn **Private**, **không** tích README/.gitignore, bấm **Create repository**.

**2. Đẩy code từ Windows.** Thư mục hiện có một `.git` khởi tạo dở từ trước, nên xoá đi và tạo lại.

**[Windows]** (PowerShell, cần đã cài Git for Windows)

```powershell
cd "D:\Project\Template slide USCC s2\presenton-main\presenton-main"
Remove-Item -Recurse -Force .git
git init -b main
git add -A
git commit -m "Presenton USCC: collab + export HTML"
git remote add origin https://github.com/<github-user>/presenton-uscc.git
git push -u origin main
```

- `.gitignore` sẵn có đã bỏ qua `node_modules`, `.next`, `app_data`, `.env`, nên repo không quá nặng. Lần `git add` đầu vẫn có thể mất vài phút vì thư mục có file lớn (`NOTICE`, `layouts.json`, `templates/`).
- Khi push, Git for Windows sẽ mở cửa sổ đăng nhập GitHub.

**3. Clone trên VM.** Repo private nên cần token:
- Trên GitHub, vào **Settings**, **Developer settings**, **Personal access tokens**, **Fine-grained tokens**, bấm **Generate new token**.
- Chọn repo `presenton-uscc`, quyền **Contents: Read-only**, rồi copy token.

**[VM]**

```bash
cd ~
git clone https://github.com/<github-user>/presenton-uscc.git presenton
# Username: <github-user>   Password: <dán token>
cd ~/presenton
```

### Cách B: copy thẳng bằng gcloud (không cần GitHub)

**[Windows]** Nén trước để bỏ các thư mục nặng, rồi gửi lên:

```powershell
cd "D:\Project\Template slide USCC s2\presenton-main"
tar -czf presenton-src.tgz --exclude=node_modules --exclude=.next --exclude=.next-build --exclude=app_data --exclude=.git --exclude=.venv -C presenton-main .
gcloud compute scp presenton-src.tgz presenton-vm:~ --zone=asia-southeast1-b
```

**[VM]**

```bash
mkdir -p ~/presenton && tar -xzf ~/presenton-src.tgz -C ~/presenton && rm ~/presenton-src.tgz
cd ~/presenton && ls
```

(`gcloud compute scp --recurse <thư mục>` cũng dùng được, nhưng nó không có tuỳ chọn loại trừ thư mục nên sẽ gửi cả `node_modules`, rất chậm. Vì vậy nên nén bằng `tar` như trên.)

---

## 5. Build image và chạy bằng Docker Compose

Mọi lệnh ở mục này chạy **[VM]** trong thư mục `~/presenton`.

### 5.1. Tạo file `.env` (cấu hình và mật khẩu, không đưa lên git)

```bash
cd ~/presenton
cat > .env <<'EOF'
# --- Tài khoản quản trị đầu tiên (chỉ dùng ở lần khởi động đầu) ---
AUTH_USERNAME=admin
AUTH_PASSWORD=<mat-khau-manh-it-nhat-8-ky-tu>

# --- Địa chỉ công khai: dùng cho link tải/sửa/xem trước ---
PRESENTON_PUBLIC_URL=https://presenton.namprojects.site

# --- Chế độ nhóm: mọi người đăng nhập đều thấy & sửa chung mọi bài/template ---
PRESENTON_SHARED_WORKSPACE=true

# --- Mem0 mặc định gọi Ollama ở host.docker.internal:11434 (không có trên VM) -> tắt ---
MEM0_ENABLED=false

# --- (tuỳ chọn) đặt sẵn nhà cung cấp AI; cũng có thể đặt trong Settings ---
# LLM=anthropic
# ANTHROPIC_API_KEY=sk-ant-...
# ANTHROPIC_MODEL=
EOF
chmod 600 .env
```

- Username tối thiểu 3 ký tự, mật khẩu tối thiểu 8 ký tự (theo README).
- `PRESENTON_SHARED_WORKSPACE` là biến của bản đã sửa này. Muốn chắc nó tồn tại trong code đang build, chạy: `grep -rn PRESENTON_SHARED_WORKSPACE servers/ start.js`.
- Nếu không muốn Mem0 bị tắt, có thể bỏ dòng `MEM0_ENABLED=false`, nhưng log sẽ báo lỗi kết nối Ollama.

### 5.2. Tạo file compose riêng cho server

File `docker-compose.yml` gốc liệt kê rất nhiều biến và mở cổng ra mọi địa chỉ. Ta dùng một file gọn hơn:

```bash
cat > docker-compose.gcp.yml <<'EOF'
services:
  presenton:
    platform: linux/amd64
    build:
      context: .
      dockerfile: Dockerfile
    image: presenton-uscc:latest
    container_name: presenton
    restart: unless-stopped
    env_file: .env
    environment:
      - MIGRATE_DATABASE_ON_STARTUP=true
      - PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
    ports:
      # Chỉ mở trên localhost của VM; Cloudflare Tunnel đi vào qua đây.
      - "127.0.0.1:5001:80"
      # Callback OAuth của tab ChatGPT (chỉ dùng qua SSH tunnel, xem mục 9.2).
      - "127.0.0.1:1455:1455"
    volumes:
      - ./app_data:/app_data
EOF
```

Gợi ý: tạo alias để khỏi gõ `-f` mỗi lần.

```bash
echo "alias dc='docker compose -f ~/presenton/docker-compose.gcp.yml --project-directory ~/presenton'" >> ~/.bashrc
source ~/.bashrc
```

Tài liệu từ đây dùng `dc` (tương đương `docker compose -f docker-compose.gcp.yml`).

### 5.3. Build image

```bash
cd ~/presenton
dc build
```

- Lần đầu mất **20–40 phút**: tải Python, Node, Chromium, model nhúng, rồi build Next.js.
- Dockerfile dùng BuildKit (`# syntax=docker/dockerfile:1.7`, `RUN --mount=type=cache`). Docker Engine mới bật BuildKit sẵn, không cần làm gì thêm.
- Lỗi `Killed` hoặc `exit code 137` nghĩa là thiếu RAM: kiểm tra swap (`free -h`) rồi chạy lại.

### 5.4. Chạy

```bash
dc up -d
dc logs -f
```

Chờ đến khi log báo các dịch vụ đã sẵn sàng (Next.js, FastAPI, nginx, và dòng của server collab), rồi bấm `Ctrl+C` để thoát xem log. Container vẫn chạy.

Kiểm tra ngay trên VM:

```bash
curl -I http://127.0.0.1:5001
```

Phải ra `HTTP/1.1 200` hoặc `30x` (chuyển hướng về trang đăng nhập).

---

## 6. Đăng nhập lần đầu và tạo tài khoản cho nhóm

Cloudflare chưa cấu hình, nên dùng SSH tunnel để mở thử trên máy bạn.

**[Windows]**

```powershell
gcloud compute ssh presenton-vm --zone=asia-southeast1-b -- -L 5001:localhost:5001
```

Giữ cửa sổ này mở, rồi trên máy bạn mở http://localhost:5001.

1. Đăng nhập bằng `AUTH_USERNAME` / `AUTH_PASSWORD` trong `.env`. Đây là tài khoản **quản trị chính**.
   - Nếu `.env` không đặt hai biến này, trang **account setup** sẽ hiện ra để bạn tự tạo admin.
2. **Tạo tài khoản cho đồng đội:** vào trang **Admin** (`/admin`, trong menu dashboard), phần **Users**, thêm username/mật khẩu cho từng người. Trang này gọi API `POST /api/v1/admin/users`.
3. Sau khi đăng nhập được, **xoá `AUTH_PASSWORD` khỏi `.env`** để mật khẩu không nằm dạng chữ thường trên đĩa:
   ```bash
   sed -i 's/^AUTH_PASSWORD=.*/AUTH_PASSWORD=/' ~/presenton/.env
   dc up -d
   ```
   Tài khoản đã lưu trong `app_data`, nên xoá biến không làm mất tài khoản.
4. **Quên mật khẩu admin:** đặt lại `AUTH_USERNAME` và `AUTH_PASSWORD`, thêm `RESET_AUTH=true` vào `.env`, rồi chạy `dc up -d`. Sau khi vào lại được thì **xoá dòng `RESET_AUTH`**.

---

## 7. Cloudflare Tunnel: đưa ra presenton.namprojects.site

### 7.1. Tạo tunnel (trên web)

1. Vào https://one.dash.cloudflare.com (Cloudflare **Zero Trust**). Lần đầu nó yêu cầu đặt tên team và chọn gói **Free**; có thể cần nhập thẻ nhưng không bị trừ tiền.
2. Menu **Networks**, chọn **Tunnels**. Ở giao diện mới, mục này có thể nằm ở **Networks → Connectors → Cloudflare Tunnels**.
3. Bấm **Create a tunnel**, chọn **Cloudflared**, đặt tên `presenton-gcp`, bấm **Save tunnel**.
4. Ở bước cài connector, chọn **Debian** và **64-bit**. Cloudflare hiện một khối lệnh có chứa **token**; copy lệnh đó.

### 7.2. Cài connector trên VM

**[VM]** Cài cloudflared từ kho apt của Cloudflare:

```bash
sudo mkdir -p --mode=0755 /usr/share/keyrings
curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg | sudo tee /usr/share/keyrings/cloudflare-main.gpg >/dev/null
echo 'deb [signed-by=/usr/share/keyrings/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main' | sudo tee /etc/apt/sources.list.d/cloudflared.list
sudo apt-get update && sudo apt-get install -y cloudflared
```

Sau đó chạy lệnh **cài dịch vụ** mà Cloudflare cho, có dạng:

```bash
sudo cloudflared service install <TOKEN-DÀI-CLOUDFLARE-CHO>
```

Kiểm tra:

```bash
systemctl status cloudflared --no-pager
```

Quay lại trang web, mục **Connectors** phải hiện trạng thái **Connected / Healthy**.

### 7.3. Thêm Public Hostname

Vẫn trong tunnel `presenton-gcp`, bấm **Next** (hoặc tab **Public Hostname**, rồi **Add a public hostname**):

| Trường | Giá trị |
|---|---|
| Subdomain | `presenton` |
| Domain | `namprojects.site` |
| Path | *(để trống)* |
| Service Type | `HTTP` |
| URL | `localhost:5001` |

Bấm **Save**.

- Cloudflare **tự tạo bản ghi DNS** `presenton` kiểu CNAME trỏ tới `<tunnel-id>.cfargotunnel.com`, ở chế độ Proxied (đám mây cam). Nếu trước đó đã có bản ghi `presenton`, hãy xoá nó trong **DNS → Records** rồi lưu lại hostname.
- **HTTPS:** Cloudflare cấp chứng chỉ ở phía ngoài. Đoạn Cloudflare → VM đi trong tunnel đã mã hoá, nên Service để `HTTP` là đúng. Chế độ SSL/TLS của zone (Flexible/Full) không ảnh hưởng đến tunnel.
- **WebSocket:** tính năng sửa song song cần websocket ở `/collab/`. Cloudflare Tunnel chuyển websocket mặc định. Kiểm tra cho chắc: dashboard tên miền `namprojects.site`, mục **Network**, công tắc **WebSockets** phải **On**.

Mở https://presenton.namprojects.site và đăng nhập. Xong!

---

## 8. (Tuỳ chọn, nên làm) Cloudflare Access: chặn người lạ từ cửa

Presenton đã có đăng nhập riêng. Access thêm một lớp nữa: chỉ email trong danh sách mới thấy được trang đăng nhập, giúp chặn dò mật khẩu và bot.

1. Zero Trust, chọn **Access**, rồi **Applications**, bấm **Add an application**, chọn **Self-hosted**.
2. **Application name:** `Presenton`. **Session duration:** `24 hours` hoặc `1 week`.
3. **Application domain:** subdomain `presenton`, domain `namprojects.site`, path để trống.
4. **Policies**, bấm **Add a policy**:
   - Name `Team`, Action **Allow**.
   - Include, chọn **Emails** rồi nhập email từng thành viên. Hoặc chọn **Emails ending in** `@<tên-miền-công-ty>`.
5. **Login methods:** mặc định có **One-time PIN** (mã gửi qua email). Muốn đăng nhập bằng Google thì vào **Settings → Authentication → Login methods → Add new → Google** và làm theo hướng dẫn.
6. Bấm **Save**.

Từ giờ, vào https://presenton.namprojects.site sẽ gặp màn hình Cloudflare trước, sau đó mới đến màn hình đăng nhập Presenton.

> Lưu ý: nếu dùng **API key của Presenton** để gọi API từ công cụ bên ngoài (MCP, script…), Access sẽ chặn những request đó. Tạo **Service Token** trong Access (**Access → Service credentials**), thêm vào policy, rồi gửi kèm header `CF-Access-Client-Id` / `CF-Access-Client-Secret`.

---

## 9. Cấu hình nhà cung cấp AI

Đăng nhập bằng **admin**, vào **Settings**, phần nhà cung cấp AI.

### 9.1. Claude: tab **Anthropic** + API key

1. Vào https://console.anthropic.com, mục **API Keys**, bấm **Create Key**. Nạp credit hoặc thêm thẻ ở **Billing**.
2. Trong Presenton: **Settings**, tab **Anthropic**, dán key, chọn model, rồi **Save**.

> Presenton **chỉ** dùng được Claude bằng API key. Không có (và không được phép làm) kiểu đăng nhập bằng gói Claude Pro/Max cho ứng dụng bên thứ ba như Presenton.

### 9.2. ChatGPT: tab **ChatGPT** (đăng nhập OAuth)

Khi đăng nhập ChatGPT, OpenAI chuyển trình duyệt về `http://localhost:1455/...`. Địa chỉ này phải trỏ tới **container trên VM**, nên khi đăng nhập cần mở SSH tunnel cổng 1455.

**[Windows]** Mở và giữ cửa sổ này trong lúc đăng nhập:

```powershell
gcloud compute ssh presenton-vm --zone=asia-southeast1-b -- -L 1455:localhost:1455
```

Sau đó trên trình duyệt của **chính máy đó**:
1. Mở https://presenton.namprojects.site, vào **Settings**, chọn tab **ChatGPT**, bấm đăng nhập.
2. Đăng nhập OpenAI. Trang chuyển về `localhost:1455`, đi qua tunnel vào VM, rồi báo thành công.
3. Đóng cửa sổ SSH. Token được lưu trên server và tự gia hạn.

Chỉ **admin** mới cấu hình được tab này. Không muốn dùng tunnel thì dùng tab **OpenAI** với API key.

### 9.3. API riêng (tab **Custom**)

URL phải có `/v1`, ví dụ `https://api.vutuanhung.vn/v1`. Thiếu `/v1` sẽ gặp lỗi `404 Not Found nginx`.

---

## 10. Nhập template USCC lên server

Bộ template nằm trên máy bạn ở `D:\Project\Template slide USCC s2\presenton-uscc\`, gồm `uscc_template.json`, 5 file PNG và `import_to_presenton.py`. Script gốc ghi vào đường dẫn của app Windows, nên trên server ta dùng một bản chỉnh nhỏ.

### 10.1. Gửi bộ template lên VM

**[Windows]**

```powershell
cd "D:\Project\Template slide USCC s2"
tar -czf presenton-uscc.tgz presenton-uscc
gcloud compute scp presenton-uscc.tgz presenton-vm:~ --zone=asia-southeast1-b
```

**[VM]**

```bash
cd ~ && tar -xzf presenton-uscc.tgz && ls ~/presenton-uscc
```

### 10.2. Script nhập cho server

**[VM]**

```bash
cat > ~/presenton-uscc/import_server.py <<'EOF'
# Nhập template USCC vào Presenton chạy Docker. Dừng container trước khi chạy.
import datetime, json, os, shutil, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else "~/presenton/app_data")
d = json.load(open(os.path.join(HERE, "uscc_template.json"), encoding="utf8"))
dst = os.path.join(APP, "pptx-to-json", d["id"])
os.makedirs(dst, exist_ok=True)
for f in ("bg-content.png", "bg-cover.png", "bg-statement.png", "logo.png", "thumbnail.png"):
    shutil.copy(os.path.join(HERE, f), dst)
db = os.path.join(APP, "fastapi.db")
assert os.path.exists(db), f"Không thấy {db} - hãy chạy Presenton ít nhất một lần trước"
shutil.copy(db, db + ".bak-before-uscc")
c = sqlite3.connect(db)
now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")
c.execute("delete from template_v2 where id=? or (name='USCC' and is_default=0)", (d["id"],))
c.execute("insert into template_v2(id,name,description,raw_layouts,components,layouts,assets,created_at,updated_at,"
          "merged_components,is_default,owner_id,theme) values(?,?,?,'null','null',?,?,?,?,?,0,NULL,?)",
          (d["id"], d["name"], d["description"], json.dumps(d["layouts"], ensure_ascii=False),
           json.dumps(d["assets"], ensure_ascii=False), now, now,
           json.dumps(d["merged_components"], ensure_ascii=False), json.dumps(d["theme"], ensure_ascii=False)))
c.commit()
print("OK:", c.execute("select id,name from template_v2 where id=?", (d["id"],)).fetchone())
EOF
```

### 10.3. Chạy

**[VM]**

```bash
dc stop
sudo python3 ~/presenton-uscc/import_server.py ~/presenton/app_data
dc start
```

- Dùng `sudo` vì thư mục `app_data` do container tạo nên thuộc user `root`.
- `owner_id = NULL`: ở chế độ `PRESENTON_SHARED_WORKSPACE=true`, mọi người đều thấy template này.
  - Nếu **tắt** chế độ nhóm, template "không chủ" và không phải mặc định có thể bị ẩn với người dùng thường.
  - Khi đó gán `owner_id` bằng id của từng user (lấy từ bảng `user`): `sudo sqlite3 ~/presenton/app_data/fastapi.db "select id,username from user;"`.
- Ảnh được phục vụ ở `/app_data/pptx-to-json/<id>/...`, đúng như trên bản Windows.

Vào **Templates** trên web sẽ thấy **USCC (13 layout)**.

---

## 11. Vận hành: cập nhật, sao lưu, log, xử lý sự cố

### 11.1. Cập nhật khi sửa code

**Cách A (GitHub):**

[Windows] commit và push:

```powershell
cd "D:\Project\Template slide USCC s2\presenton-main\presenton-main"
git add -A; git commit -m "update"; git push
```

[VM] kéo về, build lại, khởi động lại:

```bash
cd ~/presenton && git pull && dc build && dc up -d
```

**Cách B (copy):** làm lại mục 4 cách B. Lệnh `tar -xzf` ghi đè code, **không đụng `app_data`**, `.env` hay `docker-compose.gcp.yml`. Sau đó chạy `dc build && dc up -d`.

Dọn image cũ cho đỡ đầy đĩa:

```bash
docker image prune -f
```

### 11.2. Sao lưu ổ đĩa tự động (snapshot hằng ngày)

**[Windows]**

```powershell
gcloud compute resource-policies create snapshot-schedule presenton-daily `
  --region=asia-southeast1 --daily-schedule --start-time=19:00 `
  --max-retention-days=7 --on-source-disk-delete=keep-auto-snapshots
gcloud compute disks add-resource-policies presenton-vm `
  --zone=asia-southeast1-b --resource-policies=presenton-daily
```

`19:00` là giờ UTC, tức 02:00 sáng giờ Việt Nam. Khôi phục: tạo disk mới từ snapshot trong **Compute Engine → Snapshots**.

### 11.3. Sao lưu `app_data` lên Cloud Storage (bản riêng, dễ tải về)

**[Windows]** Tạo bucket. Tên bucket phải duy nhất toàn cầu:

```powershell
gcloud storage buckets create gs://<PROJECT_ID>-presenton-backup --location=asia-southeast1
```

**[VM]** Tạo script sao lưu và lịch chạy mỗi đêm:

```bash
cat > ~/backup-presenton.sh <<'EOF'
#!/bin/bash
set -e
TS=$(date +%F-%H%M)
F=/tmp/presenton-app_data-$TS.tgz
# sqlite: tạo bản sao nhất quán trước khi nén
sqlite3 /home/$USER/presenton/app_data/fastapi.db ".backup '/home/$USER/presenton/app_data/fastapi.backup.db'"
tar -czf $F -C /home/$USER/presenton app_data
gcloud storage cp $F gs://<PROJECT_ID>-presenton-backup/
rm -f $F /home/$USER/presenton/app_data/fastapi.backup.db
EOF
sed -i "s/\$USER/$USER/g" ~/backup-presenton.sh
chmod +x ~/backup-presenton.sh
sudo ~/backup-presenton.sh   # chạy thử
( sudo crontab -l 2>/dev/null; echo "30 19 * * * $HOME/backup-presenton.sh >> /var/log/presenton-backup.log 2>&1" ) | sudo crontab -
```

Nhớ thay `<PROJECT_ID>` trong script. Muốn tự xoá bản cũ hơn 30 ngày, vào bucket, tab **Lifecycle**, bấm **Add a rule**, chọn **Delete object**, điều kiện **Age 30 days**.

### 11.4. Xem log

```bash
dc logs -f --tail=200            # toàn bộ container
dc logs -f | grep -i collab      # riêng server sửa song song
sudo journalctl -u cloudflared -f   # tunnel Cloudflare
docker stats                     # RAM/CPU đang dùng
```

### 11.5. Xử lý sự cố

| Triệu chứng | Nguyên nhân hay gặp | Cách xử lý |
|---|---|---|
| Trang Cloudflare báo **502 Bad Gateway** / **Error 1033** | Container chưa chạy, đang khởi động, hoặc cloudflared mất kết nối | `dc ps` xem container có `Up` không; `curl -I http://127.0.0.1:5001` trên VM; `systemctl status cloudflared`. Kiểm tra Public Hostname trỏ đúng `HTTP` + `localhost:5001`. |
| Hai người mở cùng một bài nhưng **không thấy thay đổi của nhau** | Websocket `/collab/` bị chặn, hoặc server collab không chạy | F12, tab **Network**, lọc **WS**: phải có kết nối `wss://presenton.namprojects.site/collab/...` trạng thái **101**. Bật **WebSockets** trong Cloudflare (mục 7.3). Trên VM: `dc logs \| grep -i collab`, và `docker exec presenton curl -s http://127.0.0.1:1234/collab/health` (in ra `ok` là server collab đang chạy). Kiểm tra `PRESENTON_SHARED_WORKSPACE=true` nếu hai người khác tài khoản. |
| Đăng nhập xong vẫn bị **401 Unauthorized** / bị đá ra liên tục | Cookie phiên không khớp tên miền, hoặc sai `PRESENTON_PUBLIC_URL` | Đặt đúng `PRESENTON_PUBLIC_URL=https://presenton.namprojects.site`, `dc up -d`, xoá cookie trang rồi đăng nhập lại. Quên mật khẩu admin: mục 6, bước 4 (`RESET_AUTH`). |
| Gọi AI báo **404 Not Found (nginx)** | URL API thiếu `/v1` (tab Custom) | Sửa thành `https://.../v1`. |
| Build bị **Killed** / exit 137; container tự khởi động lại; xuất PDF thất bại | Thiếu RAM | `free -h` kiểm tra swap (mục 3.3); `docker stats`; nâng VM: `gcloud compute instances stop presenton-vm --zone=asia-southeast1-b`, rồi `gcloud compute instances set-machine-type presenton-vm --zone=asia-southeast1-b --machine-type=e2-standard-4`, rồi `start`. |
| Đăng nhập tab **ChatGPT** treo ở `localhost:1455` / "This site can't be reached" | Chưa mở SSH tunnel cổng 1455, hoặc mở trên máy khác máy đang dùng trình duyệt | Chạy lệnh tunnel ở mục 9.2 **trên đúng máy** đang mở trình duyệt, giữ cửa sổ mở trong lúc đăng nhập. Kiểm tra compose có dòng `127.0.0.1:1455:1455`. |
| Đầy ổ đĩa | Image cũ, file xuất tích tụ | `docker system df`, `docker image prune -f`, xoá bớt `app_data/exports`; hoặc tăng disk: `gcloud compute disks resize presenton-vm --size=100GB --zone=asia-southeast1-b` (Ubuntu tự giãn phân vùng sau khi khởi động lại). |
| Không thấy template USCC | Nhập khi container đang chạy, hoặc tắt chế độ nhóm | Làm lại mục 10.3 (nhớ `dc stop` trước); xem lưu ý `owner_id`. |
| Log báo lỗi kết nối Ollama / Mem0 | Mem0 mặc định gọi Ollama | Đặt `MEM0_ENABLED=false` trong `.env`, `dc up -d`. |

---

### Phụ lục: lệnh hay dùng

```bash
dc ps                 # trạng thái
dc restart            # khởi động lại
dc stop / dc start    # dừng / chạy lại (giữ container)
dc down               # xoá container (KHÔNG xoá app_data)
dc up -d              # tạo/chạy lại theo cấu hình mới
```

Tắt VM khi không dùng để tiết kiệm (vẫn trả tiền ổ đĩa):

```powershell
gcloud compute instances stop presenton-vm --zone=asia-southeast1-b
gcloud compute instances start presenton-vm --zone=asia-southeast1-b
```

Bật lại VM thì container (`restart: unless-stopped`) và cloudflared (systemd) tự chạy.
