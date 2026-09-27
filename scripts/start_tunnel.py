import os
import signal
import subprocess
import sys

# ============================================================
# 配置
# ============================================================

CONTAINER_NAME = "test-nginx"
IMAGE = "nginx:alpine"

HOST_PORT = 8080
CONTAINER_PORT = 80

TUNNEL_TIMEOUT = 3300  # 55 分钟

run_id = os.environ.get("GITHUB_RUN_ID", "local")
SUBDOMAIN = f"test-{run_id}"

PUBLIC_URL = f"https://{SUBDOMAIN}.loca.lt"

# ============================================================
# 全局资源
# ============================================================

container_id = None
tunnel_proc = None

# ============================================================
# Docker
# ============================================================

def start_docker():
    global container_id

    print("🐳 启动 Nginx 容器...", flush=True)

    result = subprocess.run(
        [
            "docker", "run", "-d",
            "-p", f"{HOST_PORT}:{CONTAINER_PORT}",
            "--name", CONTAINER_NAME,
            IMAGE,
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    container_id = result.stdout.strip()

    print(
        f"🐳 Docker 容器已启动：{container_id}",
        flush=True,
    )

def stop_docker():
    global container_id

    if not container_id:
        return

    print("🛑 停止 Docker 容器...", flush=True)

    subprocess.run(
        ["docker", "stop", container_id],
        check=False,
    )

    container_id = None

# ============================================================
# Localtunnel
# ============================================================

def install_localtunnel():
    print("📦 安装 Localtunnel...", flush=True)

    subprocess.run(
        ["npm", "install", "-g", "localtunnel"],
        check=True,
    )

def start_tunnel():
    global tunnel_proc

    print(
        f"🌐 准备启动 Localtunnel：{SUBDOMAIN}",
        flush=True,
    )

    tunnel_proc = subprocess.Popen(
        [
            "lt",
            "--port", str(HOST_PORT),
            "--subdomain", SUBDOMAIN,
        ],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    print(f"🌍 公网地址：{PUBLIC_URL}", flush=True)

def stop_tunnel():
    global tunnel_proc

    if not tunnel_proc:
        return

    if tunnel_proc.poll() is None:
        print("🛑 停止 Localtunnel...", flush=True)

        tunnel_proc.terminate()

        try:
            tunnel_proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            print("⚠️ Localtunnel 未正常退出，强制结束", flush=True)
            tunnel_proc.kill()

    tunnel_proc = None

# ============================================================
# 清理
# ============================================================

def cleanup():
    print("🧹 开始清理资源...", flush=True)

    # 先关闭 Tunnel
    stop_tunnel()

    # 再停止 Docker
    stop_docker()

    print("✅ 清理完成", flush=True)

# ============================================================
# 信号处理
# ============================================================

def handle_signal(signum, frame):
    print(f"\n⚠️ 收到信号：{signum}", flush=True)

    cleanup()

    sys.exit(0)


signal.signal(signal.SIGTERM, handle_signal)
signal.signal(signal.SIGINT, handle_signal)

# ============================================================
# 主流程
# ============================================================

def main():
    try:
        # 1. 启动 Docker
        start_docker()

        # 2. 安装 Localtunnel
        install_localtunnel()

        # 3. 启动 Tunnel
        start_tunnel()

        print(
            "⏳ 第一个 Job 将持续运行，"
            "等待第二个 Job 进行公网访问测试...",
            flush=True,
        )

        # 4. 等待 Tunnel
        try:
            tunnel_proc.wait(timeout=TUNNEL_TIMEOUT)

        except subprocess.TimeoutExpired:
            print("⏰ 运行时间达到 55 分钟", flush=True)

    except Exception as e:
        print(f"❌ 启动失败：{e}", flush=True)
        raise

    finally:
        # 无论正常退出还是异常，都清理
        cleanup()

# ============================================================
# Entry Point
# ============================================================

if __name__ == "__main__":
    main()
