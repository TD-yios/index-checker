# 收录查询工具（百度 / 谷歌 / 必应 / 头条搜索）

Windows 桌面端的多品牌关键词收录查询工具。关键词库按品牌分组，每个关键词绑定自己的目标 URL，支持一次勾选多个品牌的多个关键词批量查询；命中后截图存档，结束后把结果回写到关键词库，并生成 Excel / CSV 报告。工具自带 Chrome 内核，换电脑不用另外安装浏览器。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[GitHub 仓库](https://github.com/TD-yios/index-checker)


## 功能

- 关键词库按品牌分组：每个品牌一个分组行，品牌下可放多个关键词，每个关键词独立目标 URL
- 品牌和关键词可编辑：支持品牌重命名、目标品牌同名时合并；单条关键词的品牌 / 关键词 / URL 可完整修改
- 多品牌批量查询：勾选任意关键词，跨品牌一起查询；也支持按品牌整组查询
- 导入先校验：粘贴三列或选择 Excel / CSV / TXT，预览里直接标出“可导入 / 重复跳过 / URL 无效”，只导入有效行
- 查询结果与关键词库联动：查询结束后自动写回最近查询时间、状态、命中摘要和所用引擎
- 四大引擎：百度、必应、谷歌、头条搜索（每个引擎可单独配置代理，查询设置里可先点「测试」检查连通性）
- 桌面工具化：单实例运行、Ctrl+N / Ctrl+I / Ctrl+F / F5 / Ctrl+Q 快捷键、每次查询生成 JSONL 运行日志
- 内置 Chrome 内核：本机有 Chrome 时优先用本机，没有则自动用随工具打包的 Chrome
- 翻页次数可控：每个关键词 1–20 页，可设置命中即停（仅自然结果命中时停，品牌专区/广告命中会继续翻页，方便拿自然排名）
- 命中判定按真实 URL，不依赖页面上显示的域名文本
- 品牌专区、聚合卡片、竞价广告、自然排名四类命中分开统计，界面可按类型筛选
- 自然排名按全局连续位次显示：默认按前面页实际自然结果数累计；百度/必应/谷歌一页通常 10 条，第 2 页第 2 位为 `#12`；头条等一页实际条数不同的引擎按实际条数累计，不再强行按 10 条补位；品牌专区、聚合卡片、竞价广告不占自然位
- 命中页自动整页截图，并在截图上框选命中结果、标注 `#12 自然排名` 或对应类型；只保留标注图
- 输出文件：汇总 CSV + 命中明细 CSV + 分页明细 CSV + 三张表的 Excel + 截图目录
- 报告中心记录每次查询的输出目录，历次报告即使更换过输出目录也能打开

## 关键词库与数据

关键词库保存在：

```
%LOCALAPPDATA%\IndexChecker\library.db
```

字段包括品牌、关键词、目标 URL、目标域名、最近查询时间、最近状态、最近命中摘要、最近引擎。品牌 + 关键词唯一；同一品牌可以挂多个不同 URL 的关键词，不同品牌也可以查同一个关键词。

报告历史索引保存在 `%APPDATA%\IndexChecker\reports.json`，只记录每次查询的输出目录，不复制报告文件。

首次启动时，如果库为空且存在旧版 `%APPDATA%\IndexChecker\last_config.json`，会把旧关键词导入成初始记录，并写入一次性迁移标记；之后以库里的数据为准，清空关键词库后重启也不会再把旧关键词写回。


导入格式为三列：

```
品牌,关键词,目标URL
示例品牌,示例品牌,https://www.example.com
示例品牌,示例品牌合肥,https://www.example.com
示例品牌B,示例品牌B,https://www.example.org
```

目标 URL 支持完整网址或裸域名；裸域名会自动补 `https://`。重复按“品牌 + 关键词”判断。

## 命中判定逻辑（重点）

百度品牌词场景下，结果页的域名位置经常不显示真实域名，而是被替换成品牌名或“官方”标识，例如搜索“示例品牌”时顶部品牌专区只显示“示例品牌-专注家装，筑安心家 官方”。如果只看页面文字，会漏判。

本工具按以下顺序取真实地址：

1. 结果节点 `mu` 属性（百度自然结果）
2. `data-mu` / `data-landurl` 属性（品牌专区、品牌广告，真实地址写在属性里）
3. 跳转链接还原（百度 `link?url=` / `baidu.php?url=`，谷歌 `/url?q=`，必应 `/ck/a?u=`，头条 `sou.toutiao.com/search/jump?url=`，头条的嵌套跳转最多拆三层）
4. 可见域名文本兜底

只有前三步都取不到、且页面可见域名文本命中时，才按文本判定。判定采用域名后缀匹配，`www.xxx.com`、`m.xxx.com`、`hfm.xxx.com` 都算命中 `xxx.com`。

## 快速开始

仓库只提交源码、测试和说明文档，不提交 `dist/`、`vendor/`、`outputs/`、截图和 300MB 级发布包。

### 源码运行

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

也可以双击 `安装依赖.bat` 自动创建 `.venv` 并安装依赖，再双击 `启动工具.bat`。第一次运行如果本机没有 Chrome，可先执行 `准备内置浏览器.ps1` 下载 Chrome for Testing。

### 打包成 exe

```bat
准备内置浏览器.ps1
打包exe.bat
```

`打包exe.bat` 会调用 PyInstaller 构建 `dist\IndexChecker`，并把 `vendor\chrome-win64` 复制到 `browser\` 子目录。整个 `IndexChecker` 文件夹一起拷贝才能免安装运行，不能只拷 exe。

换机器时：

1. 直接拷贝整个 `IndexChecker` 文件夹（含 `browser` 子目录），双击 exe 就能用，不需要安装 Python 或 Chrome。
2. 源码运行需要 Python 3.10+ 和 `requirements.txt`；打包需要 PyInstaller。

浏览器使用顺序：本机 Chrome → 随工具打包的内置 Chrome（Chrome for Testing，品牌版）→ 系统 Edge → Playwright Chromium。内置 Chrome 与真实 Chrome 指纹一致，实测百度品牌词搜索不会掉进安全验证页。

运行自动测试：双击 `运行测试.bat`，或执行：

```bash
python -m unittest discover -s tests -v
```

UI smoke 需要先设置 `IC_UI_SMOKE=1`。

## 界面用法

1. 打开左侧「关键词库」，新增或导入品牌、关键词、目标 URL。
2. 勾选要查的关键词；批量条会显示“已选几个关键词、覆盖几个品牌”。也可以点品牌分组行右侧的「查询本品牌」整组查询；分组行的「重命名」可改名或合并品牌。
3. 点「批量查询」弹出查询设置：搜索引擎、翻页次数、命中即停、后台运行、每页截图、翻页间隔、各引擎代理、输出目录。代理输入框右侧可点「测试」先检查连通性。
4. 查询过程中在「查询任务」看实时进度：每页状态、命中数、全局自然排名（如 `自然#12`）、截图；「分类统计」按品牌 / 关键词 / 引擎 / 类型展开；「运行日志」保留每个引擎的执行信息。
5. 查询完成后，状态自动回写到关键词库。报告在「报告中心」，可打开 Excel 或对应输出文件夹。

快捷键：`Ctrl+N` 新增关键词，`Ctrl+I` 导入，`Ctrl+F` 搜索，`Ctrl+Enter` 查询已选关键词，`F5` 刷新，`Ctrl+Q` 退出。



“后台运行（无头）”默认开启。遇到百度/必应安全验证时，取消勾选重跑，浏览器窗口会弹出，手工完成验证后工具会自动继续（默认等 90 秒），Cookie 会保存在 `%LOCALAPPDATA%\IndexChecker\profiles` 里，后续一般不再触发。

## 输出结构

```
outputs/20261121_143000/
├── 收录查询报告.xlsx     # 汇总 + 命中明细 + 分页明细，带筛选、类型配色、冻结首行
├── 查询汇总.csv          # 每个品牌×关键词×引擎一行，四类数量分列
├── 命中明细.csv          # 每条命中一行（品牌、关键词、页码、页内位次、全局排名、URL、截图）
├── 分页明细.csv          # 每一页一行
├── baidu/
│   ├── 示例品牌_baidu_p1.png
│   └── 示例品牌_示例品牌合肥_baidu_p1.png
└── bing/
    └── 示例品牌_bing_p1.png
```

汇总表字段：时间、品牌、关键词、目标URL、搜索引擎、是否命中、品牌专区数、品牌首现页、聚合卡片数、卡片首现页、竞价广告数、广告首现页、自然排名数、自然首现页、自然首现页内位、自然首现全局位、命中URL、命中总数、检查页数、状态。“自然首现页内位”是当页自然位次，“自然首现全局位”是按前面页实际自然结果数累计后的全局位次；品牌专区、聚合卡片和竞价广告不占自然位。

命中明细里保留“页码 / 页内位次 / 全局排名”三列：自然结果填完整，品牌专区、聚合卡片、竞价广告留空。

Excel 的“命中明细”按每条命中记录展开，类型列有四种底色，可直接用表头筛选只看品牌专区、聚合卡片、竞价广告或自然排名；“分页明细”保留每一页的状态、命中数与截图路径。


## 关于

左侧导航底部有「关于」入口，窗口标题和「关于」里都会显示当前版本。关于窗口包含：

- 作者：aromer
- GitHub：@TD-yios
- 地址：https://github.com/TD-yios
- 版本：v3.2.1
- 版权：© 2026 aromer，MIT License
- 运行日志：`%LOCALAPPDATA%\IndexChecker\logs`


## 开源协议

本项目使用 MIT License，版权归 aromer（GitHub: [@TD-yios](https://github.com/TD-yios)）所有。你可以自由使用、修改、分发和商用，但需保留原始版权声明和许可证文本；完整条款见 [LICENSE](LICENSE)。

## 参与开发

- 提交问题或建议：https://github.com/TD-yios/index-checker/issues
- 修改代码后请先运行 `python -m unittest discover -s tests -v`。
- 不要把 `outputs/`、`dist/`、`vendor/`、代理配置、Cookie、关键词库或运行日志提交到仓库。
- 新增搜索引擎时，请在 `core/engines.py` 增加适配器，并在 `core/config.py`、UI 查询设置和测试中同步注册。

## 命令行用法

适合定时任务或批处理。旧版单关键词参数仍兼容：

```bat
python runner.py --keywords "示例品牌,北京装修公司" --domain example.com --engines baidu,bing --pages 3 --outdir outputs\run1
```

多品牌推荐用 JSON 配置：

```bat
python runner.py --config config.json
```

`config.json` 示例：

```json
{
  "tasks": [
    {"brand": "示例品牌", "keyword": "示例品牌", "target_url": "https://www.example.com", "library_id": 1},
    {"brand": "示例品牌", "keyword": "示例品牌合肥", "target_url": "https://www.example.com", "library_id": 2},
    {"brand": "示例品牌B", "keyword": "示例品牌B", "target_url": "https://www.example.org", "library_id": 3}
  ],
  "engines": {
    "baidu": {"enabled": true, "proxy": ""},
    "google": {"enabled": true, "proxy": "http://127.0.0.1:7890"},
    "bing": {"enabled": true, "proxy": ""},
    "toutiao": {"enabled": true, "proxy": ""}
  },
  "max_pages": 3,
  "stop_on_hit": true,
  "screenshot_on_hit": true,
  "screenshot_all_pages": false,
  "headless": true,
  "delay_min": 2.0,
  "delay_max": 4.0,
  "output_dir": "C:\\path\\to\\outputs\\run1"
}
```

命令行运行时输出 JSON Lines 事件流（`start` / `page` / `task_done` / `progress` / `done`），便于接入其他系统。

## 实现说明

- 桌面端使用 Python 3.13 + PySide6；Playwright 驱动浏览器，按“本机 Chrome → 内置 Chrome → 系统 Edge → Playwright Chromium”顺序自动选择
- 内置 Chrome 为官方 Chrome for Testing 品牌版，UA、TLS 指纹与真实 Chrome 一致，实测百度品牌词不会触发安全验证
- 每个引擎独立持久化 profile（`%LOCALAPPDATA%\IndexChecker\profiles`），Cookie 复用；换浏览器内核时 profile 分开存放，互不干扰
- 每个任务独立携带品牌、关键词、目标 URL，查询时按任务循环，同一品牌多个 URL 也不会串
- 每页加载后先等结果容器出现，再解析；百度品牌专区取 `#top-ad`，自然结果取 `tpl=www_*` 节点，广告取 `u2a6nht` / `ec_` / `[data-placeid]`，其余结果卡片归为聚合卡片；必应自然结果取 `li.b_algo`、广告取 `li.b_ad`；谷歌自然结果取 `#rso` 内卡片、广告取 `#tads` / `#tadsb` / `#bottomads`；头条搜索取 `div.cs-card-content` 内带 `div.text-xl a` 的结果卡片，视频 / 小视频 / 用户聚合卡片单独归为聚合卡片、不占自然位，跳过页首“头条热榜”，翻页点击“下一页”以沿用首屏 `search_id`
- 自然结果排位单独计数（广告、卡片不占自然位），因此“自然第 1 位”与页面第几条不是一回事
- 翻页间隔默认 2–4 秒随机，避免触发验证码
- 遇到验证码会记录状态并截图，不再继续该关键词的后续页

## 目录结构

```
index-checker/
├── app.py               # 桌面端主窗口（左侧导航 + 页面切换）
├── runner.py            # 查询入口（CLI / 供界面子进程调用）
├── core/
│   ├── browser.py       # 浏览器探测：本机 Chrome / 内置 Chrome / Edge / Playwright
│   ├── config.py        # 配置、多任务 tasks 校验、域名归一化
│   ├── engines.py       # 四引擎适配、结果解析、跳转还原、命中判定
│   ├── checker.py       # 浏览器会话、多任务调度、截图、事件输出
│   ├── proxy.py         # HTTP / HTTPS 代理校验与连通性测试
│   ├── library.py       # SQLite 关键词库、品牌重命名 / 合并、导入校验、状态回写
│   └── report.py        # CSV / Excel 报告
├── ui_shared.py         # 全局样式、RunnerThread、状态条、单实例、运行日志
├── ui_dialogs.py        # 新增 / 编辑关键词、品牌管理、导入校验、查询设置、关于
├── ui_library.py        # 关键词库页（品牌分组、勾选、批量操作）
├── ui_query.py          # 查询任务页（进度、结果、分类统计、日志）
├── ui_pages.py          # 工作台 / 报告中心
├── tests/               # 核心单元测试 + 可选 UI smoke
├── assets/              # 应用图标（app.ico 放大镜版 / app_plain.ico 简版备用）
├── requirements.txt
├── 启动工具.bat
├── 安装依赖.bat
├── 准备内置浏览器.ps1   # 下载/更新 Chrome for Testing
├── 打包exe.bat
├── CHANGELOG.md
├── LICENSE
└── outputs/             # 默认输出目录（不提交）
```

`dist/`、`vendor/`、`outputs/` 和运行日志都在 `.gitignore` 中，不进入仓库。

## 常见问题

**Q：关键词库里的状态什么时候变？**

查询过程中显示“查询中”；每个任务结束后写回一次结果；全部结束时按引擎聚合为已命中 / 未命中 / 异常。异常会保留摘要，方便判断是网络、验证码还是页面结构问题。

**Q：为什么百度结果里没看到域名，工具却判断命中了？**

品牌专区/品牌广告把域名位置换成了品牌名，真实地址在 `data-mu` 属性里。工具读的是真实地址，截图里也能看到“官方”标识那块就是命中位置。

**Q：提示百度安全验证怎么办？**

取消“后台运行”，重新运行，在弹出的浏览器里完成滑块；Cookie 会记住。也可以把翻页间隔调到 4–6 秒、减少一次查询的关键词数量。

**Q：换一台没有装 Chrome 的电脑还能用吗？**

能。打包版已内置 Chrome（`dist\IndexChecker\browser\chrome-win64`，约 450MB），拷贝整个 `IndexChecker` 文件夹过去即可，不需要安装浏览器或 Python。界面上会显示当前用的是本机 Chrome 还是内置 Chrome。

**Q：内置浏览器怎么更新？**

在项目目录运行 `准备内置浏览器.ps1` 会下载最新的 Chrome for Testing 稳定版到 `vendor\chrome-win64`，然后重新执行 `打包exe.bat`，会自动复制到 `dist\IndexChecker\browser`。

**Q：谷歌一直网络超时？**

谷歌需要代理。先启动 v2rayN、Clash 等客户端，提供本地 HTTP 代理端口；在“查询设置-代理设置-谷歌”里填 `http://127.0.0.1:7890` 这类地址，点右侧「测试」确认能访问 Google，再开始查询。工具只接受 HTTP / HTTPS 代理，不直接导入 `sub://` 订阅链接。

**Q：想用订阅节点怎么办？**

把订阅导入 v2rayN / Clash 等客户端，开启本地 HTTP 入站端口，再把该端口地址填进工具的代理设置。第三方订阅的时效和稳定性不由工具控制，重要查询建议用稳定节点并保留截图。

**Q：广告、品牌专区算不算收录？**

工具把命中位置拆成四类分别计数：品牌专区、聚合卡片、竞价广告、自然排名。查询结果上方可以只勾选“自然排名”查看纯自然结果，也可以四类全看；Excel“命中明细”页签的类型列支持直接筛选。自然排名单独计算，不会被广告或卡片挤占；跨页时按全局位次编号，第 2 页第 2 位就是 `#12`。

**Q：同一关键词两次结果不一样？**

搜索结果是动态的，必应/谷歌还受地域、代理节点和个性化影响，品牌专区与广告位也会变化。工具记录的是当次真实页面并保留截图，重点词建议隔天复跑 2–3 次看趋势。

**Q：能定时跑吗？**

可以，用命令行方式配合 Windows 任务计划程序，例如每天 9 点执行 `runner.py --config ...`。