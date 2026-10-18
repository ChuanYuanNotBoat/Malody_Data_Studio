# malody_stats.py
import argparse
import atexit
import cmd
import os
import shutil
import signal
import sqlite3
import sys
from datetime import datetime
from functools import wraps
from typing import List, Optional

import matplotlib.pyplot as plt

from selector import global_selector
from stats_cli.plugins.registry import install_plugins


# 修复matplotlib中文字体问题
def setup_chinese_font():
    """设置中文字体支持（增强版）"""
    import matplotlib.pyplot as plt
    import matplotlib.font_manager as fm
    import platform
    import os

    # 常见中文字体名称（按优先级排序）
    chinese_font_names = [
        'Microsoft YaHei',        # Windows
        'SimHei',                  # Windows
        'PingFang SC',             # macOS
        'STHeiti',                 # macOS
        'WenQuanYi Micro Hei',     # Linux
        'Noto Sans CJK SC',        # Linux
        'Droid Sans Fallback',     # Android
    ]

    # 如果系统是 Windows，可以指定完整路径（备选）
    if platform.system() == 'Windows':
        # 尝试从系统字体目录加载
        win_font_dir = os.path.join(os.environ.get('WINDIR', 'C:\\Windows'), 'Fonts')
        win_fonts = {
            'Microsoft YaHei': os.path.join(win_font_dir, 'msyh.ttc'),
            'SimHei': os.path.join(win_font_dir, 'simhei.ttf'),
        }
        for name, path in win_fonts.items():
            if os.path.exists(path):
                fm.fontManager.addfont(path)
                chinese_font_names.insert(0, name)  # 优先使用已找到的字体

    # 查找系统中可用的中文字体
    available_fonts = set(f.name for f in fm.fontManager.ttflist)
    found_font = None
    for font_name in chinese_font_names:
        if font_name in available_fonts:
            found_font = font_name
            break

    if found_font:
        plt.rcParams['font.sans-serif'] = [found_font] + plt.rcParams['font.sans-serif']
        plt.rcParams['axes.unicode_minus'] = False
        print(f"已设置中文字体: {found_font}")
        return True
    else:
        print("警告: 未找到支持中文的字体，图表中的中文可能显示为方块")
        print("可尝试手动安装以下字体之一: " + ", ".join(chinese_font_names))
        return False

# 在程序初始化时调用字体设置
setup_chinese_font()


# PowerShell 颜色支持修复
def enable_powershell_colors():
    """在 PowerShell 中启用 ANSI 颜色支持"""
    if sys.platform == "win32":
        try:
            # 方法1: 通过设置环境变量启用虚拟终端
            os.environ["TERM"] = "xterm-256color"

            # 方法2: 使用 ctypes 启用虚拟终端处理
            if hasattr(sys, 'getwindowsversion'):
                import ctypes
                from ctypes import wintypes

                kernel32 = ctypes.windll.kernel32
                STD_OUTPUT_HANDLE = -11

                # 获取标准输出句柄
                hstdout = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)

                # 获取当前控制台模式
                mode = wintypes.DWORD()
                if kernel32.GetConsoleMode(hstdout, ctypes.byref(mode)):
                    # 启用虚拟终端处理
                    ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                    new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
                    kernel32.SetConsoleMode(hstdout, new_mode)
                    return True
        except:
            pass
    return False

# 在程序启动时启用 PowerShell 颜色
enable_powershell_colors()

# 修复Python 3.12中SQLite datetime适配器的弃用警告
def adapt_datetime(dt):
    return dt.isoformat()

def convert_datetime(s):
    return datetime.fromisoformat(s.decode())

sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("timestamp", convert_datetime)

# 设置matplotlib使用Agg后端（无GUI）
plt.switch_backend('Agg')

# 设置图表字体颜色为深色，避免与背景冲突
plt.rcParams['text.color'] = 'black'
plt.rcParams['axes.labelcolor'] = 'black'
plt.rcParams['xtick.color'] = 'black'
plt.rcParams['ytick.color'] = 'black'
plt.rcParams['axes.titlecolor'] = 'black'

# 颜色定义 (ANSI转义码)
class Colors:
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def color_enabled():
    """检查当前环境是否支持颜色输出"""
    if sys.platform == "win32":
        # 在 Windows 上检查是否在支持颜色的终端中运行
        try:
            # 检查是否在 Windows Terminal、PowerShell 5.1+ 或支持 ANSI 的 CMD 中运行
            term_program = os.environ.get('TERM_PROGRAM', '')
            term = os.environ.get('TERM', '')

            # Windows Terminal 或现代 PowerShell
            if 'WindowsTerminal' in term_program or 'TERM' in os.environ:
                return True

            # 检查 PowerShell 版本（5.1+ 支持 ANSI）
            import subprocess
            result = subprocess.run(['powershell', '$PSVersionTable.PSVersion.Major'],
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout.strip().isdigit():
                ps_version = int(result.stdout.strip())
                if ps_version >= 5:
                    return True

            # 最后的手段：尝试检测控制台能力
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            STD_OUTPUT_HANDLE = -11
            hstdout = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)

            mode = wintypes.DWORD()
            if kernel32.GetConsoleMode(hstdout, ctypes.byref(mode)):
                ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
                return (mode.value & ENABLE_VIRTUAL_TERMINAL_PROCESSING) != 0

        except:
            pass
        return False
    else:
        # 非 Windows 系统通常支持颜色
        return True

def colorize(text, color):
    """有条件地添加颜色到文本"""
    if color_enabled():
        return f"{color}{text}{Colors.END}"
    return text

def db_safe_operation(func):
    """装饰器用于确保数据库操作安全"""
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except sqlite3.Error as e:
            print(colorize(f"数据库错误: {e}", Colors.RED))
            return False
        except Exception as e:
            print(colorize(f"操作错误: {e}", Colors.RED))
            return False
    return wrapper

def format_change(change_value, reverse=False, is_percent=False):
    """格式化变化值，添加颜色"""
    if change_value is None:
        return "N/A"

    if change_value == 0:
        return "0"

    if is_percent:
        change_str = f"{change_value:+.2f}%"
    else:
        change_str = f"{change_value:+d}"

    # 对于排名变化，负数表示进步（排名上升）
    if reverse:
        if change_value < 0:
            return colorize(change_str, Colors.GREEN)  # 进步
        elif change_value > 0:
            return colorize(change_str, Colors.RED)    # 退步
    else:
        if change_value > 0:
            return colorize(change_str, Colors.GREEN)  # 增加
        elif change_value < 0:
            return colorize(change_str, Colors.RED)    # 减少

    return change_str

def format_number(number):
    """格式化大数字，添加千位分隔符"""
    if number is None:
        return "N/A"
    return f"{number:,}"

def get_terminal_width():
    """获取终端宽度"""
    try:
        return shutil.get_terminal_size().columns
    except:
        return 80

def get_separator(width=None):
    """获取自适应分隔线"""
    if width is None:
        width = get_terminal_width()
    return colorize("=" * min(width, 120), Colors.CYAN)

def get_subseparator(width=None):
    """获取自适应子分隔线"""
    if width is None:
        width = get_terminal_width()
    return colorize("-" * min(width, 100), Colors.CYAN)

def _resolve_db_path() -> str:
    configured_path = os.getenv("MALODY_DB_PATH")
    if configured_path:
        return configured_path
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    data_path = os.path.join(root, "data", "malody_rankings.db")
    if os.path.exists(data_path):
        return data_path
    return os.path.join(root, "malody_rankings.db")


class MalodyViz(cmd.Cmd):
    """Malody排行榜数据可视化工具"""

    intro = colorize("\n欢迎使用Malody排行榜数据可视化工具!\n\n", Colors.CYAN) + \
            "输入 " + colorize("help", Colors.GREEN) + " 或 " + colorize("?", Colors.GREEN) + " 查看命令列表。\n" + \
            "输入 " + colorize("help <命令名>", Colors.GREEN) + " 查看具体命令的详细说明。\n\n" + \
            "所有生成的图表将保存在 " + colorize("viz_output", Colors.YELLOW) + " 目录中。\n" + \
            "提示: 可以使用 " + colorize("ls", Colors.GREEN) + " 命令查看当前目录文件。\n"
    prompt = colorize("(malody-viz) ", Colors.BLUE)

    def __init__(self):
        super().__init__()
        self.db_path = _resolve_db_path()
        self.conn = None
        self.current_mode = -1  # -1 表示所有模式
        self.output_dir = "viz_output"

        atexit.register(self.cleanup)
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir)

        self.connect_db()

        # 初始化选择器
        self.selector = global_selector
        self.selector.current_mode = self.current_mode

        self.mode_names = {
            -1: "All",  # 所有模式
            0: "Key",
            1: "Step",
            2: "DJ",
            3: "Catch",
            4: "Pad",
            5: "Taiko",
            6: "Ring",
            7: "Slide",
            8: "Live",
            9: "Cube"
        }

        # 自动修复数据库问题
        self.auto_repair_database()

    def connect_db(self):
        """连接到SQLite数据库"""
        try:
            self.conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False
            )
            self.conn.execute("PRAGMA foreign_keys = ON")
            self.conn.execute("PRAGMA busy_timeout = 3000")
            print(colorize(f"成功连接到数据库: {self.db_path}", Colors.GREEN))
        except sqlite3.Error as e:
            print(colorize(f"数据库连接错误: {e}", Colors.RED))
            sys.exit(1)

    def cleanup(self):
        """清理资源"""
        if self.conn:
            try:
                self.conn.close()
                print(colorize("\n数据库连接已安全关闭", Colors.GREEN))
            except:
                pass

    def signal_handler(self, signum, frame):
        """处理中断信号"""
        print(colorize("\n正在安全退出...", Colors.YELLOW))
        self.cleanup()
        sys.exit(0)

    def emptyline(self):
        """空行时不执行任何操作"""
        pass

    def get_unique_filename(self, base_name, extension):
        """生成不重复的文件名，添加时间戳"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name_only = os.path.splitext(base_name)[0]
        return f"{name_only}_{timestamp}.{extension}"

    @db_safe_operation
    def auto_repair_database(self):
        """
        自动修复数据库常见问题
        """
        cursor = self.conn.cursor()

        print(colorize("\n正在检查数据库状态...", Colors.CYAN))

        try:
            # 检查数据库完整性
            cursor.execute("PRAGMA integrity_check")
            integrity_result = cursor.fetchone()[0]

            issues_found = []

            if integrity_result != "ok":
                issues_found.append(f"数据库完整性: {integrity_result}")
                print(colorize(f"发现数据库完整性问题: {integrity_result}", Colors.YELLOW))

            # 检查已知状态不一致问题
            known_issues = [
                (139970, 1),  # CID 139970 应该是状态1
                # 可以在这里添加其他已知的问题CID和正确状态
            ]
            pending_known_issue_fixes = []
            for cid, correct_status in known_issues:
                cursor.execute("SELECT status FROM charts WHERE cid = ?", (cid,))
                current_status = cursor.fetchone()
                if current_status and current_status[0] != correct_status:
                    pending_known_issue_fixes.append((cid, current_status[0], correct_status))

            if pending_known_issue_fixes:
                issues_found.append(f"known_status_mismatch:{len(pending_known_issue_fixes)}")
                print(colorize(f"发现 {len(pending_known_issue_fixes)} 个已知状态不一致问题", Colors.YELLOW))

            # 如果有问题，自动修复
            if issues_found:
                print(colorize(f"发现 {len(issues_found)} 个问题，正在自动修复...", Colors.YELLOW))

                # 修复索引
                print("修复数据库索引...")
                cursor.execute("REINDEX")

                # 清理数据库
                print("清理数据库...")
                cursor.execute("VACUUM")

                # 修复已知的状态不一致问题
                print("修复状态不一致问题...")
                for cid, old_status, correct_status in pending_known_issue_fixes:
                    cursor.execute("UPDATE charts SET status = ? WHERE cid = ?", (correct_status, cid))
                    print(f"  修复 CID {cid}: 状态 {old_status} -> {correct_status}")

                self.conn.commit()

                # 验证修复结果
                cursor.execute("PRAGMA integrity_check")
                new_integrity = cursor.fetchone()[0]

                if new_integrity == "ok":
                    print(colorize("自动修复完成！数据库现在正常。", Colors.GREEN))
                else:
                    print(colorize(f"修复后完整性检查: {new_integrity}", Colors.YELLOW))

            else:
                print(colorize("数据库状态正常，无需修复。", Colors.GREEN))

        except Exception as e:
            print(colorize(f"自动修复过程中发生错误: {e}", Colors.RED))
    # 增强 do_update 命令


    def print_topics(self, header, cmds, cmdlen, maxcol):
        if cmds:
            self.stdout.write(colorize("%s\n" % str(header), Colors.CYAN))
            if self.ruler:
                self.stdout.write(colorize("%s\n" % str(self.ruler * len(header)), Colors.CYAN))
            self.columnize(cmds, maxcol-1)
            self.stdout.write("\n")


install_plugins(
    MalodyViz,
    colorize=colorize,
    colors=Colors,
    db_safe_operation=db_safe_operation,
    get_separator=get_separator,
    get_subseparator=get_subseparator,
    get_terminal_width=get_terminal_width,
    base_dir=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
)


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="malody_stats",
        add_help=True,
        description="Malody stats CLI",
    )
    parser.add_argument(
        "-c",
        "--command",
        action="append",
        default=[],
        help="Execute a command and exit. Can be used multiple times.",
    )
    parser.add_argument(
        "command_args",
        nargs=argparse.REMAINDER,
        help="Command tokens to execute directly, e.g. malody_stats mode 3",
    )
    return parser


def _execute_commands(shell: "MalodyViz", commands: list[str]) -> int:
    setattr(shell, "_non_interactive", True)
    for command_text in commands:
        cmd_text = command_text.strip()
        if not cmd_text:
            continue
        try:
            stop = shell.onecmd(cmd_text)
            if stop:
                break
        except Exception as e:
            print(colorize(f"Command failed '{cmd_text}': {e}", Colors.RED))
            return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    db_path = _resolve_db_path()
    if not os.path.exists(db_path):
        print(colorize(f"Error: database file '{db_path}' not found", Colors.RED))
        print(colorize("Please set MALODY_DB_PATH or place the database in data/", Colors.YELLOW))
        return 1

    try:
        parser = _build_cli_parser()
        args = parser.parse_args(argv)
        app = MalodyViz()

        commands = list(args.command or [])
        if args.command_args:
            direct_command = " ".join(args.command_args).strip()
            if direct_command:
                commands.append(direct_command)

        if commands:
            return _execute_commands(app, commands)

        app.cmdloop()
        return 0
    except KeyboardInterrupt:
        print(colorize("\nInterrupted by user", Colors.YELLOW))
        return 130
    except Exception as e:
        print(colorize(f"\nProgram error: {e}", Colors.RED))
        return 1


if __name__ == "__main__":
    sys.exit(main())
