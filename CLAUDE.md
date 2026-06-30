# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

金谷仓餐厅（万荷店、保利店、湾里店）日常经营数据分析系统。核心功能：将 POS 散单合并为消费团体 → 关联桌访反馈修正人数 → 重新计算人均消费 → 输出 PDF/MD 报告。

POS 系统同一桌客人多次扫码产生多笔独立订单，合并后才能计算真实客单价。桌访数据提供了比 POS 更可靠的就餐人数。

## 目录结构

```
订单与桌访合并/
├── PRD.md                            # 完整 PRD（v3.16），所有规则与参数定义
├── 订单桌访合并/                      # ★ 主工具：订单+桌访合并分析
│   ├── merge_order_zhuofang.py       #   CLI 入口，完整 pipeline（唯一入口文件）
│   ├── requirements.txt              #   pandas, openpyxl, reportlab
│   ├── output/                       #   输出 PDF + MD
│   ├── 店内订单明细_*.xlsx            #   输入：POS 订单
│   └── 桌探数据_*.csv                #   输入：桌访反馈
├── 每日订单分析/
│   ├── order_merger_skill/           # ★ 核心算法库（6个模块）
│   │   ├── config.py                 #   所有可调参数
│   │   ├── data_loader.py            #   Excel 加载与清洗
│   │   ├── order_merger.py           #   核心合并算法（R0-R3.5 + 弱规则打分）
│   │   ├── aggregator.py             #   聚合、过滤、统计
│   │   ├── item_report_helpers.py    #   报告商品展示辅助
│   │   ├── report_generator.py       #   MD 报告生成
│   │   ├── pdf_generator.py          #   PDF「客单价重点订单分析」
│   │   └── pdf_generator_complete.py #   PDF「全量订单列表」
│   └── jin-gu-cang-order-analysis/   # 可独立部署的纯订单分析 Skill 外壳
│       └── scripts/run_analysis.py   #   CLI 入口（纯订单，无桌访）
├── 长期订单分析/                      # ★ 新增：跨日期长期订单趋势分析
│   ├── main.py                       #   CLI 入口，完整 pipeline
│   ├── db_manager.py                 #   SQLite 读写、增量检测
│   ├── multi_file_loader.py          #   多文件加载与去重
│   ├── daily_stats.py                #   每日统计计算（4个Sheet）
│   ├── excel_writer.py               #   4-Sheet Excel 输出
│   └── requirements.txt              #   pandas, openpyxl
├── 周期对比分析/                      # ★ 新增：周期环比/同比对比分析
│   ├── main.py                       #   CLI 入口，完整 pipeline
│   ├── period_validator.py           #   周期完整性校验
│   ├── comparator.py                 #   同比环比计算引擎
│   ├── pdf_report.py                 #   PDF 对比报告生成
│   ├── word_report.py                #   Word 对比报告生成
│   └── requirements.txt              #   pandas, openpyxl, reportlab, python-docx
├── 平台外卖统计/
├── 饮品订单统计/                      #   万荷饮品 PDF（按需；可选周/月同比环比）
└── 桌访语料转换/                      #   四维度语料前置
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
含五个章节：经营数据、酒水饮料甜品排行、重点菜品、商品中类销售额、客单价区间，环比/同比变化带颜色标注。

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
```

**关键约束**：`merge_order_zhuofang.py` 通过相对路径 `../每日订单分析/order_merger_skill` 导入，不通过 pip install。目录结构必须保持不变。

### SQLite 数据库结构

长期订单分析和周期对比分析共用 SQLite 数据库，由 `长期订单分析/db_manager.py` 的 `DatabaseManager` 类创建和维护。共 7 张表：

| 表名 | 用途 | 去重键 |
|------|------|--------|
| `orders` | 原始订单（整行 JSON 序列化存储） | `订单号` PRIMARY KEY |
| `items` | 商品明细（整行 JSON 序列化存储） | UNIQUE INDEX `(订单号, 商品编码, 商品名称)` |
| `groups` | 消费团体聚合结果 | UNIQUE `(group_date, first_order_id, table_name)` |
| `daily_overview` | 每日经营数据总览（整体/分区/午晚市/会员） | PRIMARY KEY `(date, category, sub_category)` |
| `daily_order_counts` | 每日订单数量明细（pipeline 各阶段计数） | `date` PRIMARY KEY |
| `daily_buckets` | 每日客单价区间分布（5档） | PRIMARY KEY `(date, bucket)` |
| `daily_opener_stats` | 每日开单人统计 | PRIMARY KEY `(date, opener_name)` |

`items` 表用 `(订单号, 商品编码, 商品名称)` 复合唯一索引而非对 JSON 字段去重，原因是早期直接对 `原始数据` JSON 字符串做 UNIQUE 约束时，dict 序列化顺序不稳定导致同一条记录被重复插入。

所有 daily_* 表通过 `INSERT OR REPLACE` 写入，支持重复运行自动覆盖更新。

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
- **R2 加单金额上限**：候选收入 > 锚点 × 50% → 新开会话
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

## 门店差异化参数

万荷店与保利店在多个维度有不同参数。修改时注意两个门店都要覆盖。

| 参数 | 万荷店 | 保利店 |
|------|--------|--------|
| 异常检测人均阈值（规则2a/2b/2c） | ¥10 / ¥20 / ¥30 | 统一 ¥15 |
| 订单索引红色预警线 | 人均 < ¥100 | 人均 < ¥40 |
| 重点菜品数量 | 14 道 | 2 道 |
| 重点菜品列表 | 富顺鸡丝凉面、古法干烧鱼（江团+鲈鱼合并）、富顺荤豆花、206省道半汤牛蛙、酸菜煸炒土豆片、香菜回锅茄子、火爆腰花、炝炒莲花白菜、金阳青花椒辣子鸡、鱼香梅花肉丝、文庙担担面、茂萱婆婆芽菜包、百合蜜枣无花果排骨汤 | 川南鱼香肉丝（不能免葱）、香菜回锅茄子 |
| 桌台分类关键词 | 包间 / 大厅 / 户外 | 包房 / 沙发 / 户外 |
| PDF 第六章 | 重点菜品销售统计 | 重点菜品销售统计（仅2道） |
| PDF 第七章 | 重点新品销售统计 | 午晚热销统计（午市/晚市各 Top 6） |

万荷店 14 道重点菜完整列表见 `周期对比分析/comparator.py:296-300`。

## 重要修改注意事项

- 所有可调参数在 `order_merger_skill/config.py`，不要在业务逻辑中硬编码阈值
- 修改合并算法前先读 `每日订单分析/订单合并逻辑优化_*.plan.md` 了解历史设计决策
- PRD.md 是规范文档，算法变更后需同步更新 PRD
- 改 `order_merger_skill` 会影响全部三个工具
- `_area()` 分类规则：包间/包房→包间，大厅/沙发→大厅，户外→户外，其余→其他。如果出现"其他"分类，说明 POS 数据中出现了未预期的桌台命名
- `merge_order_zhuofang.py` 中 `_validate_closure()` 校验区域/午晚市/会员三个维度的营业额之和是否等于整体营业额，不一致时在报告中打印告警
- 商品名称含全角/半角括号差异，匹配时需统一规范化处理（`replace('（', '(').replace('）', ')')`）

### 酒水饮料归组

周期对比分析的"酒水饮料甜品销售排行"中，`_base_name()` 去掉末尾括号内的规格描述（杯/小瓶/大瓶/扎/壶/盅等），同名商品归组显示。例如「凤梨洛神花果茶(杯)」「凤梨洛神花果茶(大瓶)」归为一组。

筛选范围由 `comparator.py` 中 `DRINK_DESSERT_CATS` 定义（饮料和水果、调饮汁、甜品、啤酒、葡萄酒、茶、咖啡、冰淇淋、鸡尾酒等），且排除 `菜品收入 <= 0` 的商品（有销量但金额为 0 的免单/测试商品）。
