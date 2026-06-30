# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## 项目概述

金谷仓餐厅（万荷店、保利店、湾里店）日常经营数据分析系统。核心功能：将 POS 散单合并为消费团体 → 关联桌访反馈修正人数 → 重新计算人均消费 → 输出 PDF/MD 报告。

POS 系统同一桌客人多次扫码产生多笔独立订单，合并后才能计算真实客单价。桌访数据提供了比 POS 更可靠的就餐人数。

## 目录结构

```
订单与桌访合并/
├── PRD.md                            # 完整 PRD（v3.17），所有规则与参数定义
├── 订单桌访合并/                      # ★ 主工具：订单+桌访合并分析
│   ├── merge_order_zhuofang.py       #   CLI 入口，完整 pipeline（唯一入口文件）
│   └── ...
├── 每日订单分析/
│   └── order_merger_skill/           # ★ 核心算法库（合并、聚合、报告）
├── 长期订单分析/                      # ★ 跨日期长期订单趋势 + SQLite 主库
├── 周期对比分析/                      # ★ 周期环比/同比对比
│   ├── main.py                       #   CLI 入口 + 报告
│   └── ingest_store_stats.py         #   单店入库（不写报告）
├── 平台外卖统计/                      # ★ 平台外卖订单统计分析
├── 饮品订单统计/                      # ★ 万荷饮品 PDF（手工按需；可选周/月同比环比）
│   └── generate_drink_order_stats_pdf.py
├── 桌访语料转换/                      # ★ 桌访 CSV → 语料桌访 xlsx（四维度心理学奖）
│   └── convert_corpus.py
└── 桌探邮件下载/                      #   IMAP 拉取桌探日报 CSV
```

## 常用命令

### 订单+桌访合并分析（主工具）

```bash
cd 订单桌访合并
python3 merge_order_zhuofang.py \
    --excel "店内订单明细2026-04-29+00_00_00~2026-04-29+23_59_59.xlsx" \
    --csv "桌探数据_1.5版_50条_2026-4-29.csv"
# 可选参数: --store "万荷店" --output-dir "./output"
```

输出：`output/订单桌访合并_YYYYMMDD_门店.pdf` + `.md`

### 纯订单分析（不含桌访）

```bash
cd 每日订单分析/jin-gu-cang-order-analysis
python3 scripts/run_analysis.py \
    --excel "../../订单桌访合并/店内订单明细2026-04-29+...xlsx"
```

输出：`订单列表_YYYYMMDD.pdf` + `客单价重点订单分析_YYYYMMDD.pdf`

### 长期订单分析（跨日期趋势）

```bash
cd 长期订单分析
python3 main.py \
    --files "路径/文件1.xlsx" "路径/文件2.xlsx" \
    --db "output/长期订单分析.db" \
    --output-dir ./output
```

输出：`长期订单分析_YYYYMMDD_YYYYMMDD.xlsx` + SQLite 数据库（持久化增量更新）
Excel 含 4 个 Sheet：数据总览、订单数量明细、客单价区间分布、开单人统计

### 周期对比分析（环比/同比）

```bash
cd 周期对比分析
python3 main.py \
    --excel "店内订单明细_2026-05-11+...xlsx" \
    --db "../长期订单分析/output/长期订单分析.db" \
    --mode week \
    --store "万荷店" \
    --output-dir ./output
```

输出：`周期对比分析_YYYYMMDD_YYYYMMDD_门店.pdf` + `.docx`
含五个章节：经营数据、酒水饮料甜品排行、重点菜品、商品中类销售额、客单价区间，环比/同比变化带颜色标注。第四节表下备注会列出本期全部「未分类」商品（POS 中类为 `-` 或空），供后台补全。

### 饮品/酒水订单统计（万荷，按需手工）

```bash
cd "/Users/jgc/Documents/每周:月工作"
四维度自动评审/.venv/bin/python 订单与桌访合并/饮品订单统计/generate_drink_order_stats_pdf.py \
  --excel "path/店内订单明细...万荷.xlsx" \
  --output "path/万荷饮品酒水订单统计_YYYYMMDD_YYYYMMDD.pdf" \
  --mode week \
  --db 订单与桌访合并/长期订单分析/output/长期订单分析.db
```

输出：十一类商品中类（非酒精 5 + 含酒精 6），团体数/人数/销量/点购率/收入与整体营业额占比。统计口径复用订单桌访合并 pipeline（消费团体，非 POS 原始单数）。

含 `--mode` 时：摘要三期原始数据 + 分品类/维度「本周简表」与「同比环比三行对比表」分章展示；A4 横置。仅本期时 A4 纵置。**未纳入** `run_cycle.py`。

详见 `饮品订单统计/README.md`。

### 桌访语料转换（四维度心理学奖前置）

```bash
cd 桌访语料转换
../../四维度自动评审/.venv/bin/python convert_corpus.py \
  "/path/to/桌访数据_2026-06-08_至_2026-06-14_467条.csv"
```

输出：`语料桌访_1.5版_N条_YYYY-M-D.xlsx`，供四维度「心理学案例采纳奖」。详见 `桌访语料转换/README.md`。

### 单店统计入库（历史包或指定日期段，不写报告）

```bash
cd 周期对比分析
python3 ingest_store_stats.py \
    --excel "万荷店内订单明细....xlsx" \
    --store "万荷店" \
    --db "../长期订单分析/output/长期订单分析.db"
# 可选: --start 2025-06-09 --end 2025-06-15
```

### 数据库入库纪律（单店）

- 周期对比、单店入库必须 `--store 万荷店|保利店`；`daily_overview` 等表按 `store_name` 读写，禁止两店 POS 合并后再做分店对比。
- **判店以 POS 字段 `门店名称` 为准**（Excel 元数据/订单内容），文件名只用于一致性校验，不得作为判店兜底；`relabel_*` 只更新与 `--store` 匹配的订单，避免跨店误标。
- 长期订单分析多文件入库时，`daily_order_counts` 的 `原始订单数`、`外卖订单数`、`非堂食订单数` 必须按 `store_name` 分店统计；禁止把双店合计数重复写入每个门店行。
- 商品明细入库与统计必须保留 POS 原始行级明细；同一订单内同一商品出现多行时，应累计每一行数量和收入，禁止按 `订单号 + 商品编码 + 商品名称` 去重或覆盖。
- 周期对比报告分清两类口径：第一节经营数据中，**整体营业额 = 堂食分桌总营业额 + 自取外卖单、吧台及零食购买团体、第三方平台外卖单合计**。整体营业额包含 POS 店内全量正收入订单与第三方平台外卖已完成订单收入，用于和后台营业收入闭环；第五节客单价区间仍以堂食分桌口径计算。
- 周期对比第二节酒水饮料甜品、第三节重点菜品、第四节商品中/大类销售额，采用 **POS 店内商品归因口径**：包含自取外卖单、吧台及零食购买团体；排除赠送、免单、全额优惠等 `菜品收入 <= 0` 的商品行；套餐必须排除“套餐”父项，只保留有 `菜品收入 > 0` 的“套餐子项”归入实际商品品类，避免父项和子项重复统计，并使商品归因收入与 POS 店内订单收入闭合。若参考 POS「菜品综合统计表」，不得用“销售数量 - 赠菜数量”替代正收入销量；全额优惠/免单也必须剔除。第三方平台外卖若无商品级明细，不得猜测归类，只能计入订单级整体营业额。
- 万荷饮品酒水统计中，统计范围为十一类商品中类：调饮汁、饮料和水果、茶、咖啡、冰淇淋、啤酒、白酒、葡萄酒、鸡尾酒、苏格兰威士忌、黄酒。团体数、人数沿用有效消费团体口径；所有“销量”“收入”和“点购率”的销量分子采用 POS 店内商品归因口径，排除赠送、免单、全额优惠等 `菜品收入 <= 0` 的商品行，且排除“套餐”父项、保留有收入的“套餐子项”；不得用“销售数量 - 赠菜数量”替代正收入销量。饮品报告必须展示整体营业额闭环：POS 店内订单收入 + 第三方平台外卖已完成订单收入 = 整体营业额；各饮品品类“额占比”用该整体营业额作分母。第三方平台外卖饮品收入只有在提供商品级明细时才可归入饮品品类。
- 若历史库存在万荷文件名下的保利订单，运行 `长期订单分析/fix_store_sources.py --db ...` 一次性纠正 `source_file`。
- 两店历史入库完成后，运行 `长期订单分析/cleanup_db.py --db ...` 删除 `__legacy__` 汇总行与无效订单（`--dry-run` 可先预览）。
- 外卖 Excel 以表头「门店名称」为准，不以文件名为准。
- POS 占位中类 `-`/空 在报告中归并为 **未分类**，并在中类表下备注列出全部未分类商品名称。
- **保利店**第四节改用 **商品大类** 同比/环比（POS 未维护中类）；万荷店仍用商品中类。

### 保利店历史数据（已封存，2026-06-15 起）

保利店历史 POS（2025-05-28 ~ 2026-06-14，含历史包 + 5/27~6/14 补充包）已入库。**默认禁止再次导入**历史包/补充包，除非改账、漏导或库损坏。日常每周只入库当周保利 POS。

**已知缺口**：2026-02-15 ~ 2026-02-23（历史包无数据，疑春节歇业；若当时有营业需单独补导）。

### 万荷店历史数据（已封存，2026-06-15 起）

万荷店三包历史 POS（2023-10-08 ~ 2026-06-04）及第 23–24 周周 POS 已入库并完成单店打标。**默认禁止再次导入**，除非：POS 后台大规模改账、发现某段日期漏导、或数据库损坏重建。

日常每周只需：当周万荷 POS + `ingest_store_stats` 或 `main.py --store 万荷店` 更新当周；**不要**重复跑三包历史 `ingest_store_stats`。

### 安装依赖

```bash
pip install pandas openpyxl reportlab python-docx
```

## 核心架构

### 模块依赖关系

```
merge_order_zhuofang.py
  ├── 通过 sys.path 引入 ../每日订单分析/order_merger_skill
  │     ├── data_loader.py
  │     ├── order_merger.py → config.py
  │     ├── aggregator.py
  │     └── item_report_helpers.py

run_analysis.py → 依赖 order_merger_skill（同上）

main.py (长期订单分析)
  ├── 通过 sys.path 引入 ../每日订单分析/order_merger_skill
  ├── db_manager.py → SQLite 持久化与增量检测
  ├── multi_file_loader.py → 多文件加载去重
  ├── daily_stats.py → 每日统计计算
  └── excel_writer.py → 4-Sheet Excel 输出

main.py (周期对比分析)
  ├── 通过 sys.path 引入 ../每日订单分析/order_merger_skill
  ├── db_manager.py（复用长期订单分析的） → 历史数据读取
  ├── period_validator.py → 周/月周期完整性校验
  ├── comparator.py → 环比/同比计算
  ├── pdf_report.py → PDF 报告
  └── word_report.py → Word 报告

generate_drink_order_stats_pdf.py (饮品订单统计)
  ├── merge_order_zhuofang.load_and_process_orders() → 本期消费团体口径
  ├── period_validator / db_manager → 环比/同比期（主库 kept 团体）
  └── reportlab → A4 纵置（仅本期）或 A4 横置（含同比环比）
```

**关键约束**：`merge_order_zhuofang.py` 通过相对路径 `../每日订单分析/order_merger_skill` 导入，不通过 pip install。目录结构必须保持不变。

### 数据 Pipeline 流程（merge_order_zhuofang.py）

1. `load_excel()` → `clean_orders()` / `clean_items()` → 清洗（去汇总行、只留堂食、排除外点自取）
2. `merge_orders()` → 核心合并算法，输出 `orders_with_group`（每笔订单新增消费团体ID）
3. `aggregate_groups()` → 聚合为消费团体，过滤免单/零食/打包/零散/吧台
4. 加载 CSV 桌访 → `match_unrecognized_by_table_amount()` 三选二匹配无订单号记录
5. `associate_feedback()` → 关联桌访，人数修正，重算人均
6. `detect_anomalies()` → 异常检测（人数与商品数不匹配、人均过低、同桌台疑似同批）
7. `generate_pdf_report()` + `generate_markdown_report()` → 输出

### 核心合并算法（order_merger.py）

仅在相同桌台内合并。规则按优先级，第一个命中即决策：

- **R0 并发拆单**：下单间隔 < 5分钟 → 直接合并
- **R1 时间窗口**：距首单超时（普通2h/包间3h）→ 新开会话（小单例外）
- **R2 加单金额上限**：候选收入 > 锚点 × 50% 且 锚点单自身 > 20 元时才触发拆分（防止 ¥5 水/湿巾等小开单误拆分） → 新开会话
- **R3 结账后间隔**：距结账超时（普通30min/包间120min）→ 新开会话（小单例外）
- **R3.5 包间晚餐纯酒水加单**：包间 + 17:00-23:00 + 全酒水 → 直接合并
- **弱规则打分**：时间接近/手机号/人数/支付方式/Jaccard 商品相似度/小单加分等，≥60合并

所有参数定义在 `order_merger_skill/config.py`。

### 桌访匹配三级递进策略

1. **订单号精确匹配**：直接关联
2. **三选二模糊匹配**：桌台号子串 + 支付金额相等 + 下单时间差≤5min，三条件任意两个成立即匹配
3. **未匹配公示**：剩余记录在 PDF 报告索引下方完整列出供人工核查

查找匹配逻辑在 `merge_order_zhuofang.py` 的 `match_unrecognized_by_table_amount()` 函数中。

### 中文 PDF 字体

各模块在启动时自动搜索系统字体：macOS 优先 STHeiti/PingFang，Linux 回退到 wqy-microhei/wqy-zenhei，最终 fallback 到 Helvetica（中文乱码）。如部署到非 macOS 环境需确保系统有中文字体。

## 输入数据格式

- **POS Excel**：两个 Sheet——「店内订单明细」（订单主表）+「商品-店内订单明细」（商品明细），文件名必须含 `YYYY-MM-DD`
- **桌访 CSV**：编码 UTF-8-SIG/GBK 等自动检测，文件名格式 `桌探数据_1.5版_N条_YYYY-M-D.csv`
- 详细字段定义见 PRD.md 第四章

## 重要修改注意事项

- 所有可调参数在 `order_merger_skill/config.py`，不要在业务逻辑中硬编码阈值
- 修改合并算法前先读 `每日订单分析/订单合并逻辑优化_*.plan.md` 了解历史设计决策
- PRD.md 是规范文档，算法变更后需同步更新 PRD
- 改 `order_merger_skill` 会影响全部三个工具
- 保利店与万荷店有差异化参数：异常检测阈值（¥15 vs ¥10/20/30）、红色预警线（¥40 vs ¥100）、重点菜品列表（2道 vs 14道）、桌台分类（包房/沙发）
- `_area()` 分类规则：包间/包房→包间，大厅/沙发→大厅，户外→户外，其余→其他。数据闭合校验会自动告警"其他"分类
- 商品名称含全角/半角括号差异，匹配时需统一规范化处理
