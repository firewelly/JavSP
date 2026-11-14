"""各抓取器共享的Playwright持久化会话工具

- 所有站点共用同一个持久化浏览器profile，年龄验证/登录态/Cloudflare通行证等
  cookie跨影片、跨运行保留，避免每次都以"陌生访客"身份触发风控
- 目录结构与media项目的.playwright_user_data一致，可直接拷贝对方profile作种子
- 优先使用msedge真实浏览器通道（指纹更接近真人），不可用时回退内置chromium
"""
import os
import time
import logging
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError


logger = logging.getLogger(__name__)

PLAYWRIGHT_PROFILE_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    '.playwright_user_data')

DEFAULT_UA = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0'
)


def launch_context(p, proxy=None, user_agent=DEFAULT_UA,
                   viewport={'width': 1440, 'height': 2400}, extra_args=(),
                   headless=None):
    """启动带持久化profile的浏览器上下文

    默认无头运行；设置环境变量 JAVSP_HEADLESS=0 可用有头模式（便于人工观察
    页面加载、登录态与验证页的实际状态）。显式传入headless参数时优先生效

    Returns:
        (browser, context): browser为None时context即持久化上下文（关闭时只需context.close()）；
        profile被占用或通道不可用等情况下退回全新临时上下文（无cookie持久化）
    """
    if headless is None:
        headless = os.getenv('JAVSP_HEADLESS', '1').strip().lower() not in ('0', 'false', 'no')
    launch_args = ['--disable-blink-features=AutomationControlled', '--lang=zh-CN']
    if proxy is None:
        # 明确禁用代理，避免浏览器继承系统代理(Clash)导致直连站点连接被重置
        launch_args.append('--no-proxy-server')
    launch_args.extend(extra_args)
    launch_kwargs = dict(
        headless=headless,
        proxy=proxy,
        args=launch_args,
        locale='zh-CN',
        user_agent=user_agent,
        viewport=viewport,
        java_script_enabled=True,
    )
    profile_dir = os.path.join(PLAYWRIGHT_PROFILE_ROOT, 'msedge')
    os.makedirs(profile_dir, exist_ok=True)
    # 上一个浏览器进程异常退出时会在profile里留下陈旧的Singleton锁并残留Helper
    # 子进程，导致新启动拿不到锁。这里等待重试让Chromium自行识别陈旧锁，仍失败
    # 才清理残留进程与锁文件后重试；绝不能静默回退到无cookie的全新上下文——
    # 那会丢失登录态，表现为所有请求被重定向到登录页
    last_error = None
    for attempt in range(3):
        for channel in ('msedge', None):
            try:
                kwargs = dict(launch_kwargs)
                if channel:
                    context = p.chromium.launch_persistent_context(profile_dir, channel=channel, **kwargs)
                else:
                    context = p.chromium.launch_persistent_context(profile_dir, **kwargs)
                return None, context
            except Exception as e:
                last_error = e
                logger.debug(f'持久化profile启动失败(第{attempt+1}次, channel={channel}): {e}')
        if attempt < 2:
            time.sleep(3)
    # 重试无效：清理可能残留的本profile相关浏览器进程和陈旧锁后再试最后一次
    logger.warning('持久化profile多次启动失败，清理残留进程与陈旧锁后重试')
    _cleanup_stale_profile()
    try:
        context = p.chromium.launch_persistent_context(profile_dir, channel='msedge', **launch_kwargs)
        return None, context
    except Exception:
        context = p.chromium.launch_persistent_context(profile_dir, **launch_kwargs)
        return None, context


def _cleanup_stale_profile():
    """清理孤儿浏览器进程与陈旧的Singleton锁文件"""
    import glob
    import subprocess
    import signal
    profile_root = PLAYWRIGHT_PROFILE_ROOT
    try:
        out = subprocess.run(['ps', 'axww', '-o', 'pid=,command='],
                             capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            if profile_root in line:
                pid = int(line.strip().split()[0])
                try:
                    os.kill(pid, signal.SIGKILL)
                    logger.debug(f'已清理残留浏览器进程: pid={pid}')
                except (ProcessLookupError, PermissionError):
                    pass
    except Exception as e:
        logger.debug(f'清理残留进程失败: {e}')
    for lock in glob.glob(os.path.join(profile_root, 'msedge', 'Singleton*')):
        try:
            os.remove(lock)
        except OSError:
            pass


def close_context(browser, context):
    """关闭launch_context返回的会话"""
    try:
        context.close()
    except PlaywrightError:
        pass
    if browser:
        try:
            browser.close()
        except PlaywrightError:
            pass
