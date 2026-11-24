# Quote Scraper Demo — Spec（v0.1，待确认）

- 状态：**DRAFT，等待你确认后再动代码**
- 目标站点（占位已填）：https://quotes.toscrape.com/  ← 见 §13 待确认 Q1
- 技术栈：Python 3.9+ / requests / BeautifulSoup4（`html.parser`，不引 lxml）
- 规模：单机、单进程、串行、限速；默认全站 10 页 / 100 条

---

## 0. 一页速览

- 抓公开静态页面，**顺序翻页**，跟随页面里的 next 链接，不猜页码。
- 每行 5 个字段：`quote_id, text, author, tags, page`。
- 内存去重（按 author+text），保留首次出现，统计重复条数。
- 导出 CSV（utf-8-sig，Excel 直开不乱码）+ JSON，另有 `errors_*.jsonl` 错误日志。
- **403 / 429 立即停止**并保留已采数据，不重试、不换 IP/UA。
- 不登录、不带 Cookie、不并发、不绕验证码、不抓作者/标签详情页。

---

## 1. 目标站点事实（已实测，2026-11-24）

这些是设计依据，不是我猜的：

| 实测项 | 结果 | 对设计的影响 |
| --- | --- | --- |
| robots.txt | `GET /robots.txt` → **404 Not Found**（站点未发布） | 记录 `robots:absent`，视为无 Disallow 声明，仍保守限速 |
| 首页 | 200，含 10 个 `div.quote` | 每页固定 10 条 |
| 分页 | 第 1 页有 `<li class="next"><a href="/page/2/">`；**第 10 页没有 next** | 用「next 缺失」判定结束，不按页码递增 |
| 越界页 | `/page/11/` → **HTTP 200**，正文只有 “No quotes found!”，0 个 quote | 不能只靠状态码判结束；0 条要按「已采到数据 → 正常收尾」处理 |
| 全站总量 | 10 页 × 10 条 = **100 条** | 验收基准行数 = 100 |
| 字段结构 | `span.text` / `small.author` / `a.tag` | 见 §3 |
| tags 分布 | 每行 0–15 个，**存在 0 个 tag 的条目** | tags 允许空数组，不算字段缺失 |
| 作者重复 | 前 3 页 30 条里 Einstein 出现 6 次 | **不能按 author 去重** |
| 站内文本重复 | 100 条 text 无重复 | 去重能力需用「重复抓同一页」来验证，不能指望站内自然重复 |
| 非 ASCII | 作者 `André Gide` | CSV 用 utf-8-sig；JSON `ensure_ascii=False` |

---

## 2. 功能清单

| ID | 功能 | 说明 | 优先级 |
| --- | --- | --- | --- |
| F1 | 单页抓取 | `requests.get`，超时 10s，明确 UA | P0 |
| F2 | 顺序翻页 | 跟随 `li.next > a[href]`，`urljoin` 拼绝对地址 | P0 |
| F3 | 字段解析与清洗 | 5 个字段，规则见 §3 | P0 |
| F4 | 去重 | 按 (author, text) 归一化后哈希，保留首次 | P0 |
| F5 | CSV 导出 | utf-8-sig，固定表头，RFC4180 引号 | P0 |
| F6 | JSON 导出 | 顶层数组，`ensure_ascii=False`，缩进 2 | P0 |
| F7 | 错误记录 | `errors_*.jsonl`，每次异常一行 | P0 |
| F8 | 停止策略 | 见 §4，403/429 立即停 | P0 |
| F9 | CLI 参数 | `--max-pages --delay --out-dir --format --base-url` | P0 |
| F10 | robots 检查 | 启动先查 robots，Disallow 则拒跑 | P0 |
| F11 | 运行摘要 | stdout 一行统计（页数/行数/重复/错误/耗时/输出路径） | P0 |
| F12 | 部分结果落盘 | 中途停止（错误 / Ctrl+C）时，已采数据照常导出 | P0 |
| F13 | 原子写 | 先写 `.tmp` 再改名，不留半截文件 | P1 |
| F14 | 跨运行增量 | 依赖历史文件续采 | **非目标**（v0.2 再说） |
| F15 | 并发抓取 | 多线程/异步 | **非目标**（合规上主动放弃） |

---

## 3. 字段说明

| 字段 | 类型 | 来源 | 清洗规则 | 示例 |
| --- | --- | --- | --- | --- |
| `quote_id` | str | 派生 | `sha256(author + "\x1f" + text)` 取前 12 位十六进制；去重键与之同源 | `9f2c1a7be034` |
| `text` | str | `div.quote span.text` | 去首尾空白；把连续空白（含 `\xa0`）折叠为单空格；**弯引号 “ ” 与标点原样保留** | `“The world as we have created it is a process of our thinking.”` |
| `author` | str | `div.quote small.author` | 同上去空白折叠；Unicode 原样 | `André Gide` |
| `tags` | list[str] | `div.quote div.tags a.tag` | 去空白、转小写、去重且保序；**允许 `[]`**；CSV 中以 `|` 连接 | `["change","deep-thoughts","thinking","world"]` |
| `page` | int | 采集器本身 | 1 起始的页码，来自实际请求的页，不是猜的 | `3` |

- CSV 列顺序固定：`quote_id,text,author,tags,page`（表头首行）。
- JSON：`[{"quote_id": "...", "text": "...", "author": "...", "tags": [...], "page": 1}, ...]`。
- 不做大小写归一、不去标点、不做 HTML 实体二次解码之外的改写 —— 保真优先。

---

## 4. 翻页规则

1. 起点：`{base_url}/`。
2. 每页解析出 `li.next > a[href]`，用 `urljoin` 得到下一页绝对 URL；**不拼接 `/page/N/`**。
3. 停止判定（自上而下，先命中先停）：

| 序 | 条件 | 处理 | 退出码 |
| --- | --- | --- | --- |
| S1 | HTTP 403 | 立即停，不重试，记 `http_forbidden` | 2 |
| S2 | HTTP 429 | 立即停，不重试，记 `http_rate_limited` + `Retry-After` | 2 |
| S3 | 其它 4xx / 404 | 停止，记 `http_error` | 2 |
| S4 | 5xx / 超时 / 连接错误 | 重试 2 次（退避 2s、4s）；仍失败则停止 | 2 |
| S5 | 本页解析 0 条 quote 且**没有 next** | 已采到数据 → 正常收尾（记 `empty_page` warning）；一条没采到 → 判结构异常停止 | 0 / 2 |
| S6 | 本页解析 0 条 quote 但**有 next** | 选择器可能失效 → 停止，记 `parse_empty_page_with_next` | 2 |
| S7 | 没有 next 链接 | 正常结束 | 0 |
| S8 | 已达到 `--max-pages` | 正常结束 | 0 |
| S9 | 下一跳 URL 已在 visited 集合 | 检测到循环 → 停止，记 `pagination_loop` | 2 |

4. 串行、无并发；相邻两次请求间隔 `--delay`（默认 1.0s）+ 0–300ms 抖动。

---

## 5. 去重规则

- **键**：`(去空白折叠后的 author, 去空白折叠后的 text)` 二元组 → `quote_id`。
- **保留策略**：保留首次出现（按页码升序、页内出现顺序），输出的顺序因此是稳定可复现的。
- **作用域**：仅本次运行的内存 `set`；不读取历史输出文件（跨运行去重是非目标）。
- **不这么做的原因**：
  - 不按 `author` 去重 —— 实测 Einstein 前 3 页出现 6 次，会误杀。
  - 不按 `text` 单独去重 —— 双键已足够收敛，且避免「同文不同署名」被吞。
  - 不做大小写/标点归一 —— 保真优先，宁可少合并。
- **计数**：`rows_seen`（解析成功条数）、`rows_kept`（去重后）、`rows_duplicated`、`parse_skips`（字段缺失跳过数）。

---

## 6. 异常处理规则

| 场景 | 行为 | 记录 | 退出码 |
| --- | --- | --- | --- |
| DNS 失败 / 连接被拒 | 重试 2 次后停止 | `network_error` | 2 |
| 请求超时（10s） | 同上 | `timeout` | 2 |
| 403 | 立即停止，不重试、不伪装 UA | `http_forbidden` | 2 |
| 429 | 立即停止，不换 IP、不降频重试 | `http_rate_limited`、`retry_after` | 2 |
| 5xx | 重试 2 次（2s、4s），仍失败停止 | 每次 attempt 一行 | 2 |
| 单条缺 `text` 或 `author` | 跳过该条，继续本页 | `parse_missing_field` + 页码 + 序号 | 0 / 2 |
| 整页 0 条且还有 next | 停止（选择器可能变了） | `parse_empty_page_with_next` | 2 |
| 全站一条都没采到 | 停止，**不产出空 CSV**，提示检查选择器 | `no_rows` | 2 |
| 磁盘/权限错误 | 报错停止，不吞异常 | stderr | 1 |
| 参数非法（`--max-pages 0` 等） | 启动即校验失败 | stderr | 1 |
| robots 明确 Disallow | 不发页面请求直接退出 | `robots_disallow` | 1 |
| 手动 Ctrl+C | 捕获 `KeyboardInterrupt` → 落盘已采数据后退出 | `interrupted` | 2 |

- **退出码约定**：`0` 全部正常；`1` 前置条件失败（参数/robots/环境）；`2` 采集中止但已保存部分数据。
- `errors_*.jsonl` 每行：`{"ts","page","url","status","reason","detail"}`，追加写，一行一个 JSON。

---

## 7. 输出与运行摘要

- 目录：`out/`（可用 `--out-dir` 改）。文件命名带秒级时间戳，同秒重跑自动加 `-1`、`-2` 后缀。
- `out/quotes_YYYYmmdd_HHMMSS.csv`：utf-8-sig，首行表头，字段含逗号/引号由 csv 模块正确转义。
- `out/quotes_YYYYmmdd_HHMMSS.json`：顶层数组，缩进 2，`ensure_ascii=False`。
- `out/errors_YYYYmmdd_HHMMSS.jsonl`：总是创建；无异常则为空文件。
- **CSV 公式注入（你已裁决，2026-11-24）**：`text/author` 若以 `=` `+` `-` `@` `\t` `\r` 开头，Excel 会当公式执行。处理**只在导出层**（`export.py`）：CSV 写出时给这类值加前导单引号 `'`；**采集与解析层绝不改数据**，JSON 亦保持原样（JSON 无公式执行面）。转义仅作用于 CSV，因此「保真」原则在内存与 JSON 中不受影响。
- stdout 摘要示例：

    pages=10 rows_kept=100 dup=0 parse_skips=0 errors=0 robots=absent elapsed=11.2s
    csv=out/quotes_20261124_080500.csv json=out/quotes_20261124_080500.json

---

## 8. 合规边界

- 只采**公开静态页面**，不碰任何需要授权的内容。
- 启动先取 robots.txt：200 用 `urllib.robotparser` 判定，Disallow 命中即退出；404 记录 `robots:absent` 后继续；5xx/超时 → 记 warning 且把 delay 提到 2s。
- UA 明示身份与用途：`quote-scraper-demo/0.1 (+educational demo)`。
- 默认 1 req/s，串行，全站上限 10 页；没有任何并发与重试风暴。
- 不登录、不带 Cookie、不提交表单、不抓 `/author/*`、`/tag/*` 详情页（字段不需要）。
- 输出仅本地留存，脚本不含任何上传/回传逻辑。
- 版权提示：该站为教学用沙盒，引文源自 GoodReads；要发布或商用请自行确认站点条款与原文授权。
- **站点条款优先**：若站点条款与本 spec 冲突，以条款为准，停下来告诉你，不擅自继续。

---

## 9. 文件清单

    quote-scraper-demo/
    ├── spec.md              # 本文件
    ├── acceptance.md        # Given/When/Then 验收清单
    ├── ENV.md               # Phase 0：环境实测与安装/回退路径
    ├── ACCEPTANCE_REPORT.md # 每阶段追加：命令 + 输出证据 + 行数
    ├── README.md            # M3：运行步骤 / 参数 / 已知限制
    ├── COMPLIANCE.md        # M3：爬虫合规说明与边界
    ├── DEPLOY.md            # M3：部署与预览说明（CLI 项目的"部署"=本地/服务器跑法）
    ├── requirements.txt     # requests, beautifulsoup4（只有这两个）
    ├── scraper.py           # M1 起：抓取/翻页/解析/去重/编排/CLI
    ├── export.py            # M2：CSV / JSON / jsonl 原子写
    ├── tests/
    │   ├── fake_server.py   # M2：stdlib 桩服务，返回 403/429/500/空页
    │   ├── test_parse.py    # M2：离线解析 + 去重单测（不打网络）
    │   └── fixtures/        # M2：抓一次存下的 page1.html / page10.html
    └── out/                 # 运行时生成，不入库

---

## 10. 运行步骤（写代码后按这个验收）

Windows PowerShell：

    cd quote-scraper-demo
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt

    python scraper.py --max-pages 2 --out-dir out      # 冒烟：2 页 20 行
    python scraper.py                                 # 全站：10 页 100 行
    python scraper.py --format csv                    # 只要 CSV
    python -m unittest discover -s tests -v           # 离线单测
    python tests/fake_server.py 8000                  # 另开窗口：桩服务
    python scraper.py --base-url http://127.0.0.1:8000 --max-pages 3   # 验证 403/429 停止

macOS / Linux 把第 3 行换成 `source .venv/bin/activate` 即可。

---

## 11. 里程碑（等你确认后逐个执行，每次只做一个）

| 阶段 | 交付 | 验证方法 | 完成标准 |
| --- | --- | --- | --- |
| M1 最小可运行 | `scraper.py`（单页抓取 + 解析 + 打印 JSON 到 stdout）、`requirements.txt` | `python scraper.py --max-pages 1` | 输出 10 条，5 个字段非空，无翻页/无去重/无写文件 |
| M2 管线与导出 | 翻页 + 去重 + 异常/停止 + `export.py` + 桩服务与单测 | 全站跑一次 + 桩服务跑 403/429 场景 + `unittest` | 100 行落地、CSV/JSON 可打开、403/429 停止并记错、单测全绿 |
| M3 文档 | `README.md` + `COMPLIANCE.md` + `DEPLOY.md` | 按 README 在干净 venv 复现一遍 | 新人照 README 能跑通，合规边界与本文一致 |

> 每个阶段结束，往 `ACCEPTANCE_REPORT.md` 追加一节：跑的命令、原始输出、导出文件行数、对应 AC 编号。
> 验收不通过时**只修该阶段那一项**，不重写整个项目。

---

## 12. 明确「不做什么」

1. 不登录、不注册、不带 Cookie/Session、不模拟真实用户。
2. 不绕验证码、不换 IP/代理、不轮换 UA、不做任何反爬对抗。
3. 不采隐私/个人信息（不抓作者页、不抓邮箱、不建人物画像）。
4. 不做并发、不做高频请求（间隔不低于 1s，且不接受把 delay 调到 0）。
5. 不逆向站点内部 API、不猜隐藏接口、不伪造请求链。
6. 不写数据库、不做断点续采、不做跨运行增量（v0.1 范围外）。
7. 不做翻译/摘要/情感分析/NLP 加工。
8. 不做 Web 服务、仪表盘、可视化。
9. 不做自动分发/上传/定时任务。
10. 不修改数据保真度（不改写引文、不补全缺失字段、不做「看起来更好」的清洗）。
11. 不做 CI/容器/部署（只在本地跑）。
12. 站点返回 403/429 后不做任何「再试一次就好」的处理。

---

## 13. 待你确认（这几条定了我就开工）

- **Q1 目标站**：默认就按 `quotes.toscrape.com` 做，对吗？（模板里 `{目标站点}` 和 `{字段}` 恰好指向它，我按这个填了）
- **Q2 文本保真**：`text` 要保留原文的弯引号 “ ” 吗？还是要去掉首尾引号留纯句子？
- **Q3 tags 为空**：实测有 0 个 tag 的条目，我按「允许空数组、不算缺失」处理，可以吗？
- **Q4 默认页数**：默认抓全站 10 页（100 条），还是默认只抓 2 页（20 条）当 demo？
- **Q5 M2 拆分**：M2 我打包了「翻页+去重+异常+导出」，要不要拆成 M2a（翻页+去重）/ M2b（异常+导出），每次交付更小一点？
