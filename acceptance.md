# 验收清单（Given / When / Then）

配套 `spec.md` v0.1。基准数字来自实测（2026-11-24）：全站 10 页、100 条、每页 10 条、tags 可为空、第 10 页无 next、`/page/11/` 返回 200 但 0 条。

图例：**A** 自动（单测/桩服务）｜**M** 人工（打开文件看一眼）

---

## A. 采集页数与行数

**AC-01 全站默认跑（A+M）**
- Given 网络正常、默认参数、站点可访问
- When 运行 `python scraper.py`
- Then 摘要里 `pages=10`、`rows_kept=100`；CSV 数据行恰为 100（不含表头）；JSON 数组长度 100

**AC-02 限制页数生效（A）**
- Given 参数 `--max-pages 2`
- When 运行
- Then `pages=2`、`rows_kept=20`，且 `page` 列最大值 = 2，没有第 3 页的任何数据

**AC-03 单页冒烟（A）**
- Given `--max-pages 1`
- When 运行
- Then `pages=1`、`rows_kept=10`，退出码 0

**AC-04 末页靠 next 缺失收尾（A）**
- Given 从第 1 页开始抓
- When 处理到第 10 页（该页没有 `li.next`）
- Then 判定正常结束、退出码 0，且**不请求** `/page/11/`（看桩服务或日志里的请求序列）

**AC-05 越界页不误判为错误（A）**
- Given 页码越界页 `/page/11/` 返回 200 且 0 条 quote、也没有 next
- When 解析该页
- Then 作为「已采到数据的正常收尾」处理：退出码 0，`errors_*.jsonl` 记一条 `empty_page` warning，已采的 100 条照常导出

---

## B. 字段质量

**AC-06 必填字段非空（A）**
- Given 一次全站成功运行的输出
- When 逐行校验
- Then `text` 与 `author` 全部非空（`strip()` 后长度 > 0）、`page` 为 1–10 的整数、`quote_id` 唯一且为 12 位十六进制

**AC-07 tags 允许为空且不算缺失（A）**
- Given 站内确实存在 0 个 tag 的条目
- When 导出
- Then 该行 tags 在 JSON 里是 `[]`、在 CSV 里是空字段；`parse_skips` 不因此 +1

**AC-08 文本保真、无 HTML 残留（A+M）**
- Given 首条 quote
- When 看 CSV 里对应行
- Then `text` 保留原文弯引号 “ ” 与句末标点，不含 `<span>` 等标签，首尾无空白，内部无连续空格

**AC-09 非 ASCII 不乱码（M）**
- Given 含作者 `André Gide` 的结果
- When 用 Excel / 表格软件直接双击打开 CSV
- Then `André` 显示正常（utf-8-sig 生效），不是 `AndrÃ©`

---

## C. 去重

**AC-10 不误杀真实数据（A）**
- Given 默认全站运行（100 条 text 本身唯一）
- When 走完去重
- Then `rows_kept=100`、`rows_duplicated=0`

**AC-11 人为重复被合并（A）**
- Given 把第 1 页抓取两次的结果（20 条）喂进管线，或桩服务连续两次返回同一页
- When 去重
- Then 输出 10 条、`rows_duplicated=10`，且保留的是**首次出现**的那份 `page` 值

**AC-12 不按作者去重（A）**
- Given 前 3 页里 Einstein 出现 6 次
- When 去重
- Then 6 条全部保留（`quote_id` 各不相同），`rows_duplicated=0`

---

## D. 异常：403 / 429 记录错误并停止

**AC-13 403 立即停（A）**
- Given 桩服务对 `/page/2/` 返回 403
- When 运行 `python scraper.py --base-url http://127.0.0.1:8000 --max-pages 5`
- Then 停止且**不重试**、**不请求 `/page/3/`**；`errors_*.jsonl` 有 `status=403, reason=http_forbidden`；退出码 2；第 1 页的 10 条已导出且可打开

**AC-14 429 立即停且不换身份（A）**
- Given 桩服务返回 429（带 `Retry-After: 30`）
- When 运行
- Then 立即停止；记录 `status=429, reason=http_rate_limited, retry_after=30`；**没有**换 UA/IP 重试的第二个请求；退出码 2；已采数据照常导出

**AC-15 5xx 有限重试后停（A）**
- Given 桩服务对 `/page/3/` 连续返回 500
- When 运行
- Then 该页总共请求 3 次（1 次 + 重试 2 次，间隔约 2s、4s）后停止；errors 里 3 条 attempt；退出码 2

**AC-16 单条字段缺失只跳过该条（A）**
- Given fixture 里一条 quote 缺 `author`
- When 解析该页
- Then 该条被跳过并记 `parse_missing_field`，`parse_skips=1`，其余 9 条正常导出，退出码 0

**AC-17 结构变更要暴露不要静默（A）**
- Given 桩服务返回一页「有 next 但 0 个 quote」（模拟选择器失效）
- When 运行
- Then 停止并记 `parse_empty_page_with_next`；退出码 2；**不产出只含表头的空 CSV**

---

## E. 导出文件可打开

**AC-18 CSV 结构正确（A+M）**
- Given 一次成功运行
- When 打开 `out/quotes_*.csv`
- Then 首行表头恰为 `quote_id,text,author,tags,page`；100 行数据；含逗号和引号的 `text` 没有被拆成多列（RFC4180 转义生效）

**AC-19 JSON 合法（A）**
- Given 输出文件
- When `python -c "import json;print(len(json.load(open('out/quotes_x.json',encoding='utf-8'))))"`
- Then 打印 100；顶层是数组；每个元素恰好 5 个键

**AC-20 无半截文件（A）**
- Given 运行中途 Ctrl+C（用桩服务加延迟模拟）
- When 进程退出
- Then 目录里要么是完整文件、要么没有该文件，**没有残留 `.tmp`**，也没有截断的非法 JSON

**AC-21 重复运行不覆盖（A）**
- Given 同一秒内连续运行两次
- When 看 `out/`
- Then 得到两套文件（后者带 `-1` 后缀），前一份内容不被覆盖

---

## F. 合规与依赖

**AC-22 robots 404 的处理（A）**
- Given `/robots.txt` 返回 404（实测如此）
- When 运行
- Then 摘要含 `robots=absent`，采集正常继续，不因此退出

**AC-23 robots 禁止时不抓（A）**
- Given 桩服务 `/robots.txt` 返回 `User-agent: *\nDisallow: /`
- When 运行
- Then **不发起任何页面请求**，退出码 1，stderr 说明是 robots 拒绝

**AC-24 UA 与限速可验证（A）**
- Given 跑 3 页
- When 看桩服务的请求记录
- Then UA 含 `quote-scraper-demo`；相邻请求时间差 ≥ 1.0s；改 `--delay 0.5` 后间隔随之变小（参数确实生效）

**AC-25 干净环境可跑（M）**
- Given 全新 venv，只执行 `pip install -r requirements.txt`
- When 运行 `python scraper.py --max-pages 1`
- Then 成功，无 ImportError；`requirements.txt` 只有 `requests` 与 `beautifulsoup4` 两行

---

## 通过标准

- A 类全部通过（AC-01~AC-08、10~17、19~24）
- M 类人工确认通过（AC-09、AC-18 的打开检查、AC-25）
- 任何一条不通过就回到对应里程碑修，不进入下一阶段。
