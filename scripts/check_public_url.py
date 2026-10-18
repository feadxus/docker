#!/usr/bin/env python3

import os
import sys
import time
import shutil
import pathlib
import tarfile
import subprocess
import urllib.request
from datetime import datetime


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


# =============== ⚙️ 配置类 ===============
class Config:
    BASE_DIR = pathlib.Path(__file__).resolve().parent
    # 保持将需要打包的文件输出到 output 文件夹的结构
    OUTPUT_DIR = BASE_DIR / "output"
    RCLONE_REMOTE = "FEADXUS-Google-Drive"
    RCLONE_REMOTE_PATH = f"{RCLONE_REMOTE}:/X/"
CONFIG = Config()


# =============== 📦 极简安装类 ===============
print("📦 开始环境初始化...", flush=True)

# 1. 安装 pip 依赖库
pip_packages = [
    "google-auth-oauthlib",
    "google-api-python-client"
]
subprocess.check_call(["pip3", "install", *pip_packages])

# 2. 下载并安装特定版本的 age (v1.3.2)
age_version = "v1.3.2"
url = f"https://github.com/FiloSottile/age/releases/download/{age_version}/age-{age_version}-linux-amd64.tar.gz"
tar_path = "/tmp/age.tar.gz"
extract_dir = "/tmp/age_bin"
urllib.request.urlretrieve(url, tar_path)
os.makedirs(extract_dir, exist_ok=True)
with tarfile.open(tar_path, "r:gz") as tar:
    tar.extractall(path=extract_dir)
src_dir = os.path.join(extract_dir, "age")
subprocess.check_call(["sudo", "cp", f"{src_dir}/age", f"{src_dir}/age-keygen", "/usr/local/bin/"])
subprocess.check_call(["sudo", "chmod", "+x", "/usr/local/bin/age", "/usr/local/bin/age-keygen"])

# 3. 安装常用基础工具(删除了无用的 skopeo、wget)
subprocess.run(
    "sudo apt-get update && sudo apt-get install -y curl",
    shell=True,
    executable="/bin/bash",
    check=True,
)

# 4. 安装 Google Drive rclone 工具(彻底移除了 rust, cargo, monolith 等大体量网页下载工具)
subprocess.run(
    "curl -fsSL https://rclone.org/install.sh | sudo bash",
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

# ============================================================
# ⚙️ 核心业务逻辑移除了 download_page,改为处理本地文件
# ============================================================

def prepare_tunnel_file() -> None:
    """检查并把项目 A 提交的 current_tunnel.txt 移动到 output 目录中准备打包"""
    Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    # 这里的名字对应项目 A 提交上来的本地文件
    source_file = pathlib.Path("current_tunnel.txt")
    
    if not source_file.is_file():
        raise RuntimeError("❌ 错误:在仓库根目录下未找到 'current_tunnel.txt' 文件!请确保项目 A 已成功运行并提交该文件.")
    
    # 给输出文件加上时间戳,和您原本的命名风格保持一致
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_file = Config.OUTPUT_DIR / f"pinggy_tunnel_{timestamp}.txt"
    
    # 复制到 output 文件夹
    shutil.copy(source_file, target_file)
    print(f"📝 已成功将最新的隧道地址读入并存为:{target_file}")


# 🔐 加密并压缩 output 文件夹
def compress_and_encrypt(work_dir, encrypted_output_name):
    age_public_key = os.getenv('AGE_PUBLIC_KEY', '').strip()
    if not age_public_key:
        raise RuntimeError("AGE_PUBLIC_KEY 环境变量未设置")

    final_encrypted_path = pathlib.Path(work_dir) / encrypted_output_name
    folder_to_compress = CONFIG.OUTPUT_DIR.name  # "output"

    print(
        f"🔒 正在将 '{folder_to_compress}' 文件夹打包、XZ 压缩并使用 age 加密...",
        flush=True
    )
    cmd = (
        f"set -o pipefail; "
        f"tar cJf - {folder_to_compress} "
        f'| age -r "{age_public_key}" '
        f'> "{final_encrypted_path}"'
    )
    run(cmd, cwd=str(CONFIG.BASE_DIR))

    if final_encrypted_path.is_file() and final_encrypted_path.stat().st_size > 0:
        print(
            f"✅ 加密打包完成，生成文件：{final_encrypted_path} "
            f"({final_encrypted_path.stat().st_size} bytes)"
        )
    else:
        raise RuntimeError("❌ 加密打包失败，生成的文件为空或不存在")

# 📤 上传至 Google Drive 网盘
def upload_to_gdrive(file_name: str) -> None:
    local_file_path = CONFIG.BASE_DIR / file_name
    print(f"📤 正在上传 {file_name} 到 Google Drive -> {CONFIG.RCLONE_REMOTE_PATH}", flush=True)
    
    cmd = f"rclone copy \"{local_file_path}\" \"{CONFIG.RCLONE_REMOTE_PATH}\""
    run(cmd)
    print("🎉 网盘同步成功!")


# ============================================================
# 主流程
# ============================================================
def main():
    encrypted_file_name = "tunnel_data.tar.xz.age"
    try:
        # 1. 配置网盘凭证
        setup_rclone_config()

        # 2. 提取本地隧道地址
        prepare_tunnel_file()

        # 3. 使用 XZ 压缩并通过 age 加密
        compress_and_encrypt(CONFIG.BASE_DIR, encrypted_file_name)

        # 4. 上传至 Google Drive
        upload_to_gdrive(encrypted_file_name)

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


# ============================================================
# Entry Point
# ============================================================
if __name__ == "__main__":
    main()
