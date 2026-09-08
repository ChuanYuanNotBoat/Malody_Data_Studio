import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional


ColorizeFn = Callable[[str, str], str]


@dataclass(frozen=True)
class FlagSpec:
    flag: str
    value_type: str  # bool | str | int | enum
    target: Optional[str] = None
    enum_values: Optional[List[str]] = None
    minimum: Optional[int] = None
    maximum: Optional[int] = None
    normalize_upper: bool = False


UPDATE_OPTION_SCHEMAS: Dict[str, Dict[str, object]] = {
    "leaderboard": {
        "script": "crawlers/rankings.py",
        "flags": {
            "--once": FlagSpec(flag="--once", value_type="bool", target="--once"),
        },
        "defaults": ["--once"],
    },
    "player": {
        "script": "crawlers/player_profile.py",
        "flags": {
            "--uid": FlagSpec(flag="--uid", value_type="str"),
            "--uid-list": FlagSpec(flag="--uid-list", value_type="str"),
            "--uid-range": FlagSpec(flag="--uid-range", value_type="str"),
            "--uid-file": FlagSpec(flag="--uid-file", value_type="str"),
            "--log-level": FlagSpec(
                flag="--log-level",
                value_type="enum",
                enum_values=["DEBUG", "INFO", "WARNING", "ERROR"],
                normalize_upper=False,
            ),
            "--log-file": FlagSpec(flag="--log-file", value_type="str"),
            "--resume-file": FlagSpec(flag="--resume-file", value_type="str"),
            "--leaderboard-mode": FlagSpec(flag="--leaderboard-mode", value_type="int", minimum=1),
            "--limit": FlagSpec(flag="--limit", value_type="int", minimum=1),
            "--days-since-update": FlagSpec(flag="--days-since-update", value_type="int", minimum=1),
            "--max-workers": FlagSpec(flag="--max-workers", value_type="int", minimum=1),
            "--rpm": FlagSpec(flag="--rpm", value_type="int", minimum=1),
            "--save-interval": FlagSpec(flag="--save-interval", value_type="int", minimum=1),
            "--from-db": FlagSpec(flag="--from-db", value_type="bool"),
            "--from-leaderboard": FlagSpec(flag="--from-leaderboard", value_type="bool"),
            "--test": FlagSpec(flag="--test", value_type="bool"),
            "--print-only": FlagSpec(flag="--print-only", value_type="bool"),
            "--status": FlagSpec(flag="--status", value_type="bool"),
            "--no-default-players": FlagSpec(flag="--no-default-players", value_type="bool"),
            "--once": FlagSpec(flag="--once", value_type="bool"),
        },
        "ignored_flags": ["--once"],
    },
    "stb": {
        "script": "crawlers/stb.py",
        "flags": {
            "--once": FlagSpec(flag="--once", value_type="bool"),
            "--skip-test": FlagSpec(flag="--skip-test", value_type="bool"),
            "--source": FlagSpec(
                flag="--source",
                value_type="enum",
                enum_values=["all", "home", "latest", "api"],
            ),
            "--limit": FlagSpec(flag="--limit", value_type="int", target="--max-charts", minimum=1),
            "--rpm": FlagSpec(flag="--rpm", value_type="int", minimum=1),
            "--max-retries": FlagSpec(flag="--max-retries", value_type="int", minimum=1),
            "--cid-crawl": FlagSpec(flag="--cid-crawl", value_type="bool"),
            "--sid-crawl": FlagSpec(flag="--sid-crawl", value_type="bool"),
            "--retry-failed": FlagSpec(flag="--retry-failed", value_type="bool"),
            "--start": FlagSpec(flag="--start", value_type="int", minimum=1),
            "--end": FlagSpec(flag="--end", value_type="int", minimum=1),
            "--resume": FlagSpec(flag="--resume", value_type="str"),
            "--no-resume": FlagSpec(flag="--no-resume", value_type="bool"),
            "--log-level": FlagSpec(
                flag="--log-level",
                value_type="enum",
                enum_values=["DEBUG", "INFO", "WARNING", "ERROR"],
                normalize_upper=True,
            ),
            "--log-file": FlagSpec(flag="--log-file", value_type="str"),
        },
    },
}


def split_cli_args(text: str, colorize: ColorizeFn, red: str) -> Optional[List[str]]:
    try:
        return shlex.split(text) if text else []
    except ValueError as e:
        print(colorize(f"参数解析失败: {e}", red))
        return None


def parse_cli_options(tokens: List[str], colorize: ColorizeFn, red: str) -> Optional[Dict[str, object]]:
    options: Dict[str, object] = {}
    i = 0
    while i < len(tokens):
        token = tokens[i]
        if not token.startswith("--"):
            print(colorize(f"无效参数: {token}", red))
            return None
        if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
            options[token] = tokens[i + 1]
            i += 2
        else:
            options[token] = True
            i += 1
    return options


def parse_positive_int(name: str, value: str, colorize: ColorizeFn, red: str) -> Optional[int]:
    try:
        iv = int(value)
        if iv <= 0:
            raise ValueError()
        return iv
    except Exception:
        print(colorize(f"参数 {name} 必须是正整数: {value}", red))
        return None


def _validate_and_append_flag(
    cmd: List[str],
    flag: str,
    raw_value: object,
    spec: FlagSpec,
    colorize: ColorizeFn,
    red: str,
) -> bool:
    target = spec.target or flag

    if spec.value_type == "bool":
        if raw_value is True:
            cmd.append(target)
        return True

    if not isinstance(raw_value, str):
        print(colorize(f"参数 {flag} 需要值", red))
        return False

    if spec.value_type == "str":
        cmd.extend([target, raw_value])
        return True

    if spec.value_type == "int":
        iv = parse_positive_int(flag, raw_value, colorize, red)
        if iv is None:
            return False
        if spec.minimum is not None and iv < spec.minimum:
            print(colorize(f"参数 {flag} 不能小于 {spec.minimum}", red))
            return False
        if spec.maximum is not None and iv > spec.maximum:
            print(colorize(f"参数 {flag} 不能大于 {spec.maximum}", red))
            return False
        cmd.extend([target, str(iv)])
        return True

    if spec.value_type == "enum":
        enum_values = spec.enum_values or []
        if spec.normalize_upper:
            normalized = raw_value.upper()
            candidate = normalized
            valid_pool = enum_values
        else:
            normalized = raw_value
            candidate = raw_value.lower()
            valid_pool = [item.lower() for item in enum_values]
        if candidate not in valid_pool:
            print(colorize(f"{flag} 仅支持: {'/'.join(enum_values)}", red))
            return False
        cmd.extend([target, normalized])
        return True

    print(colorize(f"参数 {flag} 的规则类型无效: {spec.value_type}", red))
    return False


def _apply_stb_range_mapping(
    cmd: List[str],
    options: Dict[str, object],
    colorize: ColorizeFn,
    red: str,
) -> bool:
    cid_crawl = options.get("--cid-crawl") is True
    sid_crawl = options.get("--sid-crawl") is True

    start_value = options.get("--start")
    if isinstance(start_value, str):
        sv = parse_positive_int("--start", start_value, colorize, red)
        if sv is None:
            return False
        if cid_crawl or (not sid_crawl):
            cmd.extend(["--start-cid", str(sv)])
        if sid_crawl:
            cmd.extend(["--start-sid", str(sv)])

    end_value = options.get("--end")
    if isinstance(end_value, str):
        ev = parse_positive_int("--end", end_value, colorize, red)
        if ev is None:
            return False
        if cid_crawl or (not sid_crawl):
            cmd.extend(["--end-cid", str(ev)])
        if sid_crawl:
            cmd.extend(["--end-sid", str(ev)])

    if "--no-resume" in options:
        cmd.append("--no-resume")
    elif isinstance(options.get("--resume"), str):
        rv = options["--resume"].strip().lower()
        if rv in ["false", "0", "no", "n"]:
            cmd.append("--no-resume")
        elif rv not in ["true", "1", "yes", "y"]:
            print(colorize("--resume 仅支持 true/false", red))
            return False

    return True


def build_update_command(
    tokens: List[str],
    base_dir: str,
    python_executable: str,
    colorize: ColorizeFn,
    red: str,
    yellow: str,
) -> Optional[List[str]]:
    crawler_flags = ["--leaderboard", "--player", "--stb"]
    selected = [f for f in crawler_flags if f in tokens]
    if len(selected) > 1:
        print(colorize("错误: --leaderboard/--player/--stb 只能选一个", red))
        return None

    crawler_type = selected[0].lstrip("-") if selected else "leaderboard"
    schema = UPDATE_OPTION_SCHEMAS[crawler_type]
    script = os.path.join(base_dir, str(schema["script"]))
    cmd = [python_executable, script]

    filtered_tokens = [t for t in tokens if t not in crawler_flags]
    options = parse_cli_options(filtered_tokens, colorize, red)
    if options is None:
        return None

    flag_specs: Dict[str, FlagSpec] = schema["flags"]  # type: ignore[assignment]
    unknown = [k for k in options.keys() if k not in flag_specs]
    if unknown:
        print(colorize(f"{crawler_type} 不支持参数: {', '.join(unknown)}", red))
        return None

    ignored_flags = set(schema.get("ignored_flags", []))
    for flag in ignored_flags:
        if options.get(flag) is True:
            print(colorize(f"提示: {crawler_type} 忽略参数 {flag}", yellow))

    for flag in flag_specs.keys():
        if flag not in options:
            continue
        raw_value = options[flag]
        if flag in ignored_flags:
            continue
        if crawler_type == "stb" and flag in {"--start", "--end", "--resume", "--no-resume"}:
            continue
        spec = flag_specs[flag]
        if not _validate_and_append_flag(cmd, flag, raw_value, spec, colorize, red):
            return None

    if crawler_type == "stb":
        if not _apply_stb_range_mapping(cmd, options, colorize, red):
            return None

    if not options:
        defaults = schema.get("defaults", [])
        for flag in defaults:
            cmd.append(str(flag))

    return cmd


def run_streaming_command(cmd: List[str], colorize: ColorizeFn, cyan: str, green: str, red: str) -> None:
    print(colorize(f"\n开始执行: {' '.join(cmd)}", cyan))
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,
            bufsize=1,
        )
        for line in process.stdout:
            clean_line = re.sub(r"\x1b\[[0-9;]*[mK]", "", line.strip())
            if clean_line:
                print(clean_line)
        process.wait()
        if process.returncode == 0:
            print(colorize("\n数据更新成功!", green))
        else:
            print(colorize(f"\n数据更新失败，退出码: {process.returncode}", red))
    except Exception as e:
        print(colorize(f"\n更新过程中发生错误: {e}", red))
