FROM ubuntu:22.04

# Avoid interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Set hostname to sandbox
ENV HOSTNAME=sandbox

# Configure apt source to use Aliyun mirror

# Update and install basic tools
RUN apt-get update && apt-get install -y \
    ca-certificates \
    bc \
    curl \
    wget \
    gnupg \
    software-properties-common \
    xvfb \
    x11vnc \
    xterm \
    tmux \
    socat \
    supervisor \
    websockify \
    pandoc \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Tao user ubuntu (KHONG cap sudo — luat cung muc 6 cua docs/spec/00-tong-quan.md:
# "bo sudo NOPASSWD khoi image sandbox". ubuntu la user chay MCP server + CLI
# engine (agy/claude), giu HOME tam cua phien dang nhap CLI — khong duoc co
# duong leo thang quyen root).
RUN useradd -m -d /home/ubuntu -s /bin/bash ubuntu

# Tao user rieng cho Chrome, khac voi user ubuntu dang chay CLI/MCP (luat cung
# muc 6: "Chrome chay user khac voi CLI"). Xvfb/x11vnc van chay bang root (nhu
# truoc), chi tien trinh Chrome tu chuyen sang user nay — X11 socket
# (/tmp/.X11-unix) khong dung co che xac thuc (Xvfb khong truyen -auth) nen
# user nay van ket noi duoc vao DISPLAY :1.
RUN useradd -m -d /home/browser -s /usr/sbin/nologin browser && \
    mkdir -p /home/browser/.chrome-profile && \
    chown -R browser:browser /home/browser

# Cai agy (Antigravity CLI) — khong co goi apt/npm chinh thuc, cai qua script
# bootstrap chinh thuc cua antigravity.google (da kiem tra noi dung script:
# khong sudo, chi dung curl/tar/sha512sum, co kiem tra checksum SHA512 truoc
# khi cai) — xem https://antigravity.google/docs/getting-started?tab=cli
# ("Install the client (fast path)"). Cai bang user ubuntu vi binary duoc ghi
# vao $HOME/.local/bin cua chinh user chay installer (dong co CLI lop 3, xem
# docs/spec/01-dong-co-cli.md).
USER ubuntu
RUN curl -fsSL https://antigravity.google/cli/install.sh | bash
USER root
ENV PATH="/home/ubuntu/.local/bin:${PATH}"

# Thu muc ket qua nhiem vu — CLI (agy/claude) ghi file xuat ra day (DoD dong 3
# cua docs/spec/00-tong-quan.md: ".docx tai duoc tu UI")
RUN mkdir -p /home/ubuntu/output && chown ubuntu:ubuntu /home/ubuntu/output

# Install Python 3.10.12
RUN add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y python3.10 python3.10-venv python3.10-dev python3-pip && \
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.10 1 && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install uv
RUN pip3 install uv

# Configure uv to use Aliyun mirror
# UV_INDEX_URL mirror override removed for local build test

# Install Node.js 20.18.0
RUN mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" | tee /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Configure npm to use Aliyun mirror

# Cai Claude Code CLI (npm global) — dong co CLI lop 3 thu hai, xem
# docs/spec/01-dong-co-cli.md muc 4. Ghim version cu the (review Opus PR #36)
# thay vi "latest" de build lap lai duoc — 2.1.295 la ban moi nhat tren npm
# tai thoi diem viet (kiem bang `npm view @anthropic-ai/claude-code version`,
# 09/10/2026). Nang version: doi so nay + ghi lai ngay kiem tra.
RUN npm install -g @anthropic-ai/claude-code@2.1.295

# Cai python-docx (xuat file .docx) — DoD dong 3 cua docs/spec/00-tong-quan.md
# can cong cu xuat .docx; pandoc da cai o buoc "basic tools" phia tren
RUN pip3 install python-docx

# Install Google Chrome
RUN add-apt-repository ppa:xtradeb/apps -y && \
    apt-get update && \
    apt-get install -y chromium  --no-install-recommends && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Install Chinese fonts and language support
RUN apt-get update && apt-get install -y \
    fonts-noto-cjk \
    fonts-noto-color-emoji \
    language-pack-zh-hans \
    locales \
    && locale-gen zh_CN.UTF-8 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Set default locale
#ENV LANG=zh_CN.UTF-8 \
#    LANGUAGE=zh_CN:zh \
#    LC_ALL=zh_CN.UTF-8

# Set working directory
WORKDIR /app

# Copy project files (copy dependency files first to leverage cache)
COPY pyproject.toml ./

# Install Python dependencies
RUN uv sync --no-dev

# Copy remaining project files
COPY . .

# Ensure application files are writable by app user
RUN chown -R ubuntu:ubuntu /app

# Configure supervisor
COPY supervisord.conf /etc/supervisor/conf.d/app.conf

# Expose ports
EXPOSE 8080 9222 5900 5901

ENV UVI_ARGS=""
ENV CHROME_ARGS=""

# Use supervisor to start all services
CMD ["supervisord", "-n", "-c", "/app/supervisord.conf"] 
