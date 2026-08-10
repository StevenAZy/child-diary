# 李一禾成长日记 — 部署与迁移文档

> 最后更新：2026-06-27
> 域名：请在部署时设置
> 管理密码：请在部署时设置

---

## 一、项目概览

一个记录孩子成长的私人网站，功能：
- 时间线展示（从旧到新，文字+图片/视频交替显示）
- 发布日记（日期、标题、正文、图片/视频）
- 编辑 / 删除日记
- 管理密码保护
- iPhone HEIC 图片自动转 JPG
- iPhone MOV 视频自动转 MP4（ffmpeg 后台异步）
- 视频自动截取封面缩略图
- 图片客户端压缩（2048px + JPEG 82%）
- 上传进度条
- Cloudflare Tunnel 公网访问
- 手机端适配

---

## 二、技术栈

| 组件 | 技术 | 版本 |
|------|------|------|
| 服务器 | Debian 13 (trixie) | 6.12.90 |
| 后端 | Python + Flask | 3.1.3 |
| WSGI | Gunicorn | 26.0.0 |
| 数据库 | SQLite | 内置 |
| 图片处理 | Pillow + pillow-heif | 12.2.0 / 1.3.0 |
| 视频处理 | FFmpeg | 7.1.5 |
| HEIC 转换 | ImageMagick (备用) | 7.1.1 |
| 隧道 | Cloudflare Tunnel (cloudflared) | 2026.6.1 |
| 代理 | mihomo (Clash Verge) | 端口 7897 |

---

## 三、目录结构

```
~/child-diary/
├── app.py                    # Flask 主程序
├── diary.db                  # SQLite 数据库
├── venv/                     # Python 虚拟环境
├── uploads/                  # 上传的图片/视频
│   ├── 1/                   # 按日记 ID 分目录
│   │   ├── xxx.jpg          # 原图/转换后的图
│   │   ├── xxx.mp4          # 转换后的视频
│   │   └── xxx_thumb.jpg    # 视频封面缩略图
│   ├── 2/
│   └── ...
├── static/
│   └── favicon.svg          # 🍑 图标
└── templates/
    ├── timeline.html         # 公开时间线页面
    ├── admin.html            # 写日记页面（需登录）
    ├── edit.html             # 编辑日记页面（需登录）
    └── login.html            # 登录页面
```

---

## 四、数据库结构

```sql
-- 日记条目
CREATE TABLE entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    entry_date TEXT NOT NULL,           -- YYYY-MM-DD 格式，按此排序
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 媒体文件
CREATE TABLE media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id INTEGER NOT NULL,
    filename TEXT NOT NULL,             -- 原始文件名
    filepath TEXT NOT NULL,             -- 存储路径（相对 uploads/）
    media_type TEXT NOT NULL,           -- 'image' 或 'video'
    poster TEXT DEFAULT '',             -- 视频封面缩略图路径
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);
```

---

## 五、系统服务

### 5.1 Flask 应用服务

文件：`/etc/systemd/system/child-diary.service`

```ini
[Unit]
Description=Child Growth Diary
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/path/to/child-diary
ExecStart=/path/to/child-diary/venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 --timeout 300 --limit-request-line 0 --limit-request-field_size 0 app:app
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

管理命令：
```bash
sudo systemctl start child-diary      # 启动
sudo systemctl stop child-diary       # 停止
sudo systemctl restart child-diary    # 重启
sudo systemctl status child-diary     # 查看状态
sudo journalctl -u child-diary -f     # 查看日志
```

### 5.2 Cloudflare Tunnel 服务

文件：`/etc/systemd/system/cloudflared-tunnel.service`

```ini
[Unit]
Description=Cloudflare Tunnel
After=network-online.target child-diary.service
Wants=network-online.target

[Service]
Type=simple
User=www-data
Environment=HTTPS_PROXY=http://127.0.0.1:7897
Environment=HTTP_PROXY=http://127.0.0.1:7897
ExecStart=/usr/local/bin/cloudflared tunnel run --protocol http2 --token-file /tmp/cf-token.txt
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

管理命令：
```bash
sudo systemctl start cloudflared-tunnel
sudo systemctl stop cloudflared-tunnel
sudo systemctl status cloudflared-tunnel
sudo journalctl -u cloudflared-tunnel -f
```

**注意**：隧道依赖 mihomo 代理（127.0.0.1:7897）绕过 GFW。如果代理没开，隧道连不上。

---

## 六、防火墙

使用 ufw，已开放端口：

```bash
sudo ufw status
```

```
22/tcp      ALLOW       Anywhere      # SSH
5000/tcp    ALLOW       Anywhere      # Flask 应用
7897/tcp    ALLOW       Anywhere      # mihomo 代理
```

---

## 七、Cloudflare 配置

### 7.1 域名 DNS

- 域名：your-domain.com
- 注册商：Namesilo
- Nameservers：已改为 Cloudflare（xxx.ns.cloudflare.com / yyy.ns.cloudflare.com）

### 7.2 Tunnel 配置

在 Cloudflare Dashboard → Networks → Tunnels 中：

- 隧道名：child-diary
- Tunnel ID：`your-tunnel-id`
- Token 存储位置：`/tmp/cf-token.txt`

Public Hostname 配置：

| Hostname | Service |
|----------|---------|
| your-domain.com | http://localhost:5000 |

### 7.3 DNS 记录

Cloudflare DNS 中需要一条 CNAME 记录（Tunnel 自动创建或手动添加）：

| Type | Name | Target | Proxy |
|------|------|--------|-------|
| CNAME | @ | your-tunnel-id.cfargotunnel.com | Proxied (橙色云朵) |

---

## 八、访问地址

| 场景 | 地址 |
|------|------|
| 局域网访问 | http://<服务器局域网IP>:5000 |
| 公网访问 | https://your-domain.com |
| 管理页面 | /admin（需登录） |
| 登录页面 | /login |

---

## 九、从零部署步骤

以下是在全新 Debian 系统上完整部署的步骤：

### 9.1 系统准备

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv ffmpeg imagemagick libheif-dev curl wget
```

### 9.2 创建项目

```bash
mkdir -p ~/child-diary/{templates,static,uploads}
cd ~/child-diary
python3 -m venv venv
source venv/bin/activate

# 使用清华镜像加速
pip install flask gunicorn pillow pillow-heif \
  -i https://pypi.tuna.tsinghua.edu.cn/simple \
  --trusted-host pypi.tuna.tsinghua.edu.cn
```

### 9.3 部署代码

将以下文件复制到对应位置：
- `app.py` → `~/child-diary/app.py`
- `templates/timeline.html` → `~/child-diary/templates/timeline.html`
- `templates/admin.html` → `~/child-diary/templates/admin.html`
- `templates/edit.html` → `~/child-diary/templates/edit.html`
- `templates/login.html` → `~/child-diary/templates/login.html`
- `static/favicon.svg` → `~/child-diary/static/favicon.svg`

### 9.4 启动 Flask 服务

```bash
# 创建 systemd 服务文件（见 5.1）
sudo cp child-diary.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable child-diary
sudo systemctl start child-diary
```

### 9.5 配置防火墙

```bash
sudo ufw allow 5000/tcp
sudo ufw allow 22/tcp
```

### 9.6 安装 Cloudflare Tunnel

```bash
# 下载 cloudflared
wget -q 'https://gh-proxy.com/https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb' -O /tmp/cloudflared.deb
sudo dpkg -i /tmp/cloudflared.deb
```

### 9.7 配置隧道

1. 在 Cloudflare Dashboard 创建 Tunnel
2. 获取 Token，保存到 `/tmp/cf-token.txt`
3. 创建 systemd 服务文件（见 5.2）
4. 启动服务

```bash
sudo cp cloudflared-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cloudflared-tunnel
sudo systemctl start cloudflared-tunnel
```

### 9.8 配置域名

1. Namesilo 修改 Nameservers 为 Cloudflare 提供的地址
2. Cloudflare DNS 中添加 CNAME 记录指向隧道
3. Tunnel Public Hostname 配置 your-domain.com → http://localhost:5000

---

## 十、数据备份与迁移

### 10.1 备份

需要备份的文件：

```bash
# 创建备份
tar czf ~/child-diary-backup-$(date +%Y%m%d).tar.gz \
  ~/child-diary/app.py \
  ~/child-diary/diary.db \
  ~/child-diary/templates/ \
  ~/child-diary/static/ \
  ~/child-diary/uploads/

# 或者更简洁
tar czf ~/backup.tar.gz -C ~ child-diary/app.py child-diary/diary.db child-diary/templates child-diary/static child-diary/uploads
```

### 10.2 迁移到新机器

```bash
# 1. 在新机器上安装依赖
sudo apt install -y python3-pip python3-venv ffmpeg imagemagick libheif-dev

# 2. 复制备份到新机器
scp ~/backup.tar.gz user@新IP:~/

# 3. 在新机器上解压
cd ~
tar xzf backup.tar.gz

# 4. 创建虚拟环境并安装 Python 包
cd ~/child-diary
python3 -m venv venv
source venv/bin/activate
pip install flask gunicorn pillow pillow-heif \
  -i https://pypi.tuna.tsinghua.edu.cn/simple

# 5. 创建 uploads 目录
mkdir -p uploads static

# 6. 部署 systemd 服务
sudo cp /path/to/child-diary.service /etc/systemd/system/
sudo cp /path/to/cloudflared-tunnel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable child-diary cloudflared-tunnel
sudo systemctl start child-diary

# 7. 配置防火墙
sudo ufw allow 5000/tcp
sudo ufw allow 22/tcp

# 8. 重新配置 Cloudflare Tunnel Token
echo '新的token' > /tmp/cf-token.txt
sudo systemctl start cloudflared-tunnel
```

### 10.3 数据库导出（可选）

```bash
cd ~/child-diary
source venv/bin/activate
python3 -c "
import sqlite3, json
db = sqlite3.connect('diary.db')
entries = [dict(row) for row in db.execute('SELECT * FROM entries')]
media = [dict(row) for row in db.execute('SELECT * FROM media')]
with open('export.json', 'w') as f:
    json.dump({'entries': entries, 'media': media}, f, ensure_ascii=False, indent=2)
print(f'导出 {len(entries)} 条日记, {len(media)} 个媒体文件')
"
```

---

## 十一、常用运维操作

### 修改管理密码

编辑 `~/child-diary/.env` 文件，设置新的密码哈希：
```bash
# 生成新密码的哈希
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('新密码'))"

# 将生成的哈希添加到 .env 文件
ADMIN_PASSWORD_HASH=生成的哈希值
```
然后重启服务：`sudo systemctl restart child-diary`

### 查看日志

```bash
# Flask 应用日志
sudo journalctl -u child-diary -f --no-hostname

# Cloudflare Tunnel 日志
sudo journalctl -u cloudflared-tunnel -f --no-hostname
```

### 清理孤立媒体文件

```bash
cd ~/child-diary
source venv/bin/activate
python3 << 'EOF'
import sqlite3, os, glob
db = sqlite3.connect('diary.db')
db_files = set(row[0] for row in db.execute('SELECT filepath FROM media'))
for f in glob.glob('uploads/*/*'):
    rel = f.replace('uploads/', '', 1)
    if not os.path.isdir(f) and rel not in db_files:
        os.remove(f)
        print(f'删除孤立文件: {f}')
db.close()
EOF
```

### 手动生成视频缩略图

```bash
cd ~/child-diary
source venv/bin/activate
python3 << 'EOF'
import sqlite3, os, subprocess
db = sqlite3.connect('diary.db')
for mid, fpath in db.execute("SELECT id, filepath FROM media WHERE media_type='video'"):
    vpath = os.path.join('uploads', fpath)
    thumb = os.path.join('uploads', fpath.rsplit('.',1)[0] + '_thumb.jpg')
    if os.path.exists(vpath) and not os.path.exists(thumb):
        subprocess.run(['ffmpeg','-i',vpath,'-ss','0','-vframes','1','-vf','scale=480:-1','-q:v','5','-y',thumb], capture_output=True)
        print(f'生成: {thumb}')
db.close()
EOF
```

### 硬盘空间检查

```bash
du -sh ~/child-diary/uploads/
du -sh ~/child-diary/diary.db
df -h /
```

---

## 十二、已知限制与注意事项

1. **Cloudflare 免费版上传限制**：单文件最大 100MB，大视频需压缩后上传
2. **Cloudflare Tunnel 依赖代理**：必须保持 mihomo (7897端口) 运行，否则隧道连不上
3. **Gunicorn 2 workers**：单用户场景足够，多用户需增加 worker 数
4. **SQLite 并发**：不适合高并发写入，个人使用无问题
5. **笔记本休眠**：休眠后网站下线，需唤醒。建议关闭自动休眠
6. **HEIC 转换**：优先使用 Pillow (pillow-heif)，ImageMagick 作为备用
7. **视频缩略图**：ffmpeg 从视频第 1 秒截取，如果视频不到 1 秒可能截不到
8. **favicon**：使用 SVG 格式的 🍑 emoji，极少数旧浏览器不支持

---

## 十三、文件清单（完整代码）

如需获取完整代码文件，从 Debian 笔记本上复制：

```bash
# 从 Debian 复制所有代码文件到本地
scp -r user@<服务器IP>:~/child-diary/app.py ./
scp -r user@<服务器IP>:~/child-diary/templates/ ./templates/
scp -r user@<服务器IP>:~/child-diary/static/ ./static/
```

数据库和上传文件也一并备份：
```bash
scp user@<服务器IP>:~/child-diary/diary.db ./
scp -r user@<服务器IP>:~/child-diary/uploads/ ./uploads/
```

---

## 十四、自动备份

### 14.1 备份脚本

位置：

备份内容：app.py、diary.db、templates/、static/、uploads/（所有图片视频）

输出文件：

自动清理超过 30 天的旧备份。

### 14.2 定时任务

每天凌晨 3:00 自动执行，日志写入 



### 14.3 手动备份



### 14.4 查看备份



### 14.5 恢复备份



### 14.6 备份目录结构


