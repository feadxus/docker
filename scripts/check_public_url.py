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
    OUTPUT_DIR = BASE_DIR / "output"
    RCLONE_REMOTE = "FEADXUS-Google-Drive"
    RCLONE_REMOTE_PATH = f"{RCLONE_REMOTE}:/X/"
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


# 安装 skopeo wget 工具
subprocess.run(
    "sudo apt-get update && sudo apt-get install -y skopeo wget curl",
    shell=True,
    executable="/bin/bash",
    check=True,
)


# 安装 Rust 工具
subprocess.run(
    "curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y && "
    "source $HOME/.cargo/env && "
    "cargo install monolith",
    shell=True,
    executable="/bin/bash",
    check=True,
)


# 安装 monolith 工具
subprocess.run(
    "curl -L https://github.com/Y2Z/monolith/releases/download/v2.10.1/monolith-gnu-linux-x86_64 -o /usr/local/bin/monolith && "
    "chmod +x /usr/local/bin/monolith",
    shell=True,
    executable="/bin/bash",
    check=True,
)


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

# 下载网页
def download_page(url: str) -> pathlib.Path:
    """
    下载 Localtunnel 返回的原始页面,包括提醒页,
    并使用 monolith 处理为最终 HTML 文件.
    Args:
        url: Localtunnel 地址
    Returns:
        pathlib.Path: 保存的 HTML 文件路径
    Raises:
        RuntimeError: 下载失败或文件验证失败
    """
    Config.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = (
        Config.OUTPUT_DIR
        / f"localtunnel_reminder_{timestamp}.html"
    )
    raw_html_file = (
        Config.OUTPUT_DIR
        / f".localtunnel_raw_{timestamp}.html"
    )
    user_agent = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
    timeout = 30
    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            # 清理之前可能残留的文件
            for file_path in (raw_html_file, output_file):
                if file_path.exists():
                    file_path.unlink()
            # 注意:
            # 这里故意不添加 Bypass-Tunnel-Reminder Header,
            # 因此 Localtunnel 应该返回提醒页.
            curl_cmd = [
                "curl",
                "-L",
                "--silent",
                "--show-error",
                "--max-time",
                str(timeout),
                "-A",
                user_agent,
                "-o",
                str(raw_html_file),
                url,
            ]
            curl_result = subprocess.run(
                curl_cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 10,
                check=False,
            )
            # 不使用 --fail,所以即使 HTTP 状态码是 511,
            # curl 仍然会把返回内容保存到 raw_html_file.
            if curl_result.returncode != 0:
                error_message = (
                    curl_result.stderr.strip()
                    or curl_result.stdout.strip()
                    or f"curl exited with code {curl_result.returncode}"
                )
                raise RuntimeError(error_message)
            if not raw_html_file.is_file():
                raise RuntimeError(
                    f"Raw HTML file not generated: {raw_html_file}"
                )
            if raw_html_file.stat().st_size == 0:
                raise RuntimeError("Downloaded page is empty")
            # 使用 monolith 处理本地提醒页
            monolith_cmd = [
                "monolith",
                "--timeout",
                str(timeout),
                "--user-agent",
                user_agent,
                "-o",
                str(output_file),
                str(raw_html_file),
            ]
            monolith_result = subprocess.run(
                monolith_cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 10,
                check=False,
            )
            if monolith_result.returncode != 0:
                error_message = (
                    monolith_result.stderr.strip()
                    or monolith_result.stdout.strip()
                    or f"monolith exited with code "
                       f"{monolith_result.returncode}"
                )
                raise RuntimeError(error_message)
            if not output_file.is_file():
                raise RuntimeError(
                    f"Output file not generated: {output_file}"
                )
            if output_file.stat().st_size == 0:
                raise RuntimeError("Output file is empty")
            return output_file
        except subprocess.TimeoutExpired:
            if attempt < max_retries:
                time.sleep(3)
                continue
            raise RuntimeError(
                "Downloading Localtunnel reminder page timed out"
            )
        except Exception as e:
            if attempt < max_retries:
                time.sleep(2)
                continue
            raise RuntimeError(
                f"Failed to download Localtunnel reminder page: {e}"
            ) from e
        finally:
            # 最终只保留 monolith 生成的文件
            if raw_html_file.exists():
                try:
                    raw_html_file.unlink()
                except OSError:
                    pass
    raise RuntimeError("Unknown error")

def get_tunnel_url() -> str:
    run_id = os.getenv("GITHUB_RUN_ID")

    if not run_id:
        raise RuntimeError("GITHUB_RUN_ID 环境变量未设置")
    url = f"https://test-{run_id}.loca.lt"
    print(f"Localtunnel 地址:{url}")
    return url


# 🔐 加密压缩下载的页面
def compress_and_encrypt(work_dir, output_file):
    age_public_key = os.getenv('AGE_PUBLIC_KEY', '').strip()
    if not age_public_key:
        raise RuntimeError("AGE_PUBLIC_KEY 环境变量未设置")
    output_file = pathlib.Path(work_dir) / output_file
    folder_to_compress = os.path.basename(CONFIG.OUTPUT_DIR)
    cmd = (
        f"tar -cJf - -C '{work_dir}' '{folder_to_compress}' | "
        f"age -r '{age_public_key}' > '{output_file}'"
    )
    result = subprocess.run(cmd, shell=True, check=True, cwd=work_dir)
    print(f"🔒 压缩加密完成! 生成文件: {output_file}")
    return output_file


# ☁️ 保存至 Google Drive 网盘
def upload_to_drive(local_file: pathlib.Path, remote_path: str = None) -> None:
    if remote_path is None:
        remote_path = Config.RCLONE_REMOTE_PATH
    remote_path = remote_path.rstrip("/") + "/"
    if not shutil.which("rclone"):
        raise RuntimeError("❌ 未检测到 rclone,请先安装")
    if not local_file.exists():
        raise RuntimeError(f"❌ 本地文件不存在: {local_file}")
    print(f"📁 检查远程目录: {remote_path}")
    run(f"rclone mkdir '{remote_path}'")
    upload_cmd = f"rclone copy '{local_file}' '{remote_path}' --retries 3 -v"
    print(f"☁️ 上传中: {local_file.name} → {remote_path}")
    result = run(upload_cmd, capture=True)
    if result.stdout:
        print(result.stdout)
    print(f"🎉 上传成功!")


# 🚀 执行每个模块
def main() -> None:
    try:
        print("\n" + "="*50)
        print("开始执行下载-压缩-加密-上传流程")
        print("="*50 + "\n")

        # 设置 rclone
        print("[1/4] 设置 rclone 配置...")
        setup_rclone_config()

        # 下载网页
        print("\n[2/4] 等待并下载网页...")
        tunnel_url = get_tunnel_url()
        downloaded_file = download_page(tunnel_url)

        # 压缩 + 加密
        print("\n[3/4] 压缩并加密...")
        output_filename = f"feadxus-backup-{datetime.now().strftime('%Y-%m-%d')}.tar.xz.age"
        encrypted_file = compress_and_encrypt(CONFIG.BASE_DIR, output_filename)

        # 上传到 Google Drive
        print("\n[4/4] 上传到 Google Drive...")
        upload_to_drive(encrypted_file)

        print("\n" + "="*50)
        print("✅ 全流程完成!")
        print("="*50 + "\n")

    except Exception as e:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n[{now_str}] ❌ 错误: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
