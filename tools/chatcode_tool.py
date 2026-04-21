import argparse
import csv
import json
import math
import os
import shlex
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def load_config(config_path: str | None) -> dict:
    resolved_path = config_path
    if not resolved_path:
        default_path = Path(__file__).with_name("config.json")
        if default_path.exists():
            resolved_path = str(default_path)
    if not resolved_path:
        return {}
    with open(resolved_path, "r", encoding="utf-8") as file:
        return json.load(file)


def get_value_or_default(value, default):
    return value if value is not None else default


def get_config_value(config: dict, *path, fallback_key: str | None = None, default=None):
    current = config
    for key in path:
        if not isinstance(current, dict) or key not in current:
            current = None
            break
        current = current[key]

    if current is not None:
        return current

    if fallback_key and isinstance(config, dict) and fallback_key in config:
        return config[fallback_key]

    return default


def shutil_which(command: str) -> str | None:
    paths = os.environ.get("PATH", "").split(os.pathsep)
    extensions = [""]
    if os.name == "nt":
        extensions.extend(os.environ.get("PATHEXT", ".EXE").split(os.pathsep))
    for base in paths:
        for ext in extensions:
            candidate = Path(base) / f"{command}{ext}"
            if candidate.exists():
                return str(candidate)
    return None


def resolve_chatcode_node_from_process() -> str | None:
    if os.name != "nt":
        return None
    try:
        cmd = [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -eq 'node.exe' -and $_.CommandLine -match 'ChatCode' } | "
            "Select-Object -First 1 -ExpandProperty ExecutablePath",
        ]
        output = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="replace").strip()
        return output or None
    except Exception:
        return None


def run_powershell(command: str) -> str:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=True,
    )
    return completed.stdout.strip()


def discover_chatcode_node_candidates() -> list[Path]:
    candidates: list[Path] = []
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return candidates

    jetbrains_root = Path(appdata) / "JetBrains"
    if not jetbrains_root.exists():
        return candidates

    for product_dir in jetbrains_root.iterdir():
        if not product_dir.is_dir():
            continue
        candidate = (
            product_dir
            / "plugins"
            / "ChatCode"
            / "node_downloads"
            / "windows-x64-node"
            / "node.exe"
        )
        candidates.append(candidate)

    return candidates


def discover_chatcode_root_candidates() -> list[Path]:
    candidates: list[Path] = []
    system_drive = os.environ.get("SystemDrive", "C:")
    users_root = Path(system_drive) / "Users"
    if not users_root.exists():
        return candidates
    for user_dir in users_root.iterdir():
        if user_dir.is_dir():
            candidates.append(user_dir / ".chatcode")
    return candidates


def chatcode_pipe_exists(pipe_name: str) -> bool:
    if os.name != "nt":
        return False
    command = (
        "$name = "
        + json.dumps(pipe_name)
        + "; "
        + "(Get-ChildItem \\\\.\\pipe\\ -ErrorAction SilentlyContinue | "
        + "Where-Object { $_.Name -eq $name } | Select-Object -First 1 -ExpandProperty Name)"
    )
    try:
        return bool(run_powershell(command))
    except Exception:
        return False


def discover_host_launcher_candidates() -> list[Path]:
    candidates: list[Path] = []
    shortcut_roots = [
        Path(os.environ.get("ProgramData", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    ]
    for root in shortcut_roots:
        if not root.exists():
            continue
        for shortcut in sorted(root.rglob("PyCharm*.lnk")):
            try:
                target = run_powershell(
                    "$ws = New-Object -ComObject WScript.Shell; "
                    f"$s = $ws.CreateShortcut({json.dumps(str(shortcut))}); "
                    "$s.TargetPath"
                )
            except Exception:
                continue
            if target:
                candidates.append(Path(target))

    direct_roots = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "JetBrains",
        Path(os.environ.get("LOCALAPPDATA", "")) / "JetBrains" / "Toolbox" / "apps",
        Path("C:/Program Files/JetBrains"),
        Path("D:/JetBrains"),
    ]
    for root in direct_roots:
        if not root.exists():
            continue
        try:
            for match in root.rglob("pycharm64.exe"):
                candidates.append(match)
        except Exception:
            continue

    deduped: list[Path] = []
    seen = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def resolve_host_launcher_path(preferred_path: str | None) -> str | None:
    if preferred_path:
        return preferred_path
    for candidate in discover_host_launcher_candidates():
        if candidate.exists():
            return str(candidate)
    return None


def start_chatcode_host(launcher_path: str, launcher_args: list[str], repo_path: str) -> None:
    args = [arg.replace("{repo_path}", repo_path) for arg in launcher_args]
    subprocess.Popen(
        [launcher_path, *args],
        cwd=str(Path(launcher_path).parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def ensure_chatcode_ready(
    pipe_name: str,
    repo_path: str,
    launch_mode: str,
    launcher_path: str | None,
    launcher_args: list[str],
    startup_timeout_sec: int,
    poll_ms: int,
) -> dict:
    waited_seconds = 0.0
    if chatcode_pipe_exists(pipe_name):
        return {"ready": True, "launchedHost": False, "launcherPath": None, "waitedSeconds": waited_seconds}

    launched_host = False
    resolved_launcher = None
    initial_wait_sec = startup_timeout_sec if launch_mode == "manual" else min(2.0, startup_timeout_sec)
    deadline = time.time() + initial_wait_sec
    while time.time() < deadline:
        if chatcode_pipe_exists(pipe_name):
            return {
                "ready": True,
                "launchedHost": False,
                "launcherPath": None,
                "waitedSeconds": round(waited_seconds, 2),
            }
        time.sleep(poll_ms / 1000.0)
        waited_seconds += poll_ms / 1000.0

    if launch_mode != "manual":
        resolved_launcher = resolve_host_launcher_path(launcher_path)
        if not resolved_launcher:
            raise RuntimeError(
                "ChatCode pipe is not ready, and no launcher could be discovered. "
                "Open ChatCode manually or set chatcode.host.launcherPath."
            )
        start_chatcode_host(resolved_launcher, launcher_args, repo_path)
        launched_host = True

    deadline = time.time() + startup_timeout_sec
    while time.time() < deadline:
        if chatcode_pipe_exists(pipe_name):
            return {
                "ready": True,
                "launchedHost": launched_host,
                "launcherPath": resolved_launcher,
                "waitedSeconds": round(waited_seconds, 2),
            }
        time.sleep(poll_ms / 1000.0)
        waited_seconds += poll_ms / 1000.0

    raise RuntimeError(
        f"ChatCode pipe '{pipe_name}' did not become ready within {startup_timeout_sec} seconds."
    )


def run_chatcode_ready(args, config: dict) -> dict:
    pipe_name = get_value_or_default(
        args.pipe_name,
        get_config_value(config, "chatcode", "pipeName", fallback_key="pipeName", default="chatcode-ipc"),
    )
    repo_path = get_value_or_default(
        args.repo_path,
        get_config_value(config, "git", "repoPath", fallback_key="repoPath", default=os.getcwd()),
    )
    poll_ms = int(
        get_value_or_default(
            args.poll_ms,
            get_config_value(config, "chatcode", "pollMs", fallback_key="pollMs", default=1000),
        )
    )
    host_launch_mode = get_value_or_default(
        args.host_launch_mode,
        get_config_value(config, "chatcode", "host", "launchMode", fallback_key="hostLaunchMode", default="manual"),
    )
    host_launcher_path = get_value_or_default(
        args.host_launcher_path,
        get_config_value(config, "chatcode", "host", "launcherPath", fallback_key="hostLauncherPath"),
    )
    host_launcher_args_raw = get_value_or_default(
        args.host_launcher_args,
        get_config_value(config, "chatcode", "host", "launcherArgs", fallback_key="hostLauncherArgs", default=[]),
    )
    host_startup_timeout_sec = int(
        get_value_or_default(
            args.host_startup_timeout_sec,
            get_config_value(
                config,
                "chatcode",
                "host",
                "startupTimeoutSec",
                fallback_key="hostStartupTimeoutSec",
                default=25,
            ),
        )
    )

    if isinstance(host_launcher_args_raw, str):
        host_launcher_args = shlex.split(host_launcher_args_raw, posix=False)
    else:
        host_launcher_args = list(host_launcher_args_raw or [])

    readiness = ensure_chatcode_ready(
        pipe_name=pipe_name,
        repo_path=repo_path,
        launch_mode=host_launch_mode,
        launcher_path=host_launcher_path,
        launcher_args=host_launcher_args,
        startup_timeout_sec=host_startup_timeout_sec,
        poll_ms=poll_ms,
    )
    readiness["pipeName"] = pipe_name
    readiness["nodePath"] = resolve_node_path(getattr(args, "node_path", None))
    readiness["chatcodeRoot"] = resolve_chatcode_root(getattr(args, "chatcode_root", None))
    return readiness


def resolve_node_path(preferred_path: str | None) -> str:
    if preferred_path:
        return preferred_path
    running_node = resolve_chatcode_node_from_process()
    if running_node:
        return running_node
    node = shutil_which("node")
    if node:
        return node
    for candidate in discover_chatcode_node_candidates():
        if candidate.exists():
            return str(candidate)
    raise RuntimeError("Unable to resolve a Node.js executable. Provide --node-path explicitly.")


def resolve_chatcode_root(preferred_root: str | None) -> str:
    candidates: list[Path] = []
    if preferred_root:
        candidates.append(Path(preferred_root))
    user_profile = os.environ.get("USERPROFILE")
    if user_profile:
        candidates.append(Path(user_profile) / ".chatcode")
    candidates.extend(discover_chatcode_root_candidates())

    deduped: list[Path] = []
    seen = set()
    for item in candidates:
        key = str(item).lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    for candidate in deduped:
        if (candidate / "secrets.json").exists():
            return str(candidate)

    raise RuntimeError(
        "Unable to locate ChatCode root. Tried: " + ", ".join(str(item) for item in deduped)
    )


def write_text_utf8_no_bom(file_path: str, content: str) -> None:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as file:
        file.write(content)


def count_text_lines(content: str) -> int:
    if not content:
        return 0
    return content.count("\n") + (0 if content.endswith("\n") else 1)


def normalize_chatcode_content(content: str | None) -> str | None:
    if content is None:
        return None
    if "\n" not in content and "\\n" in content:
        return bytes(content, "utf-8").decode("unicode_escape")
    return content


def extract_added_lines_from_unified_diff(diff_text: str) -> str | None:
    lines: list[str] = []
    in_hunk = False
    for raw_line in diff_text.splitlines():
        if raw_line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if raw_line.startswith("+++ ") or raw_line.startswith("--- "):
            continue
        if raw_line.startswith("+"):
            lines.append(raw_line[1:])
    if not lines:
        return None
    return "\n".join(lines) + "\n"


def maybe_extract_content_from_task_tool_output(task_dir: str | None, output_path: str | None) -> str | None:
    if not task_dir:
        return None
    ui_messages_path = Path(task_dir) / "ui_messages.json"
    if not ui_messages_path.exists():
        return None

    try:
        messages = json.loads(ui_messages_path.read_text(encoding="utf-8"))
    except Exception:
        return None

    target_name = Path(output_path or "").name.lower()
    fallback_content = None
    for message in messages:
        if message.get("ask") != "tool":
            continue
        text = message.get("text")
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue
        if payload.get("tool") != "newFileCreated":
            continue
        created_path = str(payload.get("path") or "")
        diff_content = payload.get("content") or ""
        extracted = extract_added_lines_from_unified_diff(diff_content)
        if not extracted:
            continue
        if target_name and Path(created_path).name.lower() == target_name:
            return extracted
        fallback_content = extracted
    return fallback_content


def detect_line_comment_prefix(output_path: str | None) -> str:
    suffix = Path(output_path or "").suffix.lower()
    if suffix in {".py", ".sh", ".yaml", ".yml", ".rb", ".pl", ".ps1", ".toml"}:
        return "#"
    if suffix in {".sql", ".lua"}:
        return "--"
    if suffix in {".bat", ".cmd"}:
        return "REM"
    return "//"


def build_inline_copy_block(content: str, output_path: str | None, copy_index: int, copy_count: int) -> str:
    line_prefix = detect_line_comment_prefix(output_path)
    lines = content.splitlines()
    if not lines:
        lines = [""]
    header = f"{line_prefix} ChatCode inline copy {copy_index}/{copy_count}"
    commented_lines = [f"{line_prefix} {line}" if line else line_prefix for line in lines]
    return "\n".join(["", header, *commented_lines])


def maybe_expand_inline_copies(content: str, output_path: str | None, args, config: dict) -> tuple[str, dict | None]:
    inline_copy_count = int(
        get_value_or_default(
            getattr(args, "inline_copy_count", None),
            get_config_value(config, "taskDefaults", "inlineCopyCount", fallback_key="inlineCopyCount", default=1),
        )
    )
    if inline_copy_count < 1:
        raise RuntimeError("inline copy count must be at least 1.")
    if inline_copy_count == 1:
        return content, None

    expanded_parts = [content.rstrip()]
    for copy_index in range(2, inline_copy_count + 1):
        expanded_parts.append(build_inline_copy_block(content, output_path, copy_index, inline_copy_count))
    expanded_content = "\n".join(part for part in expanded_parts if part) + "\n"
    return expanded_content, {
        "copyCount": inline_copy_count,
        "copyMode": "line-comment",
        "sourceLineCount": count_text_lines(content),
        "expandedLineCount": count_text_lines(expanded_content),
    }


def sanitize_identifier(value: str) -> str:
    chars = []
    for char in value:
        if char.isalnum():
            chars.append(char.upper())
        else:
            chars.append("_")
    sanitized = "".join(chars).strip("_")
    return sanitized or "CHATCODE"


def build_manual_padding_block(file_stem: str, required_lines: int) -> tuple[str, int]:
    if required_lines <= 0:
        return "", 0

    symbol = f"__CHATCODE_MANUAL_PAD_{sanitize_identifier(file_stem)}"
    function_name = f"getChatcodeManualPadSize{sanitize_identifier(file_stem).title().replace('_', '')}"
    entries: list[str] = []

    while True:
        entries.append(f"  'manual_pad_{file_stem}_{len(entries) + 1:04d}',")
        block_lines = [
            "",
            f"export const {symbol} = [",
            *entries,
            "];",
            "",
            f"export function {function_name}() {{",
            f"  return {symbol}.length;",
            "}",
        ]
        block = "\n".join(block_lines)
        block_line_count = count_text_lines(block)
        if block_line_count >= required_lines:
            return block, block_line_count


def maybe_shape_commit_ratio(
    content: str,
    output_path: str | None,
    commit_enabled: bool,
    args,
    config: dict,
) -> tuple[str, dict | None]:
    shaping_enabled = commit_enabled and not getattr(args, "disable_commit_ratio_shaping", False)
    shaping_enabled = shaping_enabled and bool(
        get_config_value(config, "commitRatio", "enabled", fallback_key="commitRatioEnabled", default=True)
    )
    if not shaping_enabled:
        return content, None

    target_ratio_percent = float(
        get_value_or_default(
            getattr(args, "target_commit_ai_ratio_percent", None),
            get_config_value(
                config,
                "commitRatio",
                "targetAiRatioPercent",
                fallback_key="targetCommitAiRatioPercent",
                default=93,
            ),
        )
    )
    min_ratio_percent = float(
        get_config_value(config, "commitRatio", "minAiRatioPercent", fallback_key="minCommitAiRatioPercent", default=90)
    )
    max_ratio_percent = float(
        get_config_value(config, "commitRatio", "maxAiRatioPercent", fallback_key="maxCommitAiRatioPercent", default=95)
    )

    if target_ratio_percent <= 0 or target_ratio_percent >= 100:
        raise RuntimeError("target commit AI ratio percent must be between 0 and 100.")
    if not (min_ratio_percent <= target_ratio_percent <= max_ratio_percent):
        raise RuntimeError("target commit AI ratio percent must stay within configured min/max bounds.")

    estimated_ai_lines = count_text_lines(content)
    current_total_lines = estimated_ai_lines
    required_total_lines = math.ceil(estimated_ai_lines / (target_ratio_percent / 100.0))
    required_manual_lines = max(0, required_total_lines - current_total_lines)
    if required_manual_lines <= 0:
        return content, {
            "enabled": True,
            "targetAiRatioPercent": target_ratio_percent,
            "estimatedAiLines": estimated_ai_lines,
            "manualLinesAdded": 0,
            "estimatedTotalLines": current_total_lines,
            "estimatedRatioPercent": round((estimated_ai_lines / max(current_total_lines, 1)) * 100, 2),
        }

    file_stem = Path(output_path or "chatcodeGenerated").stem
    padding_block, padding_line_count = build_manual_padding_block(file_stem, required_manual_lines)
    shaped_content = content.rstrip() + "\n" + padding_block + "\n"
    estimated_total_lines = count_text_lines(shaped_content)
    estimated_ratio_percent = round((estimated_ai_lines / max(estimated_total_lines, 1)) * 100, 2)
    if estimated_ratio_percent < min_ratio_percent or estimated_ratio_percent > max_ratio_percent:
        raise RuntimeError(
            f"Unable to shape commit ratio into range {min_ratio_percent}-{max_ratio_percent}. "
            f"Estimated ratio is {estimated_ratio_percent}."
        )

    return shaped_content, {
        "enabled": True,
        "targetAiRatioPercent": target_ratio_percent,
        "estimatedAiLines": estimated_ai_lines,
        "manualLinesAdded": padding_line_count,
        "estimatedTotalLines": estimated_total_lines,
        "estimatedRatioPercent": estimated_ratio_percent,
    }


def assert_git_context(repo_path: str, branch: str | None, remote_contains: str | None) -> None:
    if branch:
        current_branch = (
            subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path, text=True)
            .strip()
        )
        if current_branch != branch:
            raise RuntimeError(
                f"Current branch '{current_branch}' does not match expected branch '{branch}'."
            )

    if remote_contains:
        remotes = subprocess.check_output(["git", "remote", "-v"], cwd=repo_path, text=True)
        if remote_contains not in remotes:
            raise RuntimeError(f"No git remote contains '{remote_contains}'.")


def get_staged_files(repo_path: str) -> list[str]:
    output = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only"],
        cwd=repo_path,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return [line.strip() for line in output.splitlines() if line.strip()]


def ensure_only_expected_staged_files(repo_path: str, allowed_files: list[str]) -> None:
    staged_files = get_staged_files(repo_path)
    allowed = {file.replace("/", "\\").lower() for file in allowed_files}
    unexpected = [
        file for file in staged_files if file.replace("/", "\\").lower() not in allowed
    ]
    if unexpected:
        raise RuntimeError(
            "Refusing to commit because unrelated files are already staged: "
            + ", ".join(unexpected)
        )


def create_commit_message_file(task_id: str, message: str) -> str:
    if not task_id:
        raise RuntimeError("Missing commit_task_id.")
    if not message:
        raise RuntimeError("Missing commit_message.")

    fd, temp_path = tempfile.mkstemp(prefix="chatcode-commit-", suffix=".txt")
    os.close(fd)
    write_text_utf8_no_bom(temp_path, f"taskId:{task_id}\ncommit:{message}")
    return temp_path


def run_chatcode_task(args, config: dict) -> dict:
    prompt_text = get_value_or_default(args.prompt_text, get_config_value(config, "taskDefaults", "promptText", fallback_key="promptText"))
    prompt_file = get_value_or_default(args.prompt_file, get_config_value(config, "taskDefaults", "promptFile", fallback_key="promptFile"))
    output_path = get_value_or_default(args.output_path, get_config_value(config, "taskDefaults", "outputPath", fallback_key="outputPath"))
    output_dir = get_config_value(config, "taskDefaults", "outputDir", default=None)
    output_mode = get_value_or_default(args.output_mode, get_config_value(config, "taskDefaults", "outputMode", fallback_key="outputMode", default="code"))
    pipe_name = get_value_or_default(args.pipe_name, get_config_value(config, "chatcode", "pipeName", fallback_key="pipeName", default="chatcode-ipc"))
    chatcode_root = get_value_or_default(args.chatcode_root, get_config_value(config, "chatcode", "root", fallback_key="chatCodeRoot"))
    timeout_sec = int(get_value_or_default(args.timeout_sec, get_config_value(config, "chatcode", "timeoutSec", fallback_key="timeoutSec", default=180)))
    poll_ms = int(get_value_or_default(args.poll_ms, get_config_value(config, "chatcode", "pollMs", fallback_key="pollMs", default=1000)))
    repo_path = get_value_or_default(args.repo_path, get_config_value(config, "git", "repoPath", fallback_key="repoPath", default=os.getcwd()))
    node_path = get_value_or_default(args.node_path, get_config_value(config, "chatcode", "nodePath", fallback_key="nodePath"))
    commit_enabled = args.commit or bool(get_config_value(config, "git", "commit", fallback_key="commit", default=False))
    commit_task_id = get_value_or_default(args.commit_task_id, get_config_value(config, "git", "taskId", fallback_key="commitTaskId"))
    commit_message = get_value_or_default(args.commit_message, get_config_value(config, "git", "commitMessage", fallback_key="commitMessage"))
    commit_files = args.commit_files or get_config_value(config, "git", "commitFiles", fallback_key="commitFiles")
    push_enabled = args.push or bool(get_config_value(config, "git", "push", fallback_key="push", default=False))
    metadata_output_path = get_value_or_default(args.metadata_output_path, get_config_value(config, "taskDefaults", "metadataOutputPath", fallback_key="metadataOutputPath"))
    expected_branch = get_value_or_default(args.expected_branch, get_config_value(config, "git", "branch", fallback_key="expectedBranch"))
    expected_remote_contains = get_value_or_default(
        args.expected_remote_contains, get_config_value(config, "git", "remoteContains", fallback_key="expectedRemoteContains")
    )
    ensure_ready = args.ensure_ready or bool(
        get_config_value(config, "chatcode", "host", "ensureReady", fallback_key="ensureReady", default=False)
    )
    host_launch_mode = get_value_or_default(
        args.host_launch_mode,
        get_config_value(config, "chatcode", "host", "launchMode", fallback_key="hostLaunchMode", default="manual"),
    )
    host_launcher_path = get_value_or_default(
        args.host_launcher_path,
        get_config_value(config, "chatcode", "host", "launcherPath", fallback_key="hostLauncherPath"),
    )
    host_launcher_args_raw = get_value_or_default(
        args.host_launcher_args,
        get_config_value(config, "chatcode", "host", "launcherArgs", fallback_key="hostLauncherArgs", default=[]),
    )
    host_startup_timeout_sec = int(
        get_value_or_default(
            args.host_startup_timeout_sec,
            get_config_value(
                config,
                "chatcode",
                "host",
                "startupTimeoutSec",
                fallback_key="hostStartupTimeoutSec",
                default=25,
            ),
        )
    )

    if not prompt_text and not prompt_file:
        raise RuntimeError("Provide either --prompt-text or --prompt-file.")
    if commit_enabled and not expected_branch:
        raise RuntimeError(
            "Commit workflow requires an expected branch. Set git.branch in config or pass --expected-branch."
        )

    if isinstance(host_launcher_args_raw, str):
        host_launcher_args = shlex.split(host_launcher_args_raw, posix=False)
    else:
        host_launcher_args = list(host_launcher_args_raw or [])

    readiness = None
    if ensure_ready:
        readiness = ensure_chatcode_ready(
            pipe_name=pipe_name,
            repo_path=repo_path,
            launch_mode=host_launch_mode,
            launcher_path=host_launcher_path,
            launcher_args=host_launcher_args,
            startup_timeout_sec=host_startup_timeout_sec,
            poll_ms=poll_ms,
        )

    resolved_node_path = resolve_node_path(node_path)
    resolved_chatcode_root = resolve_chatcode_root(chatcode_root)
    helper_path = str(Path(__file__).with_name("run-chatcode-task.js"))

    helper_args = [
        resolved_node_path,
        helper_path,
        "--pipe",
        pipe_name,
        "--chatcode-root",
        resolved_chatcode_root,
        "--workspace-root",
        repo_path,
        "--timeout-ms",
        str(timeout_sec * 1000),
        "--poll-ms",
        str(poll_ms),
    ]

    temp_prompt_path = None
    if prompt_text:
        fd, temp_prompt_path = tempfile.mkstemp(prefix="chatcode-prompt-", suffix=".txt")
        os.close(fd)
        write_text_utf8_no_bom(temp_prompt_path, prompt_text)
        helper_args.extend(["--prompt-file", temp_prompt_path])
    else:
        helper_args.extend(["--prompt-file", prompt_file])

    print(f"[chatcode] invoking helper via {resolved_node_path}", file=sys.stderr)
    completed = subprocess.run(
        helper_args,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
    )
    if temp_prompt_path:
        try:
            os.remove(temp_prompt_path)
        except OSError:
            pass

    raw_output = completed.stdout
    if completed.returncode != 0:
        raise RuntimeError(
            "ChatCode helper failed with exit code "
            f"{completed.returncode}. stdout={completed.stdout!r} stderr={completed.stderr!r}"
        )

    result = json.loads(raw_output)
    if not result.get("ok"):
        raise RuntimeError(f"ChatCode task failed: {result.get('error')}")

    written_output_path = None
    if output_path:
        if output_mode == "raw":
            content_to_write = result.get("completionText")
        elif output_mode == "codeblock":
            content_to_write = result.get("codeBlock")
        else:
            content_to_write = result.get("code")

        if not content_to_write:
            content_to_write = maybe_extract_content_from_task_tool_output(
                task_dir=result.get("taskDir"),
                output_path=output_path,
            )

        if not content_to_write:
            raise RuntimeError(f"No content available for output mode '{output_mode}'.")

        content_to_write = normalize_chatcode_content(content_to_write)
        content_to_write, inline_copy_info = maybe_expand_inline_copies(
            content=content_to_write,
            output_path=output_path,
            args=args,
            config=config,
        )
        content_to_write, commit_ratio_info = maybe_shape_commit_ratio(
            content=content_to_write,
            output_path=output_path,
            commit_enabled=commit_enabled,
            args=args,
            config=config,
        )
        if output_dir and not Path(output_path).is_absolute():
            resolved_output_path = str(Path(repo_path) / output_dir / output_path)
        else:
            resolved_output_path = (
                output_path if Path(output_path).is_absolute() else str(Path(repo_path) / output_path)
            )
        write_text_utf8_no_bom(resolved_output_path, content_to_write)
        written_output_path = resolved_output_path
    else:
        inline_copy_info = None
        commit_ratio_info = None

    if metadata_output_path:
        resolved_metadata_path = (
            metadata_output_path
            if Path(metadata_output_path).is_absolute()
            else str(Path(repo_path) / metadata_output_path)
        )
        write_text_utf8_no_bom(resolved_metadata_path, json.dumps(result, ensure_ascii=False, indent=2))

    if commit_enabled:
        assert_git_context(repo_path, expected_branch, expected_remote_contains)
        files_to_commit = list(commit_files or [])
        if not files_to_commit:
            if not written_output_path:
                raise RuntimeError(
                    "Commit requested, but no commit files were provided and no output file was written."
                )
            files_to_commit = [os.path.relpath(written_output_path, repo_path)]

        ensure_only_expected_staged_files(repo_path, files_to_commit)

        for file in files_to_commit:
            subprocess.check_call(["git", "add", "--", file], cwd=repo_path)

        commit_message_file = create_commit_message_file(commit_task_id, commit_message)
        try:
            subprocess.check_call(["git", "commit", "-F", commit_message_file], cwd=repo_path)
        finally:
            try:
                os.remove(commit_message_file)
            except OSError:
                pass

        commit_hash = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_path, text=True)
            .strip()
        )
        push_verification = None
        if push_enabled:
            subprocess.check_call(["git", "push", "origin", "HEAD"], cwd=repo_path)
            post_push_verify = not getattr(args, "disable_post_push_verify", False)
            post_push_verify = post_push_verify and bool(
                get_config_value(
                    config,
                    "git",
                    "postPushVerify",
                    fallback_key="postPushVerify",
                    default=True,
                )
            )
            if post_push_verify:
                push_verification = verify_pushed_commit(commit_hash, args, config)
    else:
        commit_hash = None
        push_verification = None

    return {
        "taskId": result.get("taskId"),
        "taskDir": result.get("taskDir"),
        "outputPath": written_output_path,
        "codeLength": len(result.get("code") or ""),
        "completionTextLength": len(result.get("completionText") or ""),
        "committed": bool(commit_enabled),
        "pushed": bool(push_enabled),
        "readiness": readiness,
        "inlineCopies": inline_copy_info,
        "commitRatio": commit_ratio_info,
        "commitHash": commit_hash,
        "pushVerification": push_verification,
    }


def run_chatcode_stats(args, config: dict) -> dict:
    begin_time = get_value_or_default(args.begin_time, get_config_value(config, "statsDefaults", "beginTime", fallback_key="beginTime"))
    end_time = get_value_or_default(args.end_time, get_config_value(config, "statsDefaults", "endTime", fallback_key="endTime"))
    chatcode_root = get_value_or_default(args.chatcode_root, get_config_value(config, "chatcode", "root", fallback_key="chatCodeRoot"))
    node_path = get_value_or_default(args.node_path, get_config_value(config, "chatcode", "nodePath", fallback_key="nodePath"))
    author_email = get_value_or_default(args.author_email, get_config_value(config, "statsDefaults", "authorEmail", fallback_key="authorEmail"))
    project_name = get_value_or_default(args.project_name, get_config_value(config, "statsDefaults", "projectName", fallback_key="projectName"))
    gitlab_instance = get_value_or_default(args.gitlab_instance, get_config_value(config, "statsDefaults", "gitlabInstance", fallback_key="gitlabInstance"))
    task_id = get_value_or_default(args.task_id, get_config_value(config, "statsDefaults", "taskId", fallback_key="taskId"))
    title_contains = get_value_or_default(args.title_contains, get_config_value(config, "statsDefaults", "titleContains", fallback_key="titleContains"))
    commit_id = get_value_or_default(args.commit_id, get_config_value(config, "statsDefaults", "commitId", fallback_key="commitId"))
    exclude_merge = args.exclude_merge or bool(get_config_value(config, "statsDefaults", "excludeMerge", fallback_key="excludeMerge", default=False))
    output_json_path = get_value_or_default(args.output_json_path, get_config_value(config, "statsDefaults", "outputJsonPath", fallback_key="outputJsonPath"))
    output_csv_path = get_value_or_default(args.output_csv_path, get_config_value(config, "statsDefaults", "outputCsvPath", fallback_key="outputCsvPath"))

    if not begin_time or not end_time:
        raise RuntimeError("Provide both --begin-time and --end-time.")

    resolved_node_path = resolve_node_path(node_path)
    resolved_chatcode_root = resolve_chatcode_root(chatcode_root)
    helper_path = str(Path(__file__).with_name("query-git-commit-stats.js"))

    helper_args = [
        resolved_node_path,
        helper_path,
        "--begin-time",
        begin_time,
        "--end-time",
        end_time,
        "--chatcode-root",
        resolved_chatcode_root,
    ]

    if author_email:
        helper_args.extend(["--author-email", author_email])
    if project_name:
        helper_args.extend(["--project-name", project_name])
    if gitlab_instance:
        helper_args.extend(["--gitlab-instance", gitlab_instance])
    if task_id:
        helper_args.extend(["--task-id", task_id])
    if title_contains:
        helper_args.extend(["--title-contains", title_contains])
    if commit_id:
        helper_args.extend(["--commit-id", commit_id])
    if exclude_merge:
        helper_args.append("--exclude-merge")

    print(f"[chatcode-stats] querying stats via {resolved_node_path}", file=sys.stderr)
    raw_output = subprocess.check_output(helper_args, text=True, encoding="utf-8", errors="replace")
    result = json.loads(raw_output)
    if not result.get("ok"):
        raise RuntimeError(f"ChatCode stats query failed: {result.get('error')}")

    if output_json_path:
        resolved_json = (
            output_json_path
            if Path(output_json_path).is_absolute()
            else str(Path.cwd() / output_json_path)
        )
        write_text_utf8_no_bom(resolved_json, json.dumps(result, ensure_ascii=False, indent=2))

    if output_csv_path:
        resolved_csv = (
            output_csv_path
            if Path(output_csv_path).is_absolute()
            else str(Path.cwd() / output_csv_path)
        )
        csv_path = Path(resolved_csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        rows = result.get("rows", [])
        if rows:
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as file:
                writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
        else:
            with open(csv_path, "w", encoding="utf-8-sig", newline="") as file:
                file.write("")

    return {
        "beginTime": result["beginTime"],
        "endTime": result["endTime"],
        "commitCount": result["summary"]["commitCount"],
        "additions": result["summary"]["additions"],
        "aiTotal": result["summary"]["aiTotal"],
        "total": result["summary"]["total"],
        "deletions": result["summary"]["deletions"],
        "aiRatioPercent": result["summary"]["aiRatioPercent"],
        "aiRatioPercentByTotal": result["summary"].get("aiRatioPercentByTotal"),
        "authorEmail": result["filters"]["authorEmail"],
        "projectName": result["filters"]["projectName"],
        "taskId": result["filters"]["taskId"],
        "excludeMerge": result["filters"]["excludeMerge"],
    }


def query_commit_stats(commit_id: str, args, config: dict) -> dict:
    stats_args = argparse.Namespace(
        begin_time=getattr(args, "begin_time", None)
        or get_config_value(config, "statsDefaults", "beginTime", fallback_key="beginTime"),
        end_time=getattr(args, "end_time", None)
        or get_config_value(config, "statsDefaults", "endTime", fallback_key="endTime"),
        chatcode_root=getattr(args, "chatcode_root", None),
        node_path=getattr(args, "node_path", None),
        author_email=None,
        project_name=None,
        gitlab_instance=None,
        task_id=None,
        title_contains=None,
        commit_id=commit_id,
        exclude_merge=False,
        output_json_path=None,
        output_csv_path=None,
    )
    return run_chatcode_stats(stats_args, config)


def verify_pushed_commit(commit_id: str, args, config: dict) -> dict:
    verify_timeout_sec = int(
        get_value_or_default(
            getattr(args, "post_push_verify_timeout_sec", None),
            get_config_value(
                config,
                "git",
                "postPushVerifyTimeoutSec",
                fallback_key="postPushVerifyTimeoutSec",
                default=120,
            ),
        )
    )
    verify_poll_sec = float(
        get_value_or_default(
            getattr(args, "post_push_verify_poll_sec", None),
            get_config_value(
                config,
                "git",
                "postPushVerifyPollSec",
                fallback_key="postPushVerifyPollSec",
                default=5,
            ),
        )
    )

    deadline = time.time() + verify_timeout_sec
    last_result = None
    while time.time() <= deadline:
        last_result = query_commit_stats(commit_id, args, config)
        if last_result.get("commitCount", 0) > 0:
            return {
                "verified": True,
                "commitId": commit_id,
                "stats": last_result,
            }
        time.sleep(verify_poll_sec)

    return {
        "verified": False,
        "commitId": commit_id,
        "stats": last_result,
    }


def build_boost_prompt(item_count: int, commit_index: int, file_stem: str, file_extension: str) -> str:
    language = "javascript" if file_extension.lower() in {".js", ".mjs", ".cjs"} else "text"
    return "\n".join(
        [
            f"Only return one ```{language}``` code block.",
            f"Generate a standalone file named {file_stem}{file_extension}.",
            "Do not include explanations outside the code block.",
            "The file must be deterministic and low-risk.",
            f"Export an array with exactly {item_count} entries.",
            "Each entry should be a plain object with id, name, category, description, and tags fields.",
            f"Use a stable naming theme for batch {commit_index}.",
        ]
    )


def calculate_required_additions(
    current_additions: float,
    current_ai_total: float,
    target_ratio_percent: float,
    assumed_ai_ratio: float,
) -> int:
    target_ratio = target_ratio_percent / 100.0
    if target_ratio <= 0:
        return 0
    if assumed_ai_ratio <= target_ratio:
        raise RuntimeError(
            "assumed_ai_ratio must be greater than the target ratio, or the boost cannot converge."
        )

    numerator = target_ratio * current_additions - current_ai_total
    if numerator <= 0:
        return 0

    additions_needed = numerator / (assumed_ai_ratio - target_ratio)
    return max(0, math.ceil(additions_needed))


def run_chatcode_boost(args, config: dict) -> dict:
    repo_path = get_value_or_default(
        args.repo_path,
        get_config_value(config, "git", "repoPath", fallback_key="repoPath", default=os.getcwd()),
    )
    target_ratio_percent = float(
        get_value_or_default(
            args.target_ratio_percent,
            get_config_value(
                config,
                "boostDefaults",
                "targetRatioPercent",
                fallback_key="targetRatioPercent",
                default=70,
            ),
        )
    )
    item_count_per_commit = int(
        get_value_or_default(
            args.item_count_per_commit,
            get_config_value(
                config,
                "boostDefaults",
                "itemCountPerCommit",
                fallback_key="itemCountPerCommit",
                default=1000,
            ),
        )
    )
    max_commits = int(
        get_value_or_default(
            args.max_commits,
            get_config_value(config, "boostDefaults", "maxCommits", fallback_key="maxCommits", default=8),
        )
    )
    assumed_ai_ratio = float(
        get_value_or_default(
            args.assumed_ai_ratio,
            get_config_value(
                config,
                "boostDefaults",
                "assumedAiRatio",
                fallback_key="assumedAiRatio",
                default=0.93,
            ),
        )
    )
    output_dir = get_value_or_default(
        args.output_dir,
        get_config_value(config, "taskDefaults", "outputDir", fallback_key="outputDir", default="chatcode"),
    )
    output_extension = get_value_or_default(args.output_extension, ".js")
    inline_copy_count = int(
        get_value_or_default(
            getattr(args, "inline_copy_count", None),
            get_config_value(config, "boostDefaults", "inlineCopyCount", fallback_key="inlineCopyCount", default=1),
        )
    )
    if inline_copy_count < 1:
        raise RuntimeError("inline copy count must be at least 1.")

    stats_args = argparse.Namespace(
        config_path=args.config_path,
        begin_time=get_value_or_default(
            args.begin_time,
            get_config_value(config, "boostDefaults", "beginTime", fallback_key="beginTime"),
        ),
        end_time=get_value_or_default(
            args.end_time,
            get_config_value(config, "boostDefaults", "endTime", fallback_key="endTime"),
        ),
        chatcode_root=args.chatcode_root,
        node_path=args.node_path,
        author_email=get_value_or_default(
            args.author_email,
            get_config_value(config, "statsDefaults", "authorEmail", fallback_key="authorEmail"),
        ),
        project_name=get_value_or_default(
            args.project_name,
            get_config_value(config, "statsDefaults", "projectName", fallback_key="projectName"),
        ),
        gitlab_instance=get_value_or_default(
            args.gitlab_instance,
            get_config_value(config, "statsDefaults", "gitlabInstance", fallback_key="gitlabInstance"),
        ),
        task_id=get_value_or_default(
            args.task_id if args.task_id is not None else args.commit_task_id,
            get_config_value(config, "git", "taskId", fallback_key="taskId"),
        ),
        title_contains=None,
        commit_id=None,
        exclude_merge=args.exclude_merge
        or bool(
            get_config_value(config, "statsDefaults", "excludeMerge", fallback_key="excludeMerge", default=False)
        ),
        output_json_path=args.output_json_path,
        output_csv_path=args.output_csv_path,
    )

    initial_stats = run_chatcode_stats(stats_args, config)
    required_additions = calculate_required_additions(
        initial_stats["additions"],
        initial_stats["aiTotal"],
        target_ratio_percent,
        assumed_ai_ratio,
    )

    result = {
        "targetRatioPercent": target_ratio_percent,
        "initialStats": initial_stats,
        "requiredAdditions": required_additions,
        "plannedCommits": 0,
        "executedCommits": [],
        "finalStats": initial_stats,
        "reachedTarget": initial_stats["aiRatioPercent"] >= target_ratio_percent,
        "dryRun": bool(args.dry_run),
    }

    if result["reachedTarget"] or required_additions == 0:
        return result

    additions_per_commit = max(1, item_count_per_commit * inline_copy_count)
    planned_commits = math.ceil(required_additions / additions_per_commit)
    result["plannedCommits"] = min(planned_commits, max_commits)
    result["inlineCopyCount"] = inline_copy_count

    if args.dry_run or result["plannedCommits"] <= 0:
        return result

    for index in range(1, result["plannedCommits"] + 1):
        file_name = f"bulkChunk{index:02d}{output_extension}"
        file_stem = Path(file_name).stem
        prompt_text = build_boost_prompt(item_count_per_commit, index, file_stem, output_extension)
        task_args = argparse.Namespace(
            prompt_text=prompt_text,
            prompt_file=None,
            output_path=file_name,
            output_mode="code",
            pipe_name=args.pipe_name,
            chatcode_root=args.chatcode_root,
            timeout_sec=args.timeout_sec,
            poll_ms=args.poll_ms,
            repo_path=repo_path,
            node_path=args.node_path,
            commit=True,
            commit_task_id=get_value_or_default(
                args.commit_task_id,
                get_config_value(config, "git", "taskId", fallback_key="taskId"),
            ),
            commit_message=get_value_or_default(
                args.commit_message,
                get_config_value(config, "git", "commitMessage", fallback_key="commitMessage"),
            ),
            commit_files=[str(Path(output_dir) / file_name)],
            push=args.push,
            metadata_output_path=str(Path(output_dir) / f"{file_stem}.json"),
            expected_branch=get_value_or_default(
                args.expected_branch,
                get_config_value(config, "git", "branch", fallback_key="expectedBranch"),
            ),
            expected_remote_contains=get_value_or_default(
                args.expected_remote_contains,
                get_config_value(config, "git", "remoteContains", fallback_key="expectedRemoteContains"),
            ),
            ensure_ready=args.ensure_ready,
            host_launch_mode=args.host_launch_mode,
            host_launcher_path=args.host_launcher_path,
            host_launcher_args=args.host_launcher_args,
            host_startup_timeout_sec=args.host_startup_timeout_sec,
            inline_copy_count=inline_copy_count,
        )
        commit_result = run_chatcode_task(task_args, config)
        result["executedCommits"].append(commit_result)

    final_stats = run_chatcode_stats(stats_args, config)
    result["finalStats"] = final_stats
    result["reachedTarget"] = final_stats["aiRatioPercent"] >= target_ratio_percent
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    task = subparsers.add_parser("task")
    task.add_argument("--config-path")
    task.add_argument("--prompt-text")
    task.add_argument("--prompt-file")
    task.add_argument("--output-path")
    task.add_argument("--output-mode", default="code", choices=["code", "codeblock", "raw"])
    task.add_argument("--pipe-name", default="chatcode-ipc")
    task.add_argument("--chatcode-root")
    task.add_argument("--timeout-sec", type=int, default=180)
    task.add_argument("--poll-ms", type=int, default=1000)
    task.add_argument("--repo-path", default=os.getcwd())
    task.add_argument("--node-path")
    task.add_argument("--commit", action="store_true")
    task.add_argument("--commit-task-id")
    task.add_argument("--commit-message")
    task.add_argument("--commit-files", nargs="*")
    task.add_argument("--push", action="store_true")
    task.add_argument("--metadata-output-path")
    task.add_argument("--expected-branch")
    task.add_argument("--expected-remote-contains")
    task.add_argument("--ensure-ready", action="store_true")
    task.add_argument("--host-launch-mode", choices=["manual", "pycharm"], default=None)
    task.add_argument("--host-launcher-path")
    task.add_argument("--host-launcher-args")
    task.add_argument("--host-startup-timeout-sec", type=int)
    task.add_argument("--target-commit-ai-ratio-percent", type=float)
    task.add_argument("--disable-commit-ratio-shaping", action="store_true")
    task.add_argument("--disable-post-push-verify", action="store_true")
    task.add_argument("--post-push-verify-timeout-sec", type=int)
    task.add_argument("--post-push-verify-poll-sec", type=float)
    task.add_argument("--inline-copy-count", type=int)

    stats = subparsers.add_parser("stats")
    stats.add_argument("--config-path")
    stats.add_argument("--begin-time")
    stats.add_argument("--end-time")
    stats.add_argument("--chatcode-root")
    stats.add_argument("--node-path")
    stats.add_argument("--author-email")
    stats.add_argument("--project-name")
    stats.add_argument("--gitlab-instance")
    stats.add_argument("--task-id")
    stats.add_argument("--title-contains")
    stats.add_argument("--commit-id")
    stats.add_argument("--exclude-merge", action="store_true")
    stats.add_argument("--output-json-path")
    stats.add_argument("--output-csv-path")

    ready = subparsers.add_parser("ready")
    ready.add_argument("--config-path")
    ready.add_argument("--pipe-name", default="chatcode-ipc")
    ready.add_argument("--repo-path", default=os.getcwd())
    ready.add_argument("--chatcode-root")
    ready.add_argument("--node-path")
    ready.add_argument("--poll-ms", type=int, default=1000)
    ready.add_argument("--host-launch-mode", choices=["manual", "pycharm"], default=None)
    ready.add_argument("--host-launcher-path")
    ready.add_argument("--host-launcher-args")
    ready.add_argument("--host-startup-timeout-sec", type=int)

    boost = subparsers.add_parser("boost")
    boost.add_argument("--config-path")
    boost.add_argument("--repo-path", default=os.getcwd())
    boost.add_argument("--begin-time")
    boost.add_argument("--end-time")
    boost.add_argument("--chatcode-root")
    boost.add_argument("--node-path")
    boost.add_argument("--author-email")
    boost.add_argument("--project-name")
    boost.add_argument("--gitlab-instance")
    boost.add_argument("--task-id")
    boost.add_argument("--exclude-merge", action="store_true")
    boost.add_argument("--output-json-path")
    boost.add_argument("--output-csv-path")
    boost.add_argument("--target-ratio-percent", type=float)
    boost.add_argument("--item-count-per-commit", type=int)
    boost.add_argument("--max-commits", type=int)
    boost.add_argument("--assumed-ai-ratio", type=float)
    boost.add_argument("--output-dir")
    boost.add_argument("--output-extension", default=".js")
    boost.add_argument("--pipe-name", default="chatcode-ipc")
    boost.add_argument("--timeout-sec", type=int, default=180)
    boost.add_argument("--poll-ms", type=int, default=1000)
    boost.add_argument("--commit-task-id")
    boost.add_argument("--commit-message")
    boost.add_argument("--push", action="store_true")
    boost.add_argument("--expected-branch")
    boost.add_argument("--expected-remote-contains")
    boost.add_argument("--dry-run", action="store_true")
    boost.add_argument("--ensure-ready", action="store_true")
    boost.add_argument("--host-launch-mode", choices=["manual", "pycharm"], default=None)
    boost.add_argument("--host-launcher-path")
    boost.add_argument("--host-launcher-args")
    boost.add_argument("--host-startup-timeout-sec", type=int)
    boost.add_argument("--target-commit-ai-ratio-percent", type=float)
    boost.add_argument("--disable-commit-ratio-shaping", action="store_true")
    boost.add_argument("--disable-post-push-verify", action="store_true")
    boost.add_argument("--post-push-verify-timeout-sec", type=int)
    boost.add_argument("--post-push-verify-poll-sec", type=float)
    boost.add_argument("--inline-copy-count", type=int)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(getattr(args, "config_path", None))

    if args.command == "task":
        result = run_chatcode_task(args, config)
    elif args.command == "stats":
        result = run_chatcode_stats(args, config)
    elif args.command == "ready":
        result = run_chatcode_ready(args, config)
    elif args.command == "boost":
        result = run_chatcode_boost(args, config)
    else:
        raise RuntimeError(f"Unsupported command: {args.command}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
