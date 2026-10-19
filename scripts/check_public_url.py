#!/usr/bin/env python3

import os
import sys
import time
import base64
import shutil
import pathlib
import tarfile
import logging
import tempfile
import subprocess
import urllib.request
from datetime import datetime
from email.message import EmailMessage


# 配置日志记录
logging.basicConfig(filename='/tmp/veracrypt.log', level=logging.INFO, format='%(message)s')


# =============== ⚙️ 配置类 ===============
class Config:
    BASE_DIR = pathlib.Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / "output"
    RCLONE_REMOTE = "FEADXUS-Google-Drive"
    RCLONE_REMOTE_PATH = f"{RCLONE_REMOTE}:/X/"
    
    # Gmail 专属配置
    SCOPES = ['https://mail.google.com/']
    EMAIL_FROM = "feadxus@gmail.com"
    EMAIL_TO = "feadxus@icloud.com"

CONFIG = Config()


# =============== 🛠️ 工具函数 ===============
def run(cmd: str, cwd: str = None, capture: bool = False) -> subprocess.CompletedProcess:
    """执行 shell 命令的通用函数"""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            executable="/bin/bash",
            cwd=cwd,
            capture_output=capture,
            text=True,
            check=True
        )
        return result
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"命令执行失败: {cmd}\n{e.stderr}")


# =============== 📦 环境初始化 ===============
def initialize_environment():
    print("📦 开始环境初始化...", flush=True)

    # 1. 锁死当前环境安装 pip 依赖库
    pip_packages = ["google-auth-oauthlib", "google-api-python-client", "google-auth"]
    subprocess.check_call([sys.executable, "-m", "pip", "install", *pip_packages])

    # 🚀 强行让当前正在运行的 Python 进程刷新缓存,识别新安装的 google 库
    import site
    import importlib
    importlib.reload(site)
    print("🔄 已成功刷新 Python 运行环境类库缓存", flush=True)

    # 2. 下载并安装特定版本的 age (v1.3.2) 带重试
    age_version = "v1.3.2"
    url = f"https://github.com/FiloSottile/age/releases/download/{age_version}/age-{age_version}-linux-amd64.tar.gz"
    tar_path = "/tmp/age.tar.gz"
    extract_dir = "/tmp/age_bin"

    for attempt in range(1, 4):
        try:
            print(f"📥 正在下载 age 工具 (尝试: {attempt}/3)...", flush=True)
            urllib.request.urlretrieve(url, tar_path)
            break
        except Exception as e:
            if attempt == 3: raise e
            time.sleep(3)

    os.makedirs(extract_dir, exist_ok=True)
    with tarfile.open(tar_path, "r:gz") as tar:
        tar.extractall(path=extract_dir)
    src_dir = os.path.join(extract_dir, "age")
    subprocess.check_call(["sudo", "cp", f"{src_dir}/age", f"{src_dir}/age-keygen", "/usr/local/bin/"])
    subprocess.check_call(["sudo", "chmod", "+x", "/usr/local/bin/age", "/usr/local/bin/age-keygen"])

    # 3. 安装常用基础工具并部署 rclone
    subprocess.run("sudo apt-get update && sudo apt-get install -y curl", shell=True, executable="/bin/bash", check=True)
    subprocess.run("curl -fsSL https://rclone.org/install.sh | sudo bash", shell=True, executable="/bin/bash", check=True)



# =============== 🛠️ 设置 rclone 配置 ===============
def setup_rclone_config() -> None:
    rclone_secret = os.getenv("RCLONE_SECRET_DATA")
    if not rclone_secret:
        raise RuntimeError("❌ RCLONE_SECRET_DATA 环境变量未设置")
    conf_dir = os.path.expanduser("~/.config/rclone")
    os.makedirs(conf_dir, exist_ok=True)
    conf_path = os.path.join(conf_dir, "rclone.conf")
    with open(conf_path, "w", encoding="utf-8") as f:
        f.write(rclone_secret)
    print(f"✅ rclone 配置已写入")


# =============== ⚙️ 核心业务逻辑 ===============
def prepare_tunnel_file() -> None:
    CONFIG.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source_file = pathlib.Path("current_tunnel.txt")
    
    # ✅ 重试逻辑：等待 current_tunnel.txt 出现
    max_retries = 10
    retry_interval = 5
    
    for attempt in range(1, max_retries + 1):
        if source_file.is_file():
            print(f"✅ 找到 current_tunnel.txt (尝试 {attempt}/{max_retries})", flush=True)
            target_file = CONFIG.OUTPUT_DIR / f"pinggy_tunnel_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            shutil.copy(source_file, target_file)
            print(f"✅ 已复制到: {target_file}", flush=True)
            return
        
        if attempt < max_retries:
            print(f"⏳ current_tunnel.txt 未找到，{retry_interval} 秒后重试... ({attempt}/{max_retries})", flush=True)
            time.sleep(retry_interval)
        else:
            raise RuntimeError(
                "❌ 错误：在规定时间内未找到 'current_tunnel.txt'！"
                "请确保 Job 1 已成功执行并提交该文件。"
            )


# =============== 🔐 加密并压缩 output 文件夹 ===============
def compress_and_encrypt(work_dir, encrypted_output_name):
    age_public_key = os.getenv('AGE_PUBLIC_KEY', '').strip()
    if not age_public_key:
        raise RuntimeError("AGE_PUBLIC_KEY 环境变量未设置")

    final_encrypted_path = pathlib.Path(work_dir) / encrypted_output_name
    cmd = f"set -o pipefail; tar cJf - {CONFIG.OUTPUT_DIR.name} | age -r '{age_public_key}' > '{final_encrypted_path}'"
    run(cmd, cwd=str(CONFIG.BASE_DIR))


# =============== 📤 上传至 Google Drive 网盘 ===============
def upload_to_gdrive(file_name: str) -> None:
    local_file_path = CONFIG.BASE_DIR / file_name
    run(f"rclone copy \"{local_file_path}\" \"{CONFIG.RCLONE_REMOTE_PATH}\"")
    print("🎉 网盘同步成功!")


# =============== 📧 Gmail 业务模块 (完美复刻本地环境) ===============

def execute_gmail_action(action_type="send", file_name=None):
    """
    💡 利用临时文件机制,完美复刻你本地的 'from_authorized_user_file' 环境
    并完成 发送 或 删除 动作
    """
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build

    token_b64 = os.getenv("GMAIL_TOKEN_BASE64")
    if not token_b64:
        raise RuntimeError("❌ 未检测到 GMAIL_TOKEN_BASE64 环境变量")

    # 1. 解码出原始的 JSON 字符串
    token_json_str = base64.b64decode(token_b64.strip()).decode("utf-8")

    # 2. 核心黑魔法:在系统安全临时目录下创建一个绝对私密的文件
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as temp_token_file:
        temp_token_file.write(token_json_str)
        temp_token_file.flush()
        temp_token_path = temp_token_file.name

    try:
        # 3. 完美复刻你本地的加载方式,让 Google 正常注入刷新器
        creds = Credentials.from_authorized_user_file(temp_token_path, CONFIG.SCOPES)

        # 4. 执行刷新(如果是新运行,expiry时间过期了这里会自动用 refresh_token 去申请新的)
        if creds and creds.expired and creds.refresh_token:
            print("🔄 内存检测到凭证已过期,正在利用原装引擎请求 Google 刷新...", flush=True)
            creds.refresh(Request())

        if not creds or not creds.valid:
            raise RuntimeError("❌ 临时的 Google 凭证对象验证无效.")

        service = build('gmail', 'v1', credentials=creds)

        # 5. 按照策略分流动作
        if action_type == "send":
            file_path = CONFIG.BASE_DIR / file_name
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            msg = EmailMessage()
            msg.set_content("Github Docker")
            msg["Subject"] = "Github Docker"
            msg["From"] = CONFIG.EMAIL_FROM
            msg["To"] = CONFIG.EMAIL_TO

            with open(file_path, "rb") as f:
                msg.add_attachment(f.read(), maintype="application", subtype="octet-stream", filename=file_name)

            encoded_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            sent_msg = service.users().messages().send(userId="me", body={"raw": encoded_message}).execute()
            print(f"📧 邮件成功发送！Message ID: {sent_msg['id']}", flush=True)

        elif action_type == "delete":
            total_deleted = 0
            while True:
                results = service.users().messages().list(userId='me', q='in:sent', maxResults=500).execute()
                messages = results.get('messages', [])
                if not messages: break
                msg_ids = [m['id'] for m in messages]
                service.users().messages().batchDelete(userId='me', body={'ids': msg_ids}).execute()
                total_deleted += len(msg_ids)
            print(f"🧹 已成功从发件箱彻底清空了 {total_deleted} 封发送记录.", flush=True)

    finally:
        # 6. 安全善后:不论成功或失败,必须抹除这个临时生成的明文 JSON 文件
        if os.path.exists(temp_token_path):
            os.unlink(temp_token_path)


# =============== 主流程 ===============
def main():
    encrypted_file_name = "tunnel_data.tar.xz.age"
    try:
        # 环境初始化
        initialize_environment()
        # 配置网盘凭证
        setup_rclone_config()
        # 提取本地隧道地址
        prepare_tunnel_file()
        # 使用 XZ 压缩并通过 age 加密
        compress_and_encrypt(CONFIG.BASE_DIR, encrypted_file_name)
        # 上传至 Google Drive
        upload_to_gdrive(encrypted_file_name)
        print("📧 开始拉起安全沙箱,组装发送邮件...", flush=True)
        execute_gmail_action(action_type="send", file_name=encrypted_file_name)

        print("🧹 开始执行发件箱残留清理...", flush=True)
        for _ in range(2):
            try:
                execute_gmail_action(action_type="delete")
                time.sleep(1)
            except Exception as e:
                logging.error(f"清理发件记录失败尝试: {e}")
                continue

    except Exception as e:
        print(f"❌ 运行失败: {e}", flush=True)
        sys.exit(1)

    finally:
        print("🧹 正在清理本地临时敏感数据...", flush=True)
        if CONFIG.OUTPUT_DIR.exists(): shutil.rmtree(CONFIG.OUTPUT_DIR)
        local_archive = CONFIG.BASE_DIR / encrypted_file_name
        if local_archive.exists(): local_archive.unlink()
        print("✅ 运行结束", flush=True)


if __name__ == "__main__":
    main()
