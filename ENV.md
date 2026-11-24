# 环境确认（Phase 0 · 实测于 2026-11-24，本机 Windows）

> 本阶段**不产生任何业务代码**，只锁定「能不能跑」。以下每一条都是在这台机器上真跑出来的，不是假设。

## 1. 本机实测结果

| 项目 | 实测值 | 判定 |
| --- | --- | --- |
| 操作系统 | Windows（`sys.platform = win32`）+ PowerShell | ✅ 与 spec 一致 |
| Python | **3.11.4**，`C:\Program Files\Python311\python.exe` | ✅ ≥ 3.9 |
| Python 多版本 | `py -0p` 只有 3.11（带 `*` 默认） | ✅ 无版本歧义 |
| pip | **23.1.2** | ✅ 可用 |
| 包索引 | `pypi.tuna.tsinghua.edu.cn`（本机已配置镜像） | ✅ 可下载 |
| `requests` | **未安装**（`ModuleNotFoundError`） | ⚠️ 待装 |
| `beautifulsoup4` | **未安装** | ⚠️ 待装 |
| `venv` 模块 | 可用 | ✅ |
| 端口 8000（桩服务用） | **空闲** | ✅ |
| 目标站连通性 | `GET https://quotes.toscrape.com/` → **200**，0.89s，11064 bytes | ✅ 直连可用 |
| 依赖可解析性 | `pip install --dry-run requests beautifulsoup4` → `Would install requests-2.34.2 beautifulsoup4-4.15.0 ...` | ✅ 装得上 |

关于 pip 那次「exit code 1」：**是假失败**。PowerShell 把 pip 写到 stderr 的升级提示当成了 `NativeCommandError`，stdout 里 `Would install ...` 说明解析与下载全部成功。真装的时候如果只看退出码会误判，验收时看最后一行 `Successfully installed`。

## 2. 版本要求

| 依赖 | 要求 | 本机 |
| --- | --- | --- |
| Python | ≥ 3.9（用到 `from __future__` 之外无新语法；`argparse`/`csv`/`json`/`hashlib` 均为标准库） | 3.11.4 ✅ |
| requests | ≥ 2.31（用到 `timeout` + `Session`） | 待装（将装 2.34.2） |
| beautifulsoup4 | ≥ 4.12（用 `html.parser`，**不引 lxml**，少一个二进制依赖） | 待装（将装 4.15.0） |
| 其它 | 无。不装 pandas / scrapy / selenium / playwright | — |

## 3. 目录结构（最终形态；M1 只建 ★ 那几项）

    quote-scraper-demo/                 ★ M1
    ├── spec.md                         ★ 已存在
    ├── acceptance.md                   ★ 已存在
    ├── ENV.md                          ★ 本文件
    ├── requirements.txt                ★ M1
    ├── scraper.py                      ★ M1（单页抓取+解析+打印）
    ├── export.py                         M2（CSV/JSON/jsonl 原子写）
    ├── tests/                            M2
    │   ├── fake_server.py               M2（stdlib 桩服务：403/429/500/空页）
    │   ├── test_parse.py                M2（离线单测，不打网络）
    │   └── fixtures/                    M2（page1.html / page10.html）
    ├── README.md                          M3（运行步骤 + 已知限制）
    ├── ACCEPTANCE_REPORT.md              每阶段追加（命令 + 证据）
    ├── COMPLIANCE.md                     M3（爬虫合规说明）
    ├── DEPLOY.md                         M3（部署/预览说明）
    ├── out/                              运行时生成
    └── .venv/                            本机虚拟环境（.gitignore）

## 4. 依赖安装（按序尝试，前一条失败才走下一步）

**A. 默认路径：项目内 venv + 已配置镜像**

    cd C:\Users\zxs20\Documents\deepseek-harness\default-workspace\quote-scraper-demo
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    python -m pip install -U pip
    pip install -r requirements.txt

**B. 回退 1：venv 里 pip 装不上（代理/SSL/权限）**

    pip install -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn -r requirements.txt

    # 仍失败则走离线 wheel：
    pip download -r requirements.txt -d wheelhouse --no-deps
    pip install --no-index --find-links wheelhouse -r requirements.txt

**C. 回退 2：完全无法联网装包 → 纯标准库版（`urllib` + `html.parser` 手写解析）**

这一版能跑，但**偏离你确认的技术栈**（requests + BeautifulSoup），解析代码会变长、可读性下降。要不要走这条**必须你点头**，我不会自己切。

> 三选一的判据：A 成功就停，不要提前折腾 B/C。装完立即跑 `python -c "import requests,bs4;print(requests.__version__,bs4.__version__)"` 验证。

## 5. 启动命令（M1 的形态）

    python scraper.py --max-pages 1

预期：stdout 打印 10 条 JSON，每条 5 个字段（`quote_id/text/author/tags/page`）；不写文件、不翻页、不去重。

## 6. 端口与冲突

- 桩服务默认 **8000**（已确认空闲）。
- 回退 1：`python tests/fake_server.py 8001`，主程序配 `--base-url http://127.0.0.1:8001`。
- 回退 2：桩服务传 `0` 让系统自选端口，启动时打印实际端口。

## 7. 已知风险（先说清，免得到时候卡住）

| 风险 | 概率 | 预案 |
| --- | --- | --- |
| pip 走镜像偶发超时 | 低 | 重试 1 次；仍失败走 §4-B 离线 wheel |
| 目标站 403/429 | 低（实测 200、约 1s） | 不重试、不换身；立即停并记录，等你决定是否降低页数 |
| 公司网络拦 TLS | 低 | 报错原文给我，我给「关校验（仅本地 demo）」或「离线 fixture 演示」两条路，不静默绕 |
| Excel 打开 CSV 乱码 | 中 | 已定 utf-8-sig；若仍乱码用「数据→从文本导入」 |
| Ctrl+C 留下半截文件 | 中 | M2 用 `.tmp` + rename 原子写，单测覆盖 |

## 8. 需要你确认的 3 个环境问题

- **E1** 用**项目内 `.venv`**（推荐，不污染全局），还是直接装到全局 3.11？
- **E2** `out/` 放在项目内，还是你指定别的绝对路径（比如桌面）？
- **E3** 本机 pip 走的是清华镜像（已配置好），确认可以继续用镜像吗？
