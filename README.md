# JavSP (firewelly fork)

**汇总多站点数据的AV元数据刮削器 — macOS 增强版**

上游项目：[Yuukiy/JavSP](https://github.com/Yuukiy/JavSP)

本 fork 在上游 v1.8 基础上进行了 **javdb 爬虫重写（Playwright）** 和 **macOS 原生打包支持**，并修复了多个影响日常使用的稳定性问题。

---

## 主要修改（相对上游）

### 1. javdb 爬虫全面重写：cloudscraper → Playwright

上游的 javdb 抓取基于 cloudscraper，在当前 Cloudflare 防护下基本失效。本 fork 用 **Playwright（无头 Chromium）** 完全重写了 `javsp/web/javdb.py`：

- 通过真实浏览器内核稳定通过 Cloudflare 质询，不再依赖 cookies 池
- **默认使用国内可直连镜像站 `javdb575.com`，不走代理**。原因：javdb.com 官方域名按版权要求屏蔽日本地区 IP，而常见代理出口恰好在日本，导致上游版本"怎么配代理都 403"
- 镜像失效时只需修改 `javsp/web/javdb.py` 顶部的 `base_url` 常量（`_get_proxy_settings` 会自动在用镜像时禁用代理）
- 保留了与上游一致的 `parse_data` / `parse_clean_data` / `collect_actress_alias` 接口，数据汇总逻辑不变

### 2. macOS 打包支持（PyInstaller）

新增 `JavSP.spec`，`onedir` 模式构建。产物布局对人类友好——**配置与数据独立放置，其余全部打包**：

```
JavSP/
├── JavSP                  # 可执行文件
├── config.yml             # 实际生效的配置（独立，可直接编辑）
├── config.ini             # 旧版配置参考（需用迁移脚本转换）
├── config_migration.py    # config.ini → config.yml 迁移脚本
├── data/                  # genre 映射、女优别名等数据（独立）
├── image/                 # 图标资源（独立）
└── _internal/             # Python 运行时 + 全部依赖（勿动）
```

打包模式下的适配修复：

- `multiprocessing.freeze_support()`：**修复 frozen 模式 fork 炸弹**（子进程重复执行主程序导致内存暴涨失控）
- `resource_path()` 改为基于 `sys.executable` 解析，配置/数据独立放置后依然可找到
- 运行时自动 `chdir` 到可执行文件目录
- `--config` 参数解析加固，过滤 multiprocessing 注入的杂音参数
- macOS tkinter 不支持 `.ico` 的兼容处理；打包环境缺包元数据的兼容处理
- spec 中排除 PyQt6/PySide6/matplotlib 等无关大依赖（避免 anaconda 构建环境的 Qt 多绑定冲突）

### 3. 稳定性改进（刮削主流程）

- **单影片失败跳过**：某部影片所有抓取器都失败时，记录错误并继续处理下一部（上游会直接抛异常终止整个任务）
- `extrafanart` 目录创建改用 `os.makedirs(..., exist_ok=True)`：重复刮削同一影片不再因目录已存在而崩溃

### 4. 代理配置建议

实测在 macOS + Clash 系代理下，`socks5h://`（由代理端解析 DNS）比 `socks5://` 明显更可靠：

```yaml
network:
  proxy_server: socks5h://127.0.0.1:1080
```

---

## 快速开始（macOS）

### 方式一：直接下载打包版

从 [Releases](https://github.com/firewelly/JavSP/releases) 下载 `JavSP-macOS.zip` 并解压：

```bash
cd JavSP
xattr -cr ./JavSP   # 清除隔离属性（未签名二进制）
./JavSP
```

- `scanner.input_directory` 留空 `null` 时，启动会**弹出文件夹选择窗口**
- 需要代理请编辑 `config.yml` 的 `network.proxy_server`

### 方式二：源码运行

```bash
git clone https://github.com/firewelly/JavSP.git
cd JavSP
pip3 install cloudscraper colorama pillow pretty-errors requests tqdm \
    cryptography pycryptodome "lxml[html-clean]" confz pydantic-extra-types \
    pendulum playwright
python3 -m playwright install chromium
python3 javsp/__main__.py
```

### 从旧版 config.ini 迁移配置

```bash
python3 config_migration.py -i config.ini -o config.yml
```

迁移后请将 `proxy_server` 的 `socks5://` 手动改为 `socks5h://`。

### 自行打包

```bash
pip3 install pyinstaller
python3 -m PyInstaller JavSP.spec --noconfirm
# 产物在 dist/JavSP/，将 config.yml、data/、image/、config_migration.py 复制进去即可
```

---

## 已知限制

- javdb 镜像域名会不定期变化（官方持续更换 alternative 域名），失效时需手动更新 `javsp/web/javdb.py` 的 `base_url`
- airav / javlib 的反爬在无浏览器环境下依然经常失败，属正常现象；数据汇总以 javdb / javbus / fanza 为主力
- macOS 版未做代码签名与公证，首次运行需 `xattr -cr` 清除隔离属性

## 致谢

- 上游作者 [Yuukiy](https://github.com/Yuukiy) 及所有 JavSP 贡献者
- Playwright 版 javdb 爬虫的初始实现参考了社区中浏览器自动化绕过 Cloudflare 的实践

## 许可

继承上游 GPL-3.0 License 与 [Anti 996 License](https://github.com/996icu/996.ICU/blob/master/LICENSE_CN)。
