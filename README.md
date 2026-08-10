# 🍑 小宝的成长日记 (Child Growth Diary)

一个记录孩子成长的私人网站，支持图片/视频上传、时间线展示、管理后台等功能。

## ✨ 功能特性

- 📅 **时间线展示** - 按日期排序，文字+图片/视频交替显示
- 📝 **日记管理** - 创建、编辑、删除日记
- 🖼️ **媒体上传** - 支持图片和视频上传
- 📱 **手机适配** - 响应式设计，支持手机端
- 🔒 **密码保护** - 管理后台需要密码登录
- 🔄 **自动转换** - iPhone HEIC 图片自动转 JPG，MOV 视频自动转 MP4
- 🖼️ **自动生成缩略图** - 视频自动截取封面
- 📸 **图片压缩** - 上传时自动压缩，生成缩略图
- 🚀 **性能优化** - 图片懒加载、浏览器缓存

## 🛠️ 技术栈

| 组件 | 技术 |
|------|------|
| 后端 | Python + Flask |
| 数据库 | SQLite |
| 图片处理 | Pillow + pillow-heif |
| 视频处理 | FFmpeg |
| WSGI | Gunicorn |

## 📦 安装步骤

### 1. 克隆仓库

```bash
git clone https://github.com/yourusername/child-diary.git
cd child-diary
```

### 2. 创建虚拟环境

```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# 或
venv\Scripts\activate  # Windows
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，设置你的密码和密钥
```

### 5. 生成密码哈希

```bash
python3 -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your-password'))"
```

将生成的哈希值填入 `.env` 文件的 `ADMIN_PASSWORD_HASH`。

### 6. 启动应用

```bash
# 开发模式
python3 app.py

# 生产模式
gunicorn -w 2 -b 0.0.0.0:5000 app:app
```

## 📁 项目结构

```
child-diary/
├── app.py                    # Flask 主程序
├── requirements.txt          # Python 依赖
├── .env.example              # 环境变量示例
├── .gitignore                # Git 忽略文件
├── README.md                 # 项目说明
├── templates/                # HTML 模板
│   ├── timeline.html         # 时间线页面
│   ├── admin.html            # 写日记页面
│   ├── edit.html             # 编辑日记页面
│   └── login.html            # 登录页面
├── static/                   # 静态文件
│   └── favicon.svg           # 图标
└── uploads/                  # 上传的媒体文件（不提交到 Git）
```

## 🔧 配置说明

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `SECRET_KEY` | Flask 会话密钥 | 随机生成 |
| `ADMIN_PASSWORD_HASH` | 管理员密码哈希 | `your-password` 的哈希 |

### 数据库

数据库会在首次运行时自动创建，包含以下表：
- `entries` - 日记条目
- `media` - 媒体文件记录

## 🚀 部署

### 使用 Systemd (Linux)

创建服务文件 `/etc/systemd/system/child-diary.service`:

```ini
[Unit]
Description=Child Growth Diary
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/path/to/child-diary
ExecStart=/path/to/child-diary/venv/bin/gunicorn -w 2 -b 0.0.0.0:5000 app:app
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable child-diary
sudo systemctl start child-diary
```

### 使用 Docker

```dockerfile
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y ffmpeg && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "app:app"]
```

```bash
docker build -t child-diary .
docker run -p 5000:5000 -v ./uploads:/app/uploads child-diary
```

## 📸 截图

(添加你的截图)

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 🙏 致谢

- [Flask](https://flask.palletsprojects.com/)
- [Pillow](https://python-pillow.org/)
- [FFmpeg](https://ffmpeg.org/)
