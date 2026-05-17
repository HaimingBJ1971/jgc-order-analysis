# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

金谷仓餐厅（万荷店、保利店、湾里店）日常经营数据分析系统。核心功能：将 POS 散单合并为消费团体 → 关联桌访反馈修正人数 → 重新计算人均消费 → 输出 PDF/MD 报告。

POS 系统同一桌客人多次扫码产生多笔独立订单，合并后才能计算真实客单价。桌访数据提供了比 POS 更可靠的就餐人数。

## 目录结构

```
订单与桌访合并/
├── PRD.md                            # 完整 PRD（v3.10），所有规则与参数定义
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

### 安装依赖

```bash
pip install pandas openpyxl reportlab
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

## 重要修改注意事项

- 所有可调参数在 `order_merger_skill/config.py`，不要在业务逻辑中硬编码阈值
- 修改合并算法前先读 `每日订单分析/订单合并逻辑优化_*.plan.md` 了解历史设计决策
- PRD.md 是规范文档，算法变更后需同步更新 PRD
- 改 `order_merger_skill` 会影响两个工具（主工具和纯订单分析工具）
- 商品名称含全角/半角括号差异，匹配时需统一规范化处理
