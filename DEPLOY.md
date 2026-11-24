# 部署与预览说明

本项目是**命令行采集器**，没有 Web 前端、没有小程序、没有常驻服务。
因此这里的「部署」= 在一台机器上把脚本跑起来；「预览」= 查看导出的 CSV / JSON。

## 1. 本地运行（推荐，验收即此路径）

    git clone <your-repo-url> quote-scraper-demo
    cd quote-scraper-demo
    python -m venv .venv
    .\.venv\Scripts\Activate.ps1          # macOS/Linux: source .venv/bin/activate
    pip install -r requirements.txt
    python scraper.py

产物在 out/。跑完看 stderr 的摘要行确认条数。

## 2. 在服务器上定时跑（可选）

仅在你已确认目标站允许、且用量远低于其承载能力时才有意义。示例（Linux，cron，每天 03:00）：

    0 3 * * * cd /opt/quote-scraper-demo && ./.venv/bin/python scraper.py --delay 2.0 --out-dir /var/data/quotes >> /var/log/quote-scraper.log 2>&1

Windows 用「任务计划程序」指向 python.exe，参数同上。

注意：

- 定时任务会**每天全量重跑**，本版本没有跨运行增量（见 README §6）。
- out/ 会持续增长，请自行加清理策略；程序不做轮转。
- 不要为了「更快」把 --delay 调低：下限 0.2s 是硬限制，且违背合规意图。

## 3. 预览导出结果

| 文件 | 怎么预览 | 命令 |
| --- | --- | --- |
| CSV | Excel / WPS / Numbers 双击打开（utf-8-sig 带 BOM，中文与 é 不会乱码） | — |
| JSON | 编辑器直接看；或命令行校验条数 | python -c "import json;d=json.load(open('out/quotes_x.json',encoding='utf-8'));print(len(d))" |
| 错误日志 | 一行一个 JSON，逐行看 | type out\errors_x.jsonl （macOS: cat） |
| 一次运行的完整性 | 16 项断言 | python tests\verify_output.py out\quotes_x.csv out\quotes_x.json |

CSV 列固定为 quote_id,text,author,tags,page；tags 用竖线分隔，方便 Excel 分列。

## 4. 演示给别人看（无外网也能跑）

    # 窗口 A：起桩服务，模拟 429
    python tests/fake_server.py 8000 --scenario 429

    # 窗口 B：让它失败，展示错误记录与退出码
    python scraper.py --base-url http://127.0.0.1:8000/ --delay 0.2 --max-pages 5
    echo $LASTEXITCODE        # 2

    # 换成正常场景（窗口 A 改 --scenario ok 重开），窗口 B 再跑一次，展示成功导出

这种方式不触碰真实站点，适合写进作品集或做演示。

## 5. 不在部署范围内（按 spec §12）

- 容器化 / Dockerfile：不做。
- CI/CD、K8s、Serverless：不做。
- Web 服务化（把采集结果挂成接口或页面）：不做，本项目没有这个目标。
- 多机分布式、代理池：不做。

## 6. 卸载 / 清理

    rm -rf out/ .venv __pycache__ tests/__pycache__

项目不写注册表、不装系统服务、不在项目目录之外留文件（除 Python 自身缓存与 pip 缓存）。
