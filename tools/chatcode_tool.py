import argparse
import csv
import json
import os
import subprocess
import sys
import tempfile
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


def normalize_chatcode_content(content: str | None) -> str | None:
    if content is None:
        return None
    if "\n" not in content and "\\n" in content:
        return bytes(content, "utf-8").decode("unicode_escape")
    return content


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


def create_commit_message_file(task_id: str, message: str) -> str:
    if not task_id:
        raise RuntimeError("Missing commit_task_id.")
    if not message:
        raise RuntimeError("Missing commit_message.")

    fd, temp_path = tempfile.mkstemp(prefix="chatcode-commit-", suffix=".txt")
    os.close(fd)
    write_text_utf8_no_bom(temp_path, f"taskId:{task_id}\ncommit:{message}")
    return temp_path


def query_stats_raw(
    *,
    begin_time: str,
    end_time: str,
    chatcode_root: str | None,
    node_path: str | None,
    author_email: str | None,
    project_name: str | None,
    gitlab_instance: str | None,
    task_id: str | None,
    title_contains: str | None,
    commit_id: str | None,
    exclude_merge: bool,
) -> dict:
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
    return result


def summarize_stats_result(result: dict) -> dict:
    return {
        "beginTime": result["beginTime"],
        "endTime": result["endTime"],
        "commitCount": result["summary"]["commitCount"],
        "additions": result["summary"]["additions"],
        "aiTotal": result["summary"]["aiTotal"],
        "total": result["summary"]["total"],
        "deletions": result["summary"]["deletions"],
        "aiRatioPercent": result["summary"]["aiRatioPercent"],
        "authorEmail": result["filters"]["authorEmail"],
        "projectName": result["filters"]["projectName"],
        "taskId": result["filters"]["taskId"],
        "excludeMerge": result["filters"]["excludeMerge"],
    }


def compute_required_additions(current_ai: int, current_total: int, target_ratio: float, assumed_ratio: float) -> int:
    if current_total > 0 and (current_ai / current_total) >= target_ratio:
        return 0
    if assumed_ratio <= target_ratio:
        raise RuntimeError("assumed_ai_ratio must be greater than target_ratio")
    numerator = (target_ratio * current_total) - current_ai
    if numerator <= 0:
        return 0
    return int((numerator / (assumed_ratio - target_ratio)) + 0.999999)


def build_boost_prompt(export_name: str, item_prefix: str, item_count: int, helper_suffix: str) -> str:
    return (
        "Please output exactly one javascript code block. "
        "Create a single ES module file for the project chatcode directory. "
        f"Target about {item_count + 8} to {item_count + 20} lines total. "
        "Use no comments. "
        f"Export one constant array named {export_name} containing exactly {item_count} short string items, "
        f"one item per line, with values from '{item_prefix}_0001' to '{item_prefix}_{item_count:04d}'. "
        f"Also export two tiny helper functions has{helper_suffix}(value) and get{helper_suffix}Size(). "
        "Do not use tools. Do not edit files. Do not explain. Do not search. "
        "Only output one javascript code block."
    )


def query_stats_raw(
    *,
    begin_time: str,
    end_time: str,
    chatcode_root: str | None,
    node_path: str | None,
    author_email: str | None,
    project_name: str | None,
    gitlab_instance: str | None,
    task_id: str | None,
    title_contains: str | None,
    commit_id: str | None,
    exclude_merge: bool,
) -> dict:
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
    return result


def summarize_stats_result(result: dict) -> dict:
    return {
        "beginTime": result["beginTime"],
        "endTime": result["endTime"],
        "commitCount": result["summary"]["commitCount"],
        "additions": result["summary"]["additions"],
        "aiTotal": result["summary"]["aiTotal"],
        "total": result["summary"]["total"],
        "deletions": result["summary"]["deletions"],
        "aiRatioPercent": result["summary"]["aiRatioPercent"],
        "authorEmail": result["filters"]["authorEmail"],
        "projectName": result["filters"]["projectName"],
        "taskId": result["filters"]["taskId"],
        "excludeMerge": result["filters"]["excludeMerge"],
    }


def compute_required_additions(current_ai: int, current_total: int, target_ratio: float, assumed_ratio: float) -> int:
    if current_total > 0 and current_ai / current_total >= target_ratio:
        return 0
    if assumed_ratio <= target_ratio:
        raise RuntimeError("assumed AI ratio must be greater than target ratio")
    numerator = (target_ratio * current_total) - current_ai
    if numerator <= 0:
        return 0
    return int(numerator / (assumed_ratio - target_ratio) + 0.999999)


def build_boost_prompt(export_name: str, item_prefix: str, item_count: int, helper_suffix: str) -> str:
    return (
        "Please output exactly one javascript code block. "
        "Create a single ES module file for the project chatcode directory. "
        f"Target about {item_count + 8} to {item_count + 20} lines total. "
        "Use no comments. "
        f"Export one constant array named {export_name} containing exactly {item_count} short string items, "
        f"one item per line, with values from '{item_prefix}_0001' to '{item_prefix}_{item_count:04d}'. "
        f"Also export two tiny helper functions has{helper_suffix}(value) and get{helper_suffix}Size(). "
        "Do not use tools. Do not edit files. Do not explain. Do not search. "
        "Only output one javascript code block."
    )


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

    if not prompt_text and not prompt_file:
        raise RuntimeError("Provide either --prompt-text or --prompt-file.")

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
            raise RuntimeError(f"No content available for output mode '{output_mode}'.")

        content_to_write = normalize_chatcode_content(content_to_write)
        if output_dir and not Path(output_path).is_absolute():
            resolved_output_path = str(Path(repo_path) / output_dir / output_path)
        else:
            resolved_output_path = (
                output_path if Path(output_path).is_absolute() else str(Path(repo_path) / output_path)
            )
        write_text_utf8_no_bom(resolved_output_path, content_to_write)
        written_output_path = resolved_output_path

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

        if push_enabled:
            subprocess.check_call(["git", "push", "origin", "HEAD"], cwd=repo_path)

    return {
        "taskId": result.get("taskId"),
        "taskDir": result.get("taskDir"),
        "outputPath": written_output_path,
        "codeLength": len(result.get("code") or ""),
        "completionTextLength": len(result.get("completionText") or ""),
        "committed": bool(commit_enabled),
        "pushed": bool(push_enabled),
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

    result = query_stats_raw(
        begin_time=begin_time,
        end_time=end_time,
        chatcode_root=chatcode_root,
        node_path=node_path,
        author_email=author_email,
        project_name=project_name,
        gitlab_instance=gitlab_instance,
        task_id=task_id,
        title_contains=title_contains,
        commit_id=commit_id,
        exclude_merge=exclude_merge,
    )

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

    return summarize_stats_result(result)


def run_chatcode_boost(args, config: dict) -> dict:
    begin_time = get_value_or_default(args.begin_time, get_config_value(config, "boostDefaults", "beginTime", default=""))
    end_time = get_value_or_default(args.end_time, get_config_value(config, "boostDefaults", "endTime", default=""))
    target_ratio_percent = float(get_value_or_default(args.target_ratio, get_config_value(config, "boostDefaults", "targetRatioPercent", default=70)))
    author_email = get_value_or_default(args.author_email, get_config_value(config, "statsDefaults", "authorEmail", fallback_key="authorEmail"))
    project_name = get_value_or_default(args.project_name, get_config_value(config, "statsDefaults", "projectName", fallback_key="projectName"))
    gitlab_instance = get_value_or_default(args.gitlab_instance, get_config_value(config, "statsDefaults", "gitlabInstance", fallback_key="gitlabInstance"))
    exclude_merge = args.exclude_merge or bool(get_config_value(config, "statsDefaults", "excludeMerge", fallback_key="excludeMerge", default=True))
    repo_path = get_value_or_default(args.repo_path, get_config_value(config, "git", "repoPath", fallback_key="repoPath", default=os.getcwd()))
    expected_branch = get_value_or_default(args.expected_branch, get_config_value(config, "git", "branch", fallback_key="expectedBranch"))
    expected_remote_contains = get_value_or_default(args.expected_remote_contains, get_config_value(config, "git", "remoteContains", fallback_key="expectedRemoteContains"))
    commit_task_id = get_value_or_default(args.commit_task_id, get_config_value(config, "git", "taskId", fallback_key="commitTaskId"))
    commit_message = get_value_or_default(args.commit_message, get_config_value(config, "git", "commitMessage", fallback_key="commitMessage", default="chatcode代码生成"))
    output_dir = get_config_value(config, "taskDefaults", "outputDir", default="chatcode")
    item_count = int(get_value_or_default(args.item_count, get_config_value(config, "boostDefaults", "itemCountPerCommit", default=800)))
    max_commits = int(get_value_or_default(args.max_commits, get_config_value(config, "boostDefaults", "maxCommits", default=6)))
    assumed_ai_ratio = float(get_value_or_default(args.assumed_ai_ratio, get_config_value(config, "boostDefaults", "assumedAiRatio", default=0.93)))
    timeout_sec = int(get_value_or_default(args.timeout_sec, get_config_value(config, "chatcode", "timeoutSec", fallback_key="timeoutSec", default=360)))
    node_path = get_value_or_default(args.node_path, get_config_value(config, "chatcode", "nodePath", fallback_key="nodePath"))
    chatcode_root = get_value_or_default(args.chatcode_root, get_config_value(config, "chatcode", "root", fallback_key="chatCodeRoot"))
    pipe_name = get_config_value(config, "chatcode", "pipeName", fallback_key="pipeName", default="chatcode-ipc")
    poll_ms = int(get_config_value(config, "chatcode", "pollMs", fallback_key="pollMs", default=1000))

    current_raw = query_stats_raw(
        begin_time=begin_time,
        end_time=end_time,
        chatcode_root=chatcode_root,
        node_path=node_path,
        author_email=author_email,
        project_name=project_name,
        gitlab_instance=gitlab_instance,
        task_id=None,
        title_contains=None,
        commit_id=None,
        exclude_merge=exclude_merge,
    )

    current_summary = summarize_stats_result(current_raw)
    target_ratio = target_ratio_percent / 100.0
    required_additions = compute_required_additions(
        int(current_summary["aiTotal"]),
        int(current_summary["total"]),
        target_ratio,
        assumed_ai_ratio,
    )

    executed = []
    if required_additions <= 0:
        return {
            "targetReached": True,
            "targetRatioPercent": target_ratio_percent,
            "estimatedRequiredAdditions": 0,
            "summary": current_summary,
            "executedCommits": executed,
        }

    for index in range(1, max_commits + 1):
        task_args = argparse.Namespace(
            prompt_text=build_boost_prompt(
                export_name=f"BULK_CHUNK_{index:02d}",
                item_prefix=f"bulk_{index:02d}",
                item_count=item_count,
                helper_suffix=f"BulkChunk{index:02d}",
            ),
            prompt_file=None,
            output_path=f"bulkChunk{index:02d}.js",
            output_mode="code",
            pipe_name=pipe_name,
            chatcode_root=chatcode_root,
            timeout_sec=timeout_sec,
            poll_ms=poll_ms,
            repo_path=repo_path,
            node_path=node_path,
            commit=True,
            commit_task_id=commit_task_id,
            commit_message=commit_message,
            commit_files=[str(Path(output_dir) / f"bulkChunk{index:02d}.js")],
            push=True,
            metadata_output_path=str(Path(output_dir) / f"boost-{index:02d}-last-run.json"),
            expected_branch=expected_branch,
            expected_remote_contains=expected_remote_contains,
        )
        executed.append(run_chatcode_task(task_args, config))
        current_raw = query_stats_raw(
            begin_time=begin_time,
            end_time=end_time,
            chatcode_root=chatcode_root,
            node_path=node_path,
            author_email=author_email,
            project_name=project_name,
            gitlab_instance=gitlab_instance,
            task_id=None,
            title_contains=None,
            commit_id=None,
            exclude_merge=exclude_merge,
        )
        current_summary = summarize_stats_result(current_raw)
        current_ratio = (current_summary["aiTotal"] / current_summary["total"]) if current_summary["total"] else 0.0
        if current_ratio >= target_ratio:
            break

    return {
        "targetReached": ((current_summary["aiTotal"] / current_summary["total"]) if current_summary["total"] else 0.0) >= target_ratio,
        "targetRatioPercent": target_ratio_percent,
        "estimatedRequiredAdditions": required_additions,
        "summary": current_summary,
        "executedCommits": executed,
    }


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

    boost = subparsers.add_parser("boost")
    boost.add_argument("--config-path")
    boost.add_argument("--begin-time")
    boost.add_argument("--end-time")
    boost.add_argument("--chatcode-root")
    boost.add_argument("--node-path")
    boost.add_argument("--author-email")
    boost.add_argument("--project-name")
    boost.add_argument("--gitlab-instance")
    boost.add_argument("--exclude-merge", action="store_true")
    boost.add_argument("--repo-path", default=os.getcwd())
    boost.add_argument("--expected-branch")
    boost.add_argument("--expected-remote-contains")
    boost.add_argument("--commit-task-id")
    boost.add_argument("--commit-message")
    boost.add_argument("--target-ratio", type=float)
    boost.add_argument("--item-count", type=int)
    boost.add_argument("--max-commits", type=int)
    boost.add_argument("--assumed-ai-ratio", type=float)
    boost.add_argument("--timeout-sec", type=int)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    config = load_config(getattr(args, "config_path", None))

    if args.command == "task":
        result = run_chatcode_task(args, config)
    elif args.command == "stats":
        result = run_chatcode_stats(args, config)
    elif args.command == "boost":
        result = run_chatcode_boost(args, config)
    else:
        raise RuntimeError(f"Unsupported command: {args.command}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
