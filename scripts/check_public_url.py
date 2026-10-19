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
    """
    ✨ 修正版本：从环境变量或文件读取隧道数据
    优先级：环境变量 TUNNEL_DATA > 本地文件 current_tunnel.txt
    """
    CONFIG.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 第一优先级：从环境变量读取
    tunnel_data = os.getenv("TUNNEL_DATA")
    
    if tunnel_data and tunnel_data.strip():
        print(f"✅ 从 TUNNEL_DATA 环境变量读取隧道数据", flush=True)
        target_file = CONFIG.OUTPUT_DIR / f"pinggy_tunnel_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(tunnel_data.strip())
        print(f"📝 隧道数据: {tunnel_data.strip()}", flush=True)
        return
    
    # 第二优先级：降级方案，尝试读取本地文件（用于本地测试）
    source_file = pathlib.Path("current_tunnel.txt")
    if source_file.is_file():
        print(f"⚠️  未检测到 TUNNEL_DATA 环境变量，从本地文件读取", flush=True)
        with open(source_file, "r", encoding="utf-8") as f:
            tunnel_data = f.read().strip()
        
        target_file = CONFIG.OUTPUT_DIR / f"pinggy_tunnel_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(tunnel_data)
        print(f"📝 隧道数据: {tunnel_data}", flush=True)
        return
    
    # 两个来源都没有数据
    raise RuntimeError(
        "❌ 错误：既未检测到 TUNNEL_DATA 环境变量，"
        "也未在仓库根目录找到 'current_tunnel.txt' 文件!"
    )


# =============== 🔐 加密并压缩 output 文件夹 ===============
def compress_and_encrypt(work_dir, encrypted_output_name):
    age_public_key = os.getenv('AGE_PUBLIC_KEY', '').strip()
    if not age_public_key:
        raise RuntimeError("❌ AGE_PUBLIC_KEY 环境变量未设置")

    final_encrypted_path = pathlib.Path(work_dir) / encrypted_output_name
    
    # 检查 output 目录是否存在且非空
    if not CONFIG.OUTPUT_DIR.exists() or not list(CONFIG.OUTPUT_DIR.iterdir()):
        raise RuntimeError(f"❌ 加密失败: {CONFIG.OUTPUT_DIR} 目录不存在或为空")
    
    cmd = f"set -o pipefail; tar cJf - {CONFIG.OUTPUT_DIR.name} | age -r '{age_public_key}' > '{final_encrypted_path}'"
    print(f"🔐 正在加密并压缩 {CONFIG.OUTPUT_DIR}...", flush=True)
    run(cmd, cwd=str(CONFIG.BASE_DIR))
    
    # 验证加密文件是否生成成功
    if not final_encrypted_path.exists():
        raise RuntimeError(f"❌ 加密失败: 未生成 {encrypted_output_name}")
    
    file_size = final_encrypted_path.stat().st_size
    print(f"✅ 加密完成，文件大小: {file_size / 1024:.2f} KB", flush=True)


# =============== 📤 上传至 Google Drive 网盘 ===============
def upload_to_gdrive(file_name: str) -> None:
    local_file_path = CONFIG.BASE_DIR / file_name
    
    if not local_file_path.exists():
        raise RuntimeError(f"❌ 上传失败: 本地文件 {file_name} 不存在")
    
    print(f"📤 开始上传 {file_name} 至 Google Drive...", flush=True)
    run(f"rclone copy \"{local_file_path}\" \"{CONFIG.RCLONE_REMOTE_PATH}\"")
    print("🎉 网盘同步成功!")


# =============== 📧 Gmail 业务模块 ===============

def execute_gmail_action(action_type="send", file_name=None):
    """
    💡 利用临时文件机制，完美复刻本地的 'from_authorized_user_file' 环境
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

    # 2. 核心黑魔法：在系统安全临时目录下创建一个绝对私密的文件
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as temp_token_file:
        temp_token_file.write(token_json_str)
        temp_token_file.flush()
        temp_token_path = temp_token_file.name

    try:
        # 3. 完美复刻本地的加载方式，让 Google 正常注入刷新器
        creds = Credentials.from_authorized_user_file(temp_token_path, CONFIG.SCOPES)

        # 4. 执行刷新（如果凭证过期，会自动用 refresh_token 请求新的）
        if creds and creds.expired and creds.refresh_token:
            print("🔄 凭证已过期，正在刷新...", flush=True)
            creds.refresh(Request())

        if not creds or not creds.valid:
            raise RuntimeError("❌ Google 凭证验证失败")

        service = build('gmail', 'v1', credentials=creds)

        # 5. 按照策略分流动作
        if action_type == "send":
            if not file_name:
                raise RuntimeError("❌ 发送邮件时必须指定文件名")
            
            file_path = CONFIG.BASE_DIR / file_name
            
            if not file_path.exists():
                raise RuntimeError(f"❌ 文件不存在: {file_path}")
            
            print(f"📧 正在组装邮件，附件: {file_name}...", flush=True)
            
            msg = EmailMessage()
            msg.set_content("Github Docker Tunnel Data")
            msg["Subject"] = f"Tunnel Data - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            msg["From"] = CONFIG.EMAIL_FROM
            msg["To"] = CONFIG.EMAIL_TO

            with open(file_path, "rb") as f:
                msg.add_attachment(f.read(), maintype="application", subtype="octet-stream", filename=file_name)

            encoded_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
            sent_msg = service.users().messages().send(userId="me", body={"raw": encoded_message}).execute()
            print(f"📧 邮件成功发送! Message ID: {sent_msg['id']}", flush=True)

        elif action_type == "delete":
            print(f"🧹 开始清理 Gmail 发件箱...", flush=True)
            total_deleted = 0
            
            while True:
                results = service.users().messages().list(userId='me', q='in:sent', maxResults=500).execute()
                messages = results.get('messages', [])
                
                if not messages:
                    break
                
                msg_ids = [m['id'] for m in messages]
                service.users().messages().batchDelete(userId='me', body={'ids': msg_ids}).execute()
                total_deleted += len(msg_ids)
                print(f"  - 已删除 {len(msg_ids)} 封邮件", flush=True)
            
            print(f"✅ 发件箱清理完成，共删除 {total_deleted} 封邮件", flush=True)

    except Exception as e:
        raise RuntimeError(f"❌ Gmail 操作失败: {e}")
    
    finally:
        # 6. 安全善后：不论成功或失败，必须抹除临时生成的明文 JSON 文件
        if os.path.exists(temp_token_path):
            try:
                os.unlink(temp_token_path)
                print("🔒 已安全删除临时凭证文件", flush=True)
            except Exception as e:
                logging.error(f"⚠️ 删除临时文件失败: {e}")


# =============== 主流程 ===============
def main():
    encrypted_file_name = "tunnel_data.tar.xz.age"
    
    try:
        print("=" * 60, flush=True)
        print("🚀 Job 2: 检查公网 URL 并处理隧道数据", flush=True)
        print("=" * 60, flush=True)
        
        # Step 1: 初始化环境
        print("\n[1/6] 初始化环境...", flush=True)
        initialize_environment()
        
        # Step 2: 配置 rclone
        print("\n[2/6] 配置 rclone...", flush=True)
        setup_rclone_config()
        
        # Step 3: 准备隧道文件（从环境变量或本地文件）
        print("\n[3/6] 准备隧道数据...", flush=True)
        prepare_tunnel_file()
        
        # Step 4: 加密并压缩
        print("\n[4/6] 加密并压缩数据...", flush=True)
        compress_and_encrypt(CONFIG.BASE_DIR, encrypted_file_name)
        
        # Step 5: 上传至 Google Drive
        print("\n[5/6] 上传至 Google Drive...", flush=True)
        upload_to_gdrive(encrypted_file_name)

        # Step 6: 发送邮件
        print("\n[6/6] 发送邮件并清理...", flush=True)
        print("📧 正在组装安全沙箱...", flush=True)
        execute_gmail_action(action_type="send", file_name=encrypted_file_name)

        # Step 7: 清理发件箱
        print("\n[7/7] 清理 Gmail 发件箱...", flush=True)
        for attempt in range(1, 3):
            try:
                execute_gmail_action(action_type="delete")
                break
            except Exception as e:
                if attempt < 2:
                    print(f"⚠️  清理失败（尝试 {attempt}/2），2秒后重试...", flush=True)
                    time.sleep(2)
                else:
                    logging.error(f"清理发件箱最终失败: {e}")
                    print(f"⚠️  清理失败: {e}", flush=True)

        print("\n" + "=" * 60, flush=True)
        print("✅ 全部流程执行完成！", flush=True)
        print("=" * 60, flush=True)

    except Exception as e:
        print(f"\n❌ 运行失败: {e}", flush=True)
        logging.error(f"运行失败: {e}")
        sys.exit(1)

    finally:
        print("\n🧹 正在清理本地临时敏感数据...", flush=True)
        if CONFIG.OUTPUT_DIR.exists():
            shutil.rmtree(CONFIG.OUTPUT_DIR)
            print("  ✓ 已删除 output 目录")
        
        local_archive = CONFIG.BASE_DIR / encrypted_file_name
        if local_archive.exists():
            local_archive.unlink()
            print("  ✓ 已删除加密文件")
        
        print("✅ 运行结束，环境已清理", flush=True)


if __name__ == "__main__":
    main()
