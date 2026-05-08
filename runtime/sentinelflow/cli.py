from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = PACKAGE_DIR.parent
PROJECT_ROOT = RUNTIME_DIR.parent
WEBUI_DIR = PROJECT_ROOT / "webui"
SPA_SERVER_SCRIPT = PROJECT_ROOT / "scripts" / "serve_webui.py"


def _product_name() -> str:
    return (os.getenv("SENTINELFLOW_PRODUCT_NAME") or "SentinelFlow").strip() or "SentinelFlow"


def _console_title() -> str:
    value = os.getenv("SENTINELFLOW_CONSOLE_TITLE") or f"{_product_name()} Platform"
    return value.strip() or f"{_product_name()} Platform"


def _workflow_engine_label() -> str:
    value = os.getenv("SENTINELFLOW_WORKFLOW_ENGINE_LABEL") or "SentinelFlowWorkflowRunner"
    return value.strip() or "SentinelFlowWorkflowRunner"


def _product_tag() -> str:
    return f"[{_product_name()}]"


def _require_pnpm() -> str:
    pnpm = shutil.which("pnpm")
    if not pnpm:
        raise SystemExit(f"pnpm 未安装，无法启动 {_product_name()} WebUI。")
    return pnpm


def _require_node() -> str:
    node = shutil.which("node")
    if not node:
        raise SystemExit(f"node 未安装，无法启动 {_product_name()} WebUI。")
    return node


def _local_vite_entry() -> Path:
    vite_entry = WEBUI_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_entry.is_file():
        raise SystemExit(f"未找到本地 Vite 可执行入口：{vite_entry}。请先在 WebUI 目录执行 pnpm install。")
    return vite_entry


def _run(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> int:
    process = subprocess.Popen(
        command,
        cwd=str(cwd),
        env=env,
        start_new_session=True,
    )
    try:
        return process.wait()
    except KeyboardInterrupt:
        _interrupt_process_group(process)
        return 0


def _spawn(command: list[str], cwd: Path, env: dict[str, str] | None = None) -> subprocess.Popen:
    return subprocess.Popen(command, cwd=str(cwd), env=env)


def _api_health_url(api_base_url: str) -> str:
    return f"{api_base_url.rstrip('/')}/api/sentinelflow/health"


def _wait_for_backend_health(api_base_url: str, process: subprocess.Popen, timeout: float = 60.0) -> bool:
    health_url = _api_health_url(api_base_url)
    deadline = time.monotonic() + timeout
    last_error = ""
    print(f"{_product_tag()} waiting for backend health -> {health_url}")
    while time.monotonic() < deadline:
        exit_code = process.poll()
        if exit_code is not None:
            print(f"{_product_tag()} backend exited before health check passed (exit code {exit_code}).")
            return False
        try:
            with urllib.request.urlopen(health_url, timeout=1.0) as response:
                if 200 <= response.status < 300:
                    print(f"{_product_tag()} backend health check passed.")
                    return True
                last_error = f"HTTP {response.status}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        time.sleep(0.5)
    print(f"{_product_tag()} backend health check timed out after {timeout:.0f}s: {last_error or 'unknown error'}")
    return False


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _interrupt_process_group(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGINT)
        process.wait(timeout=5)
    except (ProcessLookupError, PermissionError):
        return
    except subprocess.TimeoutExpired:
        _stop_process(process)


def backend_command(api_host: str, api_port: int) -> tuple[list[str], dict[str, str]]:
    env = os.environ.copy()
    env["SENTINELFLOW_API_HOST"] = api_host
    env["SENTINELFLOW_API_PORT"] = str(api_port)
    env.setdefault("SENTINELFLOW_PRODUCT_NAME", _product_name())
    env.setdefault("SENTINELFLOW_CONSOLE_TITLE", _console_title())
    env.setdefault("SENTINELFLOW_WORKFLOW_ENGINE_LABEL", _workflow_engine_label())
    return [sys.executable, "-m", "sentinelflow.api.serve"], env


def webui_dev_command(api_base_url: str, host: str, port: int) -> tuple[list[str], dict[str, str]]:
    env = os.environ.copy()
    env["VITE_SENTINELFLOW_API_BASE_URL"] = api_base_url
    env.setdefault("VITE_PRODUCT_NAME", _product_name())
    env.setdefault("VITE_CONSOLE_TITLE", _console_title())
    env.setdefault("VITE_WORKFLOW_ENGINE_LABEL", _workflow_engine_label())
    return [_require_node(), str(_local_vite_entry()), "--host", host, "--port", str(port)], env


def webui_build_command(api_base_url: str) -> tuple[list[str], dict[str, str]]:
    env = os.environ.copy()
    env["VITE_SENTINELFLOW_API_BASE_URL"] = api_base_url
    env.setdefault("VITE_PRODUCT_NAME", _product_name())
    env.setdefault("VITE_CONSOLE_TITLE", _console_title())
    env.setdefault("VITE_WORKFLOW_ENGINE_LABEL", _workflow_engine_label())
    return [_require_pnpm(), "build"], env


def webui_serve_command(host: str, port: int) -> tuple[list[str], dict[str, str]]:
    if not SPA_SERVER_SCRIPT.exists():
        raise SystemExit(f"未找到静态 WebUI 服务脚本：{SPA_SERVER_SCRIPT}")
    dist_dir = WEBUI_DIR / "dist"
    return [
        sys.executable,
        str(SPA_SERVER_SCRIPT),
        "--directory",
        str(dist_dir),
        "--host",
        host,
        "--port",
        str(port),
    ], os.environ.copy()


def command_backend(args: argparse.Namespace) -> int:
    command, env = backend_command(args.api_host, args.api_port)
    return _run(command, RUNTIME_DIR, env=env)


def command_webui_dev(args: argparse.Namespace) -> int:
    command, env = webui_dev_command(args.api_base_url, args.webui_host, args.webui_port)
    return _run(command, WEBUI_DIR, env=env)


def command_webui_build(args: argparse.Namespace) -> int:
    command, env = webui_build_command(args.api_base_url)
    return _run(command, WEBUI_DIR, env=env)


def command_webui_serve(args: argparse.Namespace) -> int:
    command, env = webui_serve_command(args.webui_host, args.webui_port)
    return _run(command, PROJECT_ROOT, env=env)


def command_dev(args: argparse.Namespace) -> int:
    backend_cmd, backend_env = backend_command(args.api_host, args.api_port)
    frontend_cmd, frontend_env = webui_dev_command(args.api_base_url, args.webui_host, args.webui_port)

    print(f"{_product_tag()} backend -> http://{args.api_host}:{args.api_port}")
    print(f"{_product_tag()} webui   -> http://{args.webui_host}:{args.webui_port}")

    backend = _spawn(backend_cmd, RUNTIME_DIR, env=backend_env)
    frontend: subprocess.Popen | None = None
    processes = [backend]

    def _shutdown() -> None:
        for process in reversed(processes):
            _stop_process(process)

    def _handle_signal(signum, frame) -> None:  # type: ignore[override]
        del frame
        print(f"\n{_product_tag()} 收到信号 {signum}，正在关闭开发服务...")
        _shutdown()
        raise SystemExit(0)

    original_sigint = signal.signal(signal.SIGINT, _handle_signal)
    original_sigterm = signal.signal(signal.SIGTERM, _handle_signal)
    try:
        if not _wait_for_backend_health(args.api_base_url, backend):
            _shutdown()
            return backend.poll() or 1
        frontend = _spawn(frontend_cmd, WEBUI_DIR, env=frontend_env)
        processes.append(frontend)
        while True:
            backend_code = backend.poll()
            frontend_code = frontend.poll() if frontend else None
            if backend_code is not None or frontend_code is not None:
                _shutdown()
                return backend_code or frontend_code or 0
            time.sleep(0.5)
    finally:
        signal.signal(signal.SIGINT, original_sigint)
        signal.signal(signal.SIGTERM, original_sigterm)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"{_product_name()} unified platform launcher")
    parser.set_defaults(handler=None)

    parser.add_argument(
        "--api-base-url",
        default="http://127.0.0.1:8001",
        help=f"{_product_name()} API base URL exposed to the frontend",
    )
    parser.add_argument("--api-host", default="127.0.0.1", help=f"{_product_name()} backend host")
    parser.add_argument("--api-port", type=int, default=8001, help=f"{_product_name()} backend port")
    parser.add_argument("--webui-host", default="127.0.0.1", help=f"{_product_name()} WebUI host")
    parser.add_argument("--webui-port", type=int, default=5173, help=f"{_product_name()} WebUI port")

    subparsers = parser.add_subparsers(dest="command")

    backend_parser = subparsers.add_parser("backend", help=f"Start the {_product_name()} backend API")
    backend_parser.set_defaults(handler=command_backend)

    webui_dev_parser = subparsers.add_parser("webui-dev", help=f"Start the {_product_name()} WebUI dev server")
    webui_dev_parser.set_defaults(handler=command_webui_dev)

    webui_build_parser = subparsers.add_parser("webui-build", help=f"Build the {_product_name()} WebUI bundle")
    webui_build_parser.set_defaults(handler=command_webui_build)

    webui_serve_parser = subparsers.add_parser("webui-serve", help=f"Serve the built {_product_name()} WebUI bundle")
    webui_serve_parser.set_defaults(handler=command_webui_serve)

    dev_parser = subparsers.add_parser("dev", help="Start backend and WebUI together for local development")
    dev_parser.set_defaults(handler=command_dev)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.handler is None:
        parser.print_help()
        return 0
    return int(args.handler(args) or 0)
