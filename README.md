# quote-scraper-demo

公开静态数据采集脚本的最小完整示范：抓取 [quotes.toscrape.com](https://quotes.toscrape.com/) 的名言页面，
解析 5 个字段，顺序翻页、去重、导出 CSV / JSON，并对 403、429、5xx、结构变更做明确处置。

> **合规先行**：本项目只采公开页面、串行限速、不登录、不绕验证码。使用前请先读 [COMPLIANCE.md](COMPLIANCE.md)。
> 默认目标站是专门用于练习爬虫的教学站点；换站点前请自行确认该站条款与 robots.txt。

---

## 1. 环境要求

| 项 | 要求 | 说明 |
| --- | --- | --- |
| Python | ≥ 3.9 | 开发与验收用 3.11.4 |
| 依赖 | requests==2.34.2、beautifulsoup4==4.15.0 | 解析器用标准库 html.parser，不需要 lxml |
| 系统 | Windows / macOS / Linux | 无平台特定代码；仅虚拟环境激活命令不同 |

## 2. 安装

    cd quote-scraper-demo
    python -m venv .venv
    # Windows PowerShell
    .\.venv\Scripts\Activate.ps1
    # macOS / Linux
    source .venv/bin/activate

    python -m pip install -U pip
    pip install -r requirements.txt
    python -c "import requests, bs4; print(requests.__version__, bs4.__version__)"   # 2.34.2 4.15.0

装不上时见 §7 故障排查。

## 3. 运行

    python scraper.py                                    # 全站：默认 10 页 / 100 条，间隔 1s
    python scraper.py --max-pages 2                      # 冒烟：2 页 20 条
    python scraper.py --format csv                       # 只出 CSV
    python scraper.py --out-dir D:\data\quotes           # 换输出目录
    python scraper.py --delay 2.0                        # 更慢（下限 0.2，不接受 0）

### 参数

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| --base-url | https://quotes.toscrape.com/ | 目标站根地址；也可以指向本地桩服务 |
| --max-pages | 10 | 最多翻多少页；该站全量正好 10 页 |
| --delay | 1.0 | 相邻请求间隔（秒），会再加 0–0.3s 抖动；小于 0.2 直接拒绝 |
| --out-dir | out | 输出目录，不存在会自动创建 |
| --format | both | both / csv / json |

### 退出码

| 码 | 含义 |
| --- | --- |
| 0 | 正常结束（无 next / 达页数上限 / 空页正常收尾） |
| 1 | 前置条件失败：参数非法、robots.txt 明确禁止、写入失败 |
| 2 | 采集中止但已保存部分数据：403 / 429 / 其它 4xx / 5xx 重试后仍失败 / 空页却有 next / 分页成环 / 一条没采到 |

## 4. 输出

    out/
    ├── quotes_YYYYmmdd_HHMMSS.csv      # utf-8-sig，Excel 双击直开
    ├── quotes_YYYYmmdd_HHMMSS.json     # 顶层数组，ensure_ascii=False
    └── errors_YYYYmmdd_HHMMSS.jsonl    # 一行一个事件；无异常时是空文件

同秒重跑不会覆盖：第二份自动变成 quotes_..._080500-1.csv。写入是原子的（先 .tmp 再 rename），
进程被杀也不会留下半截 JSON。

### 字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| quote_id | str | sha256(author + 分隔符 + text) 前 12 位，去重键 |
| text | str | 原文，保留弯引号 “ ”，空白已折叠 |
| author | str | 作者名，Unicode 原样 |
| tags | list[str] | 小写、去重保序；允许为空数组。CSV 中用竖线分隔 |
| page | int | 实际请求到的页码，1 起始 |

### 运行摘要（stderr）

    pages=10 rows_seen=100 rows_kept=100 dup=0 parse_skips=0 errors=0 robots=absent stop=no_next elapsed=14.5s
    csv=out\quotes_20261124_081908.csv
    json=out\quotes_20261124_081908.json
    errors_log=out\errors_20261124_081908.jsonl

## 5. 自测（不打外网也能跑）

    python -m unittest discover -s tests -v        # 34 个用例，约 21s，含桩服务端到端

    # 校验某一对导出结果（16 项断言）
    python tests/verify_output.py out\quotes_XXX.csv out\quotes_XXX.json

    # 手动复现异常场景：另开一个窗口
    python tests/fake_server.py 8000 --scenario 429
    python scraper.py --base-url http://127.0.0.1:8000/ --delay 0.2 --max-pages 5

桩服务支持的场景：ok / 403 / 429 / 500 / emptynext / noquotes / disallow / absent / duplicate / missing / loop。

## 6. 已知限制

1. **选择器与目标站绑定**：div.quote / span.text / small.author / a.tag / li.next a。换站点必须改 parse_page。
2. **不跨运行增量**：每次都全量抓，不读历史输出续采；去重只作用于单次运行的内存。
3. **无并发**：单进程串行，全站约 15s。这是合规上的主动选择，不是性能缺陷。
4. **403/429 不重试**：设计如此，避免把封禁升级。只记录并停止。
5. **robots.txt 缺失（404）不阻断**：实测该站就是 404，记为 robots=absent 后继续，但保持 1s 间隔。
   robots.txt 返回 5xx 时按「无法确认」处理，把间隔抬到 2s 并继续。
6. **CSV 公式转义只作用于 CSV**：以 = + - @ 、制表符、回车开头的文本在 CSV 里会多一个前导单引号，
   防 Excel 当公式执行（CWE-1236）；JSON 与内存数据保持原样。因此 CSV 与 JSON 在这类边界上会有 1 个字符差异。
7. **Windows 控制台编码**：程序输出已强制 UTF-8；若终端代码页不是 65001，中文日志在部分终端仍可能显示乱码，不影响文件内容。
8. **--max-pages 默认 10**：等于该站全量。若站点日后加页，需要手动调大。
9. **错误日志不轮转**：errors_*.jsonl 每次运行一个新文件，不自动清理。
10. **只导出 CSV/JSON**：不做 Excel(xlsx)、数据库、S3 等其它落地方式。

## 7. 故障排查

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| pip install 卡住、CPU 飙高 | 上一次安装被中断，进程没退出，两个 pip 抢同一个 venv | 结束残留 python 进程后，单进程重装：pip install --no-cache-dir --progress-bar off -r requirements.txt |
| 装不上（代理/SSL） | 网络或证书 | 加 -i https://pypi.tuna.tsinghua.edu.cn/simple --trusted-host pypi.tuna.tsinghua.edu.cn；或离线 wheel：pip download -r requirements.txt -d wheelhouse --no-deps 后 pip install --no-index --find-links wheelhouse -r requirements.txt |
| `--out-dir` 指向 `%TEMP%` 时报 `WinError 5 拒绝访问` | 本机在 cmd 子进程下写 AppData\Temp 偶发被拦 | 换到项目内目录或 `D:\data\...`。程序已优雅失败（退出码 1），不会抛栈 |
| 端口 8000 被占 | 桩服务默认端口冲突 | python tests/fake_server.py 8001，主程序配 --base-url http://127.0.0.1:8001/ |
| 退出码 2 且 stop=http_forbidden / http_rate_limited | 目标站限流或封禁 | 不要重试、不要换 UA/IP。等一段时间，或降低 --max-pages；详见 errors_*.jsonl |
| Excel 打开 CSV 乱码 | 文件被其它工具另存成非 UTF-8 | 用「数据 → 从文本/CSV 导入」并指定 UTF-8；本程序写出的文件带 BOM，正常应直接可读 |
| robots_disallow 直接退出 1 | 目标站 robots.txt 禁止 | 该项目不应继续采集。换站点或取得授权，不要绕过 |

## 8. 文件结构

    quote-scraper-demo/
    ├── scraper.py            # CLI：robots 检查、翻页、去重、异常与停止、编排
    ├── export.py             # 导出层：CSV（含公式注入转义）/ JSON / JSONL，原子写
    ├── requirements.txt      # 两个钉版依赖
    ├── LICENSE                 # MIT
    ├── spec.md               # 功能/字段/翻页/去重/异常/合规规格
    ├── acceptance.md         # 25 条 Given/When/Then
    ├── ACCEPTANCE_REPORT.md  # 逐轮验收证据
    ├── COMPLIANCE.md         # 合规说明与边界
    ├── DEPLOY.md             # 部署与预览说明
    ├── ENV.md                # 环境实测记录
    ├── PUBLISH.md            # 建 GitHub 仓库的三种路径（本机未装 git）
    ├── dist/                 # 可直接拖拽上传的 zip
    ├── docs/                 # 验收报告 HTML + 截图（作品集素材）
    ├── tools/
    │   └── render_report.py  # Markdown -> 自包含 HTML（截图/打印 PDF）
    ├── tests/
    │   ├── fake_server.py    # stdlib 桩服务（403/429/500/空页/robots/重复页）
    │   ├── test_parse.py     # 离线单测：解析/清洗/转义/原子写
    │   ├── test_acceptance.py# 端到端：退出码、请求序列、文件内容
    │   ├── verify_output.py  # 校验一对导出文件的 16 项断言
    │   └── fixtures/         # page1.html / page10.html（真实页面快照）
    └── out/                  # 运行产物（不入库）

## 9. 许可

代码以 **MIT License** 发布，全文见 [LICENSE](LICENSE)。你可以自由使用、修改、分发、商用，保留版权声明即可。

两条边界（许可不覆盖的部分）：

- **采集到的文本**：页面引文版权归原作者/出版方，不属于本仓库的 MIT 授权范围；要公开或商用请自行取得授权。
- **目标站点的使用条款**：优先于本项目的许可，见 [COMPLIANCE.md](COMPLIANCE.md)。

---

## 10. 数据来源与致谢

目标站点 [quotes.toscrape.com](https://quotes.toscrape.com/) 由 Zyte(Scrapinghub) 提供，用于爬虫教学；
页面引文源自 GoodReads。本项目仅作技术示范，不对引文内容主张任何权利。
