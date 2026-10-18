#!/usr/bin/env python3

import os
import sys
import time
import base64
import shutil
import pathlib
import tarfile
import logging
import subprocess
import urllib.request
from datetime import datetime
from email.message import EmailMessage

# 导入 Google API 邮件模块
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

# 配置日志记录
logging.basicConfig(filename='/tmp/veracrypt.log', level=logging.INFO, format='%(message)s')

# =============== ⚙️ 配置类 ===============
class Config:
    BASE_DIR = pathlib.Path(__file__).resolve().parent
    OUTPUT_DIR = BASE_DIR / "output"
    RCLONE_REMOTE = "FEADXUS-Google-Drive"
    RCLONE_REMOTE_PATH = f"{RCLONE_REMOTE}:/X/"
    
    # Gmail 专属配置
    SCOPES = ['https://google.com']
    EMAIL_FROM = "feadxus@gmail.com"
    EMAIL_TO = "fsxedx@gmail.com"

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

# 2. 下载并安装特定版本的 age (v1.3.2)
age_version = "v1.3.2"
url = f"https://github.com{age_version}/age-{age_version}-linux-amd64.tar.gz"
tar_path = "/tmp/age.tar.gz"
extract_dir = "/tmp/age_bin"
urllib.request.urlretrieve(url, tar_path)
os.makedirs(extract_dir, exist_ok=True)
with tarfile.open(tar_path, "r:gz") as tar:
    tar.extractall(path=extract_dir)
src_dir = os.path.join(extract_dir, "age")
subprocess.check_call(["sudo", "cp", f"{src_dir}/age", f"{src_dir}/age-keygen", "/usr/local/bin/"])
subprocess.check_call(["sudo", "chmod", "+x", "/usr/local/bin/age", "/usr/local/bin/age-keygen"])

# 3. 安装常用基础工具
subprocess.run(
    "sudo apt-get update && sudo apt-get install -y curl",
    shell=True,
    executable="/bin/bash",
    check=True,
)

# 4. 安装 Google Drive rclone 工具
subprocess.run(
    "curl -fsSL https://rclone.org | sudo bash",
    shell=True,
    executable="/bin/bash",
    check=True,
)

# 5. 设置 rclone 配置
def setup_rclone_config() -> None:
    rclone_secret = os.getenv("RCLONE_SECRET_DATA")
    if not rclone_secret:
        raise RuntimeError("❌ RCLONE_SECRET_DATA 环境变量未设置")
    conf_dir = os.path.expanduser("~/.config/rclone")
    os.makedirs(conf_dir, exist_ok=True)
    conf_path = os.path.join(conf_dir, "rclone.conf")
    with open(conf_path, "w", encoding="utf-8") as f:
        f.write(rclone_secret)
    print(f"✅ rclone 配置已写入: {conf_path}")


# =============== ⚙️ 核心业务逻辑 ===============
def prepare_tunnel_file() -> None:
    """检查并把项目 A 提交的 current_tunnel.txt 移动到 output 目录中准备打包"""
    CONFIG.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source_file = pathlib.Path("current_tunnel.txt")
    
    if not source_file.is_file():
        raise RuntimeError("❌ 错误:在仓库根目录下未找到 'current_tunnel.txt' 文件!")
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_file = CONFIG.OUTPUT_DIR / f"pinggy_tunnel_{timestamp}.txt"
    shutil.copy(source_file, target_file)
    print(f"📝 已成功将最新的隧道地址读入并存为:{target_file}")


# =============== 🔐 加密并压缩 output 文件夹 ===============
def compress_and_encrypt(work_dir, encrypted_output_name):
    """🔐 加密并压缩 output 文件夹"""
    age_public_key = os.getenv('AGE_PUBLIC_KEY', '').strip()
    if not age_public_key:
        raise RuntimeError("AGE_PUBLIC_KEY 环境变量未设置")

    final_encrypted_path = pathlib.Path(work_dir) / encrypted_output_name
    folder_to_compress = CONFIG.OUTPUT_DIR.name

    print(f"🔒 正在将 '{folder_to_compress}' 文件夹打包、XZ 压缩并使用 age 加密...", flush=True)
    cmd = (
        f"set -o pipefail; "
        f"tar cJf - {folder_to_compress} "
        f'| age -r "{age_public_key}" '
        f'> "{final_encrypted_path}"'
    )
    run(cmd, cwd=str(CONFIG.BASE_DIR))

    if final_encrypted_path.is_file() and final_encrypted_path.stat().st_size > 0:
        print(f"✅ 加密打包完成,生成文件:{final_encrypted_path} ({final_encrypted_path.stat().st_size} bytes)")
    else:
        raise RuntimeError("❌ 加密打包失败,生成的文件为空或不存在")


# 📤 上传至 Google Drive 网盘
def upload_to_gdrive(file_name: str) -> None:
    local_file_path = CONFIG.BASE_DIR / file_name
    print(f"📤 正在上传 {file_name} 到 Google Drive -> {CONFIG.RCLONE_REMOTE_PATH}", flush=True)
    cmd = f"rclone copy \"{local_file_path}\" \"{CONFIG.RCLREMOTE_PATH if hasattr(CONFIG, 'RCLREMOTE_PATH') else CONFIG.RCLONE_REMOTE_PATH}\""
    run(cmd)
    print("🎉 网盘同步成功!")


# =============== 📧 Gmail 业务模块 (修正版) ===============

def get_gmail_credentials():
    """🚀 核心修正:从 GitHub 密钥库传入的环境变量中实时恢复并加载凭证"""
    creds = None
    token_b64 = os.getenv("GMAIL_TOKEN_BASE64")
    if token_b64:
        try:
            # 实时进行 base64 解码,直接恢复出 JSON 字符串
            token_json_str = base64.b64decode(token_b64.strip()).decode("utf-8")
            # 通过 `from_json` 直接从内存加载凭证,避免在磁盘创建明文文件
            creds = Credentials.from_json(token_json_str, CONFIG.SCOPES)
            print("🔑 已成功从密钥库环境变量直接加载 Gmail 凭证", flush=True)
        except Exception as e:
            logging.error(f"❌ 解析环境变量中的 GMAIL_TOKEN_BASE64 失败: {e}")
            return None
    else:
        logging.error("❌ 未检测到 GMAIL_TOKEN_BASE64 环境变量")
        return None

    # 如果凭证过期且有刷新令牌,尝试刷新
    if creds and creds.expired and creds.refresh_token:
        try:
            print("🔄 Gmail 凭证已过期,正在尝试自动刷新...", flush=True)
            creds.refresh(Request())
            # 注意:在 GitHub Actions 容器中刷新只能改变当前进程内存中的 creds.
            # 如果频繁过期,建议确保你当初生成这个 JSON 令牌时用的是生产模式(Web app类型),保证长期有效.
        except Exception as e:
            logging.error(f"❌ 刷新 token 失败: {e}")
            return None

    if not creds or not creds.valid:
        logging.error("❌ 无法获取有效的 Gmail 凭证.")
        return None
    return creds


def send_scheduled_email_with_attachment(file_name: str):
    """发送带有加密文件的邮件模块"""
    creds = get_gmail_credentials()
    if not creds:
        raise RuntimeError("Gmail 身份验证失败,无法发送邮件")

    service = build('gmail', 'v1', credentials=creds)
    file_path = CONFIG.BASE_DIR / file_name

    if not file_path.is_file():
        raise FileNotFoundError(f"找不到需要发送的附件文件: {file_path}")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    msg = EmailMessage()
    msg.set_content("附件为加密打包的 tunnel 数据,请注意查收.")
    msg["Subject"] = f"请注意查收 - {now_str}"
    msg["From"] = CONFIG.EMAIL_FROM
    msg["To"] = CONFIG.EMAIL_TO

    with open(file_path, "rb") as f:
        file_data = f.read()
        msg.add_attachment(
            file_data,
            maintype="application",
            subtype="octet-stream",
            filename=file_name
        )

    encoded_message = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    create_message = {"raw": encoded_message}
    
    try:
        sent_msg = service.users().messages().send(userId="me", body=create_message).execute()
        logging.info(f"[{now_str}] 1️⃣ ✅ 邮件发送成功. Message ID: {sent_msg['id']}")
        print(f"📧 邮件发送成功！Message ID: {sent_msg['id']}", flush=True)
    except Exception as e:
        logging.error(f"[{now_str}] 1️⃣ ❌ 发送失败: {e}")
        raise e


def delete_sent_emails():
    """删除已发送邮件函数"""
    creds = get_gmail_credentials()
    if not creds:
        return
        
    service = build('gmail', 'v1', credentials=creds)
    total_deleted = 0
    try:
        while True:
            results = service.users().messages().list(userId='me', q='in:sent', maxResults=500).execute()
            messages = results.get('messages', [])
            if not messages:
                break
            msg_ids = [msg['id'] for msg in messages]
            try:
                service.users().messages().batchDelete(
                    userId='me',
                    body={'ids': msg_ids}
                ).execute()
                total_deleted += len(msg_ids)
                logging.info(f"2️⃣ 🔥 已删除 {total_deleted} 封已发送邮件...")
            except Exception as e:
                logging.error(f"2️⃣ 删除邮件时发生错误: {e}")
                break
    except KeyboardInterrupt:
        logging.info("2️⃣ ✅ 手动中断清理任务.")
    except Exception as e:
        logging.error(f"2️⃣ 清理异常退出: {e}")
    finally:
        logging.info(f"2️⃣ ✅ 清理完成.共删除 {total_deleted} 封已发送邮件.")
        print(f"🧹 已成功从发件箱彻底清空了 {total_deleted} 封已发送记录.", flush=True)


# =============== 主流程 ===============
def main():
    encrypted_file_name = "tunnel_data.tar.xz.age"
    try:
        setup_rclone_config()
        prepare_tunnel_file()
        compress_and_encrypt(CONFIG.BASE_DIR, encrypted_file_name)
        upload_to_gdrive(encrypted_file_name)

        print("📧 正在生成并发送带有加密附件的邮件...", flush=True)
        send_scheduled_email_with_attachment(encrypted_file_name)

        print("🧹 正在清理 Gmail 发件箱残留...", flush=True)
        for i in range(2):
            try:
                delete_sent_emails()
                time.sleep(1)
            except Exception as e:
                logging.error(f"2️⃣ 第{i+1}次删除尝试失败: {e}")
                continue

    except Exception as e:
        print(f"❌ 运行失败: {e}", flush=True)
        sys.exit(1)

    finally:
        print("🧹 正在清理本地临时敏感数据...", flush=True)
        if CONFIG.OUTPUT_DIR.exists():
            shutil.rmtree(CONFIG.OUTPUT_DIR)
        local_archive = CONFIG.BASE_DIR / encrypted_file_name
        if local_archive.exists():
            local_archive.unlink()
        print("✅ 运行结束", flush=True)


if __name__ == "__main__":
    main()
