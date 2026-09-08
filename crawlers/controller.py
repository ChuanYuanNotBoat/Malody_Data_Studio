#!/usr/bin/env python3
"""
爬虫控制器 - 支持IMAP接收邮件命令 + 预设参数展开 + QQ外发报告 + 本地Shell测试
"""

import argparse
import cmd
import email
import imaplib
import json
import logging
import os
import signal
import smtplib
import subprocess
import sys
import threading
import time
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Dict, List, Optional, Any

import yaml

# 确保日志目录存在
os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("logs/controller.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("CrawlerController")

CONFIG_FILE = os.path.join("data", "config.yaml")
if not os.path.exists(CONFIG_FILE) and os.path.exists("config.yaml"):
    # 兼容旧的根目录布局
    CONFIG_FILE = "config.yaml"
RUNNING_PIDS_FILE = "running_pids.json"


def _set_nested(config: dict, path: List[str], value: Any):
    node = config
    for key in path[:-1]:
        if key not in node or not isinstance(node[key], dict):
            node[key] = {}
        node = node[key]
    node[path[-1]] = value


def _apply_env_overrides(config: dict) -> dict:
    """
    Allow sensitive config to be provided by env vars, so credentials
    do not need to be hardcoded in config.yaml.
    """
    mapping = {
        "MALODY_MAIL_SMTP_USERNAME": ["mail", "smtp_out", "username"],
        "MALODY_MAIL_SMTP_PASSWORD": ["mail", "smtp_out", "password"],
        "MALODY_MAIL_SMTP_FROM_ADDR": ["mail", "smtp_out", "from_addr"],
        "MALODY_MAIL_IMAP_USERNAME": ["mail", "imap", "username"],
        "MALODY_MAIL_IMAP_PASSWORD": ["mail", "imap", "password"],
        "MALODY_REPORT_TO": ["report_to"],
    }

    for env_name, nested_path in mapping.items():
        value = os.getenv(env_name)
        if value:
            _set_nested(config, nested_path, value)

    allowed_senders = os.getenv("MALODY_ALLOWED_SENDERS")
    if allowed_senders:
        config["allowed_senders"] = [
            s.strip() for s in allowed_senders.split(",") if s.strip()
        ]

    return config


class Mailer:
    """邮件发送（外部 SMTP）"""
    def __init__(self, config: dict):
        self.smtp_config = config['smtp_out']
        self.from_addr = self.smtp_config.get('from_addr')

    def send(self, subject: str, body: str, to_addr: str) -> bool:
        msg = MIMEMultipart()
        msg['From'] = self.from_addr
        msg['To'] = to_addr
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain', 'utf-8'))

        try:
            if self.smtp_config.get('use_tls'):
                server = smtplib.SMTP(self.smtp_config['server'], self.smtp_config['port'])
                server.starttls()
            else:
                server = smtplib.SMTP_SSL(self.smtp_config['server'], self.smtp_config['port']) \
                    if self.smtp_config.get('use_ssl') else \
                    smtplib.SMTP(self.smtp_config['server'], self.smtp_config['port'])

            server.login(self.smtp_config['username'], self.smtp_config['password'])
            server.send_message(msg)
            server.quit()
            logger.info(f"邮件发送成功至 {to_addr}: {subject}")
            return True
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            return False


class CrawlerManager:
    """管理爬虫进程"""
    def __init__(self, config: dict):
        self.crawlers_config = config['crawlers']
        self.running = self._load_running_pids()

    def _load_running_pids(self) -> Dict[str, dict]:
        if os.path.exists(RUNNING_PIDS_FILE):
            try:
                with open(RUNNING_PIDS_FILE, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_running_pids(self):
        with open(RUNNING_PIDS_FILE, 'w') as f:
            json.dump(self.running, f, indent=2)

    def _expand_preset_args(self, crawler_name: str, args: List[str]) -> List[str]:
        """将预设名称展开为实际参数列表"""
        presets = self.crawlers_config.get(crawler_name, {}).get('presets', {})
        expanded = []
        for arg in args:
            if arg in presets:
                expanded.extend(presets[arg])
            else:
                expanded.append(arg)
        return expanded

    def run_once(self, crawler_name: str, args: List[str], timeout: int = None) -> Dict[str, Any]:
        crawler_info = self.crawlers_config.get(crawler_name)
        if not crawler_info:
            raise ValueError(f"未知爬虫: {crawler_name}")

        script = crawler_info['script']
        if not os.path.exists(script):
            raise FileNotFoundError(f"脚本不存在: {script}")

        # 展开预设参数
        expanded_args = self._expand_preset_args(crawler_name, args)
        cmd = [sys.executable, script] + expanded_args
        logger.info(f"运行命令: {' '.join(cmd)}")

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            returncode = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
        except subprocess.TimeoutExpired as e:
            stdout = e.stdout.decode() if e.stdout else ""
            stderr = e.stderr.decode() if e.stderr else ""
            returncode = -1
            logger.warning(f"爬虫 {crawler_name} 超时")

        full_output = stdout + "\n" + stderr
        return {
            'returncode': returncode,
            'stdout': stdout,
            'stderr': stderr,
            'full_output': full_output,
            'cmd': cmd
        }

    def start_daemon(self, crawler_name: str, args: List[str]) -> bool:
        crawler_info = self.crawlers_config.get(crawler_name)
        if not crawler_info:
            raise ValueError(f"未知爬虫: {crawler_name}")

        if crawler_name in self.running:
            logger.warning(f"爬虫 {crawler_name} 已经在运行 (PID: {self.running[crawler_name]['pid']})")
            return False

        script = crawler_info['script']
        if not os.path.exists(script):
            raise FileNotFoundError(f"脚本不存在: {script}")

        # 展开预设参数
        expanded_args = self._expand_preset_args(crawler_name, args)
        cmd = [sys.executable, script] + expanded_args
        logger.info(f"启动后台进程: {' '.join(cmd)}")

        os.makedirs("logs", exist_ok=True)
        log_file = open(f"logs/{crawler_name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log", 'w')
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL
        )
        log_file.close()

        self.running[crawler_name] = {
            'pid': proc.pid,
            'start_time': datetime.now().isoformat(),
            'args': args,  # 保存原始参数，便于显示
            'expanded_args': expanded_args,
            'log_file': log_file.name
        }
        self._save_running_pids()
        logger.info(f"后台进程 {crawler_name} 已启动，PID: {proc.pid}")
        return True

    def stop_daemon(self, crawler_name: str, wait_timeout: int = 30) -> Optional[str]:
        if crawler_name not in self.running:
            logger.warning(f"爬虫 {crawler_name} 未在运行")
            return None

        pid = self.running[crawler_name]['pid']
        log_file = self.running[crawler_name]['log_file']
        logger.info(f"正在停止爬虫 {crawler_name} (PID: {pid})")

        try:
            os.kill(pid, signal.SIGINT)
        except ProcessLookupError:
            logger.warning(f"进程 {pid} 已不存在")
            del self.running[crawler_name]
            self._save_running_pids()
            return None

        start_wait = time.time()
        while time.time() - start_wait < wait_timeout:
            try:
                os.kill(pid, 0)
                time.sleep(1)
            except ProcessLookupError:
                break
        else:
            logger.warning(f"进程 {pid} 在超时后仍未退出，强制终止")
            try:
                os.kill(pid, signal.SIGKILL)
            except:
                pass

        recent_output = ""
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    recent_lines = lines[-200:] if len(lines) > 200 else lines
                    recent_output = ''.join(recent_lines)
            except Exception as e:
                logger.error(f"读取日志文件失败: {e}")

        del self.running[crawler_name]
        self._save_running_pids()
        return recent_output

    def list_running(self) -> Dict:
        to_remove = []
        for name, info in self.running.items():
            pid = info['pid']
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                logger.warning(f"进程 {pid} 已消失，清理记录")
                to_remove.append(name)
        for name in to_remove:
            del self.running[name]
        if to_remove:
            self._save_running_pids()
        return self.running


class CommandParser:
    @staticmethod
    def parse_command(text: str):
        text = text.strip()
        if not text.startswith('/'):
            return None

        parts = text.split()
        if len(parts) == 0:
            return None

        cmd = parts[0][1:]  # 去掉 '/'
        if cmd == 'run':
            if len(parts) < 2:
                return {'action': 'run', 'crawler': None, 'args': []}
            return {
                'action': 'run',
                'crawler': parts[1],
                'args': parts[2:]
            }
        elif cmd == 'start':
            if len(parts) < 2:
                return {'action': 'start', 'crawler': None, 'args': []}
            return {
                'action': 'start',
                'crawler': parts[1],
                'args': parts[2:]
            }
        elif cmd == 'stop':
            if len(parts) < 2:
                return {'action': 'stop', 'crawler': None}
            return {
                'action': 'stop',
                'crawler': parts[1]
            }
        elif cmd == 'status':
            return {'action': 'status'}
        else:
            return {'action': 'unknown', 'raw': text}


def load_config():
    if not os.path.exists(CONFIG_FILE):
        logger.error(f"Config file {CONFIG_FILE} not found")
        sys.exit(1)
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return _apply_env_overrides(config or {})


def handle_command(cmd: dict, manager: CrawlerManager, mailer: Mailer = None, reply_to: str = None) -> str:
    """执行命令，如果mailer和reply_to不为空，则发送邮件报告"""
    action = cmd.get('action')
    if action == 'run':
        crawler = cmd.get('crawler')
        args = cmd.get('args', [])
        if not crawler:
            return "错误：未指定爬虫名称"
        try:
            result = manager.run_once(crawler, args)
            output = result['full_output']
            if mailer and reply_to:
                subject = f"[爬虫] {crawler} 运行完成 (返回码 {result['returncode']})"
                mailer.send(subject, output, reply_to)
                return f"已运行 {crawler}，结果已发送至 {reply_to}"
            else:
                return output
        except Exception as e:
            error_msg = f"运行失败: {e}"
            if mailer and reply_to:
                mailer.send(f"[爬虫] {crawler} 运行失败", error_msg, reply_to)
                return f"运行失败，错误已发送至 {reply_to}"
            else:
                return error_msg

    elif action == 'start':
        crawler = cmd.get('crawler')
        args = cmd.get('args', [])
        if not crawler:
            return "错误：未指定爬虫名称"
        try:
            if manager.start_daemon(crawler, args):
                msg = f"已启动后台爬虫 {crawler}"
                if mailer and reply_to:
                    mailer.send(f"[爬虫] {crawler} 已启动", msg, reply_to)
                    return f"{msg}，通知已发送至 {reply_to}"
                else:
                    return msg
            else:
                msg = f"爬虫 {crawler} 可能已经在运行"
                if mailer and reply_to:
                    mailer.send(f"[爬虫] {crawler} 启动失败", msg, reply_to)
                    return f"{msg}，通知已发送至 {reply_to}"
                else:
                    return msg
        except Exception as e:
            error_msg = f"启动失败: {e}"
            if mailer and reply_to:
                mailer.send(f"[爬虫] {crawler} 启动异常", error_msg, reply_to)
                return f"启动异常，错误已发送至 {reply_to}"
            else:
                return error_msg

    elif action == 'stop':
        crawler = cmd.get('crawler')
        if not crawler:
            return "错误：未指定爬虫名称"
        output = manager.stop_daemon(crawler)
        if output is not None:
            if mailer and reply_to:
                subject = f"[爬虫] {crawler} 已停止（最近输出）"
                mailer.send(subject, output, reply_to)
                return f"已停止 {crawler}，最近输出已发送至 {reply_to}"
            else:
                return f"已停止 {crawler}，最近输出如下：\n{output}"
        else:
            msg = f"爬虫 {crawler} 未运行"
            if mailer and reply_to:
                mailer.send(f"[爬虫] {crawler} 停止操作", msg, reply_to)
                return f"{msg}，通知已发送至 {reply_to}"
            else:
                return msg

    elif action == 'status':
        running = manager.list_running()
        if not running:
            msg = "当前没有正在运行的爬虫"
        else:
            lines = ["正在运行的爬虫："]
            for name, info in running.items():
                lines.append(f"  {name}: PID {info['pid']}, 启动于 {info['start_time']}")
            msg = "\n".join(lines)
        if mailer and reply_to:
            mailer.send("[爬虫] 当前状态", msg, reply_to)
            return f"状态信息已发送至 {reply_to}"
        else:
            return msg

    else:
        msg = f"未知命令: {cmd.get('raw', '')}"
        if mailer and reply_to:
            mailer.send("[爬虫] 未知命令", msg, reply_to)
            return f"未知命令，通知已发送至 {reply_to}"
        else:
            return msg


class IMAPListener:
    """IMAP邮件监听器"""
    def __init__(self, config: dict, manager: CrawlerManager, mailer: Mailer):
        self.imap_config = config['mail']['imap']
        self.allowed_senders = config.get('allowed_senders', [])
        self.manager = manager
        self.mailer = mailer
        self.running = True

    def check_and_process(self):
        """检查一次收件箱，处理未读命令邮件"""
        try:
            if self.imap_config.get('use_ssl'):
                conn = imaplib.IMAP4_SSL(self.imap_config['server'], self.imap_config['port'])
            else:
                conn = imaplib.IMAP4(self.imap_config['server'], self.imap_config['port'])
            conn.login(self.imap_config['username'], self.imap_config['password'])
            conn.select('INBOX')

            # 搜索未读邮件
            typ, data = conn.search(None, 'UNSEEN')
            for num in data[0].split():
                typ, msg_data = conn.fetch(num, '(RFC822)')
                msg = email.message_from_bytes(msg_data[0][1])
                from_addr = email.utils.parseaddr(msg.get('From'))[1]
                subject = msg.get('Subject', '').strip()
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors='ignore')
                            break
                else:
                    body = msg.get_payload(decode=True).decode(errors='ignore')

                logger.info(f"IMAP: 收到来自 {from_addr} 的邮件，主题: {subject}")

                # 检查发件人白名单
                if self.allowed_senders and from_addr not in self.allowed_senders:
                    logger.warning(f"忽略来自未授权地址的邮件: {from_addr}")
                    # 仍标记为已读，避免重复提醒
                    conn.store(num, '+FLAGS', '\\Seen')
                    continue

                cmd = CommandParser.parse_command(subject)
                if not cmd:
                    cmd = CommandParser.parse_command(body)

                if cmd:
                    logger.info(f"解析到命令: {cmd}")
                    # 异步处理，避免阻塞IMAP连接
                    threading.Thread(target=self._process_command, args=(cmd, from_addr)).start()
                else:
                    logger.info("邮件未包含有效命令，忽略")

                # 标记为已读
                conn.store(num, '+FLAGS', '\\Seen')

            conn.close()
            conn.logout()
        except Exception as e:
            logger.error(f"IMAP检查失败: {e}")

    def _process_command(self, cmd: dict, reply_to: str):
        """处理命令并发送回复"""
        try:
            response = handle_command(cmd, self.manager, self.mailer, reply_to)
            logger.info(f"命令处理结果: {response}")
        except Exception as e:
            logger.error(f"处理命令异常: {e}")
            # 异常时也尝试发送错误邮件
            error_msg = f"处理命令时发生未预期异常: {e}"
            self.mailer.send("[爬虫] 命令处理异常", error_msg, reply_to)

    def start_loop(self, interval=60):
        """启动循环，每隔interval秒检查一次"""
        logger.info(f"IMAP监听循环已启动，检查间隔 {interval} 秒")
        while self.running:
            self.check_and_process()
            # 逐秒检查停止标志，避免长时间sleep
            for _ in range(interval):
                if not self.running:
                    break
                time.sleep(1)


class Shell(cmd.Cmd):
    """交互式命令行，用于本地测试"""
    intro = "爬虫控制器本地Shell。输入命令 (如 /run player_profile --uid 123) 或 ? 查看帮助。输入 exit 退出。\n"
    prompt = "(crawler) "

    def __init__(self, manager, mailer):
        super().__init__()
        self.manager = manager
        self.mailer = mailer

    def default(self, line):
        if line.strip() == 'exit':
            return self.do_exit('')
        cmd = CommandParser.parse_command(line)
        if cmd:
            response = handle_command(cmd, self.manager, self.mailer, None)
            print(response)
        else:
            print(f"无效命令: {line}")

    def do_exit(self, arg):
        print("退出Shell")
        return True

    def do_EOF(self, arg):
        return self.do_exit(arg)


def main():
    # 确保日志目录存在
    os.makedirs("logs", exist_ok=True)

    parser = argparse.ArgumentParser(description="爬虫控制器")
    subparsers = parser.add_subparsers(dest='command', help='子命令')

    # 原有命令
    run_parser = subparsers.add_parser('run', help='运行爬虫一次并邮件结果')
    run_parser.add_argument('crawler', help='爬虫名称')
    run_parser.add_argument('args', nargs=argparse.REMAINDER, help='传递给爬虫的参数')

    start_parser = subparsers.add_parser('start', help='启动后台爬虫（无限循环）')
    start_parser.add_argument('crawler', help='爬虫名称')
    start_parser.add_argument('args', nargs=argparse.REMAINDER, help='传递给爬虫的参数')

    stop_parser = subparsers.add_parser('stop', help='停止后台爬虫')
    stop_parser.add_argument('crawler', help='爬虫名称')

    status_parser = subparsers.add_parser('status', help='查看正在运行的爬虫')

    # 本地Shell
    shell_parser = subparsers.add_parser('shell', help='启动交互式命令行（本地测试）')

    # IMAP监听模式（主要使用）
    imap_parser = subparsers.add_parser('imap-listen', help='启动IMAP邮件监听（从配置的邮箱读取命令）')

    # 内置SMTP服务器（可选，保留）
    smtp_parser = subparsers.add_parser('smtp-server', help='启动内置 SMTP 服务器（接收命令邮件）')

    args = parser.parse_args()

    config = load_config()
    manager = CrawlerManager(config)
    mailer = Mailer(config['mail'])

    # 从配置读取报告接收邮箱（可选）
    report_to = config.get('report_to')  # 如果配置中没有，则为 None

    if args.command == 'run':
        try:
            result = manager.run_once(args.crawler, args.args)
            print(result['full_output'])
            # 发送结果到指定邮箱（从配置读取）
            if report_to:
                mailer.send(f"[爬虫] {args.crawler} 运行完成", result['full_output'], report_to)
            else:
                logger.warning("未配置 report_to，结果不会通过邮件发送")
        except Exception as e:
            logger.error(f"运行失败: {e}")
            sys.exit(1)

    elif args.command == 'start':
        try:
            if manager.start_daemon(args.crawler, args.args):
                print(f"后台爬虫 {args.crawler} 已启动")
            else:
                print(f"爬虫 {args.crawler} 已在运行")
        except Exception as e:
            print(f"启动失败: {e}")
            sys.exit(1)

    elif args.command == 'stop':
        output = manager.stop_daemon(args.crawler)
        if output is not None:
            print(f"爬虫 {args.crawler} 已停止，最近输出如下：")
            print(output)
            if report_to:
                mailer.send(f"[爬虫] {args.crawler} 已停止", output, report_to)
        else:
            print(f"爬虫 {args.crawler} 未在运行")

    elif args.command == 'status':
        running = manager.list_running()
        if not running:
            print("没有正在运行的爬虫")
        else:
            print("正在运行的爬虫：")
            for name, info in running.items():
                print(f"  {name}: PID {info['pid']}, 启动于 {info['start_time']}")

    elif args.command == 'shell':
        Shell(manager, mailer).cmdloop()

    elif args.command == 'imap-listen':
        # 检查配置中是否启用了imap
        if not config['mail'].get('imap', {}).get('enabled'):
            logger.error("配置文件中未启用 imap，请在 mail.imap 中设置 enabled: true")
            sys.exit(1)
        listener = IMAPListener(config, manager, mailer)
        try:
            listener.start_loop(interval=60)  # 每分钟检查一次
        except KeyboardInterrupt:
            logger.info("收到中断信号，正在停止IMAP监听...")
            listener.running = False
            logger.info("IMAP监听已停止")

    elif args.command == 'smtp-server':
        # 可选的内置SMTP服务器模式，需要安装aiosmtpd
        try:
            from aiosmtpd.controller import Controller
            from aiosmtpd.smtp import SMTP, Session, Envelope
        except ImportError:
            logger.error("aiosmtpd未安装，无法启动SMTP服务器。运行 pip install aiosmtpd")
            sys.exit(1)

        smtp_in_config = config['mail'].get('smtp_in', {})
        if not smtp_in_config.get('enabled'):
            logger.error("配置文件中未启用 smtp_in")
            sys.exit(1)

        class MailHandler:
            def __init__(self, manager, mailer, allowed_senders):
                self.manager = manager
                self.mailer = mailer
                self.allowed_senders = allowed_senders

            async def handle_DATA(self, server, session, envelope):
                msg = email.message_from_bytes(envelope.content)
                from_addr = email.utils.parseaddr(msg.get('From'))[1]
                subject = msg.get('Subject', '').strip()
                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() == "text/plain":
                            body = part.get_payload(decode=True).decode(errors='ignore')
                            break
                else:
                    body = msg.get_payload(decode=True).decode(errors='ignore')

                logger.info(f"SMTP: 收到来自 {from_addr} 的邮件，主题: {subject}")

                if self.allowed_senders and from_addr not in self.allowed_senders:
                    logger.warning(f"忽略来自未授权地址的邮件: {from_addr}")
                    return "250 OK"

                cmd = CommandParser.parse_command(subject)
                if not cmd:
                    cmd = CommandParser.parse_command(body)

                if cmd:
                    threading.Thread(target=self._process_command, args=(cmd, from_addr)).start()
                return "250 OK"

            def _process_command(self, cmd, reply_to):
                handle_command(cmd, self.manager, self.mailer, reply_to)

        handler = MailHandler(manager, mailer, config.get('allowed_senders', []))
        controller = Controller(handler, hostname=smtp_in_config['host'], port=smtp_in_config['port'])
        controller.start()
        logger.info(f"内置SMTP服务器已启动，监听 {smtp_in_config['host']}:{smtp_in_config['port']}")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            controller.stop()
            logger.info("SMTP服务器已停止")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
