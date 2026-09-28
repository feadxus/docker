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
    # 在 rclone 配置文件中使用的远程名称
    RCLONE_REMOTE = "FEADXUS-Google-Drive"
    # 挂载此目录
    RCLONE_REMOTE_PATH = f"{RCLONE_REMOTE}:/Command/"
CONFIG = Config()

# =============== 📦 安装类 ===============
# 安装 pip 依赖库
pip_packages = [
    "google-auth-oauthlib",
    "google-api-python-client"
]
# ⚠️ 注意:不能使用 sys.executable,直接调用系统环境的 pip3
subprocess.check_call(["pip3", "install", *pip_packages])

# 下载并安装特定版本的 age (v1.3.2)
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

# 安装 Google Drive rclone 与 skopeo 工具
subprocess.run(
    "curl -fsSL https://rclone.org/install.sh | sudo bash",
    shell=True,
    executable="/bin/bash",
    check=True,
)
# 设置 rclone 配置
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

# 挂载网盘
def mount_remote_command() -> None:
    mount_point = pathlib.Path("/tmp/command")
    mount_point.mkdir(parents=True, exist_ok=True)
    cmd = (
        f"rclone mount {Config.RCLONE_REMOTE_PATH} {mount_point} "
        "--daemon "
        "--vfs-cache-mode writes "
        "--allow-other "
        "--log-level INFO"
    )
    try:
        run(cmd)
        print(f"✅ 已挂载 {Config.RCLONE_REMOTE_PATH} → {mount_point}")
    except RuntimeError as e:
        raise RuntimeError(f"挂载失败: {e}")


# 执行每个模块
def main() -> None:
    try:
        # 设置 rclone
        print("[1/4] 设置 rclone 配置...")
        setup_rclone_config()

        # 挂载网盘
        print("[2/4] 挂载 remote:/command 到 /tmp/command ...")
        mount_remote_command()

    except Exception as e:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now_str}] ❌ 错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
