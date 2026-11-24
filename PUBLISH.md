# 发布到 GitHub（三种路径，选一种）

本机 **没有安装 git**（where git 无结果），所以「建仓库」这一步需要你选一条路。
仓库内容已经就绪并自洽：源码 + 文档 + 测试 + 验收报告都在，.gitignore 已排除 out/、.venv/、__pycache__/。

## 方案 A：网页上传（不需要 git，最快）

1. 解压 dist/quote-scraper-demo.zip。
2. GitHub → New repository → 名字建议 quote-scraper-demo → Public → **不要**勾选 README/.gitignore（我们自带）。
3. 仓库页 → Add file → Upload files → 把解压出来的文件与文件夹**全部拖进去** → Commit changes。
4. 仓库设置里补 Description（示例见下）与 Topics：python / web-scraping / beautifulsoup / requests / csv-export / robots-txt。

## 方案 B：装 Git 后用命令行（推荐，后续好维护）

    winget install --id Git.Git -e --source winget      # 装完新开一个终端
    cd quote-scraper-demo
    git init
    git add -A
    git commit -m "M1-M3: 公开数据采集 demo（robots 三态 / 翻页 / 去重 / CSV 转义 / 35 个测试）"
    git branch -M main
    git remote add origin https://github.com/<你的账号>/quote-scraper-demo.git
    git push -u origin main

> 推送要你的 GitHub 凭据（HTTPS 走 Personal Access Token，或 gh auth login）。这一步只有你能做。

## 方案 C：GitHub CLI

    winget install --id GitHub.cli -e --source winget
    gh auth login
    cd quote-scraper-demo
    gh repo create quote-scraper-demo --public --source=. --push

## 仓库门面建议

- **Description**：公开数据采集脚本：robots 三态检查、顺序翻页、去重、CSV 公式注入防护、35 个测试与逐轮验收报告
- **首屏**：README 已含「合规先行」提示 + 安装/运行/参数/退出码/已知限制，建议在仓库 About 里指向 COMPLIANCE.md。
- **证据链**：ACCEPTANCE_REPORT.md（Round 1–4 逐轮证据）、spec.md（先规格后实现）、acceptance.md（25 条 Given/When/Then）。
  这套「先 spec → 再实现 → 逐轮验收」的顺序，比只贴代码更能说明工程能力。

## 截图素材（第四步第 2 小步）

| 素材 | 怎么来 |
| --- | --- |
| 验收报告网页截图 | 双击打开 docs/acceptance-report.html（已渲染好，可直接截图或打印成 PDF） |
| GitHub 仓库页截图 | 按方案 A/B/C 建好仓库后，截仓库首页 |
| 聊天界面截图 | 需要你自己截（我这侧无法访问你的窗口） |

## 不要上传的东西

out/（采集产物）、.venv/（虚拟环境）、__pycache__/（字节码）。.gitignore 已经写好，用方案 B/C 时不会误传；
用网页上传时请**只拖** scraper.py、export.py、requirements.txt、*.md、tests/、.gitignore。
