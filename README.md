# 金谷仓餐厅订单与桌访合并分析系统

金谷仓餐厅（万荷店、保利店、湾里店）日常经营数据分析系统：订单桌访合并、长期入库、周期对比、平台外卖统计，以及按需的桌访语料转换与万荷饮品酒水统计。

## 背景

POS 系统同一桌客人多次扫码产生多笔独立订单，合并后才能计算真实客单价。桌访数据提供了比 POS 更可靠的就餐人数。

## 项目结构

```
├── PRD.md                              # 完整 PRD，所有规则与参数定义
├── 订单桌访合并/                         # 主工具：订单+桌访合并分析
│   ├── merge_order_zhuofang.py          #   CLI 入口，完整 pipeline
│   ├── requirements.txt                 #   pandas, openpyxl, reportlab
│   └── output/                          #   输出 PDF + MD
├── 每日订单分析/
│   ├── order_merger_skill/              #   核心算法库
│   │   ├── config.py                    #     所有可调参数
│   │   ├── data_loader.py               #     Excel 加载与清洗
│   │   ├── order_merger.py              #     核心合并算法（R0-R3.5 + 弱规则打分）
│   │   ├── aggregator.py               #     聚合、过滤、统计
│   │   ├── item_report_helpers.py       #     报告商品展示辅助
│   │   ├── report_generator.py          #     MD 报告生成
│   │   ├── pdf_generator.py             #     PDF 客单价重点订单分析
│   │   └── pdf_generator_complete.py    #     PDF 全量订单列表
│   └── jin-gu-cang-order-analysis/     #   可独立部署的纯订单分析工具
│       └── scripts/run_analysis.py      #     CLI 入口（纯订单，无桌访）
├── 长期订单分析/                          #   跨日期长期趋势分析
│   ├── main.py                          #     CLI 入口，完整 pipeline
│   ├── db_manager.py                    #     SQLite 持久化，增量检测
│   ├── multi_file_loader.py             #     多文件加载与去重
│   ├── daily_stats.py                   #     每日统计计算
│   ├── excel_writer.py                  #     4-Sheet Excel 输出
│   └── requirements.txt                 #     pandas, openpyxl
├── 周期对比分析/                          #   环比/同比周期对比
│   ├── main.py                          #     CLI 入口
│   ├── period_validator.py              #     周期校验
│   ├── comparator.py                    #     对比计算
│   ├── pdf_report.py                    #     PDF 输出
│   ├── word_report.py                   #     Word 输出
│   └── requirements.txt                 #     pandas, openpyxl, reportlab, python-docx
├── 平台外卖统计/                          #   平台外卖数据统计分析
├── 饮品订单统计/                          #   万荷饮品/酒水中类 PDF（手工按需）
└── 桌访语料转换/                          #   桌访 CSV → 语料桌访 xlsx
```

## 快速开始

### 安装依赖

```bash
pip install pandas openpyxl reportlab python-docx
```

### 订单+桌访合并分析（主工具）

```bash
cd 订单桌访合并
python3 merge_order_zhuofang.py \
    --excel "店内订单明细2026-05-08+00_00_00~2026-05-08+23_59_59.xlsx" \
    --csv "桌探数据_1.5版_65条_2026-5-8.csv"
# 可选: --store "万荷店" --output-dir "./output"
```

输出：`output/订单桌访合并_YYYYMMDD_门店.pdf` + `.md`

### 纯订单分析（不含桌访）

```bash
cd 每日订单分析/jin-gu-cang-order-analysis
python3 scripts/run_analysis.py \
    --excel "../../订单桌访合并/店内订单明细2026-04-29+...xlsx"
```

### 长期订单分析（跨日期趋势）

```bash
cd 长期订单分析
python3 main.py \
    --files "路径/文件1.xlsx" "路径/文件2.xlsx" \
    --db "output/长期订单分析.db" \
    --output-dir ./output
```

输出：`长期订单分析_YYYYMMDD_YYYYMMDD.xlsx` + SQLite 数据库（支持增量更新）

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

### 平台外卖统计 (平台经营数据分析)

```bash
cd 平台外卖统计
python3 main.py \
    --files "../原始数据/万荷平台外卖订单明细2026-05-18+00_00_00~2026-05-24+23_59_59.xlsx" \
            "../原始数据/保利平台外卖订单明细2026-05-18+00_00_00~2026-05-24+23_59_59.xlsx" \
    --db "../长期订单分析/output/长期订单分析.db" \
    --output-dir ./output
```

输出：
- `平台外卖统计_YYYYMMDD_YYYYMMDD.xlsx` — 8-Sheet 格式化外卖分析 Excel
- `平台外卖统计_YYYYMMDD_YYYYMMDD.pdf` — 中文 A4 外卖摘要 PDF 报告
- `平台外卖统计_YYYYMMDD_YYYYMMDD.md` — 易于复制的 Markdown 简报
- 数据库增量归档 — 订单数据自动脱敏写入 SQLite `takeaway_*` 系列表

### 饮品/酒水订单统计（万荷，按需手工）

```bash
四维度自动评审/.venv/bin/python 订单与桌访合并/饮品订单统计/generate_drink_order_stats_pdf.py \
  --excel "path/店内订单明细...万荷.xlsx" \
  --output "path/万荷饮品酒水订单统计_YYYYMMDD_YYYYMMDD.pdf" \
  --mode week \
  --db 订单与桌访合并/长期订单分析/output/长期订单分析.db
```

十一类商品中类；收入排除套餐父项、保留套餐子项，额占比分母为整体营业额。含 `--mode` 时输出摘要三期原始数据、本周简表与同比环比对比表（A4 横置）。详见 `饮品订单统计/README.md`。

### 桌访语料转换（四维度心理学奖）

```bash
cd 桌访语料转换
python3 convert_corpus.py "/path/to/桌访数据_...csv"
```

输出 `语料桌访_1.5版_*.xlsx`。详见 `桌访语料转换/README.md`。

### GUI 控制台 (统一图形化操作界面)

```bash
# 启动 GUI 桌面控制台
.venv/bin/python3 GUI控制台/main.py
```

**界面特性**：
- **极客暗黑主题**：高阶 QSS 视觉体系，带呼吸效果的交互指示和文件拖入高亮。
- **全拖拽支持**：支持拖入单个/多个文件或文件夹，自动识别分类（POS Excel, 桌访 CSV, 外卖 Excel, SQLite 数据库）。
- **实时预校验**：在后台线程提取 Excel 表头和结构进行预检，Error 级别时禁用运行按钮，Warning 级别提供风险评估。
- **异步安全任务引擎**：利用 QProcess 异步调度分析命令，实时截获 stdout/stderr 渲染到嵌入式控制台，并配备 SQLite 写入锁防止数据库并发冲突。
- **多功能支持**：集成订单+桌访合并、长期订单分析、周期对比分析、平台外卖统计以及全局参数偏好保存五大功能面板。



## 核心算法

### 订单合并（order_merger.py）

仅在相同桌台内合并，按优先级第一个命中即决策：

- **R0 并发拆单**：下单间隔 < 5 分钟 → 直接合并
- **R1 时间窗口**：距首单超时（普通 2h / 包间 3h）→ 新开会话（小单例外）
- **R2 加单金额上限**：候选收入 > 锚点 × 50% → 新开会话
- **R3 结账后间隔**：距结账超时（普通 30min / 包间 120min）→ 新开会话
- **R3.5 包间晚餐纯酒水加单**：包间 + 17:00-23:00 + 全酒水 → 直接合并
- **弱规则打分**：时间/手机号/人数/支付方式/商品相似度等，≥60 合并

### 桌访匹配（三级递进）

1. **订单号精确匹配**：直接关联
2. **三选二模糊匹配**：桌台号子串 + 支付金额相等 + 下单时间差 ≤ 5min，三条件任意两个成立即匹配（含订单号在 POS 中不存在的记录）
3. **未匹配公示**：剩余记录在 PDF 索引下方完整列出供人工核查

## 输入数据格式

- **POS Excel**：两个 Sheet——「店内订单明细」（订单主表）+「商品-店内订单明细」（商品明细）
- **桌访 CSV**：UTF-8-SIG 编码，含订单号、桌台号、就餐人数、支付金额、服务员等字段

## 已知限制

- 中文 PDF 依赖系统字体（macOS 自带 STHeiti/PingFang，Linux 需 wqy-microhei）
- 合并算法可能将同台翻台误判为同一批客人
- 桌台号命名差异（CSV "B07" vs POS "大厅B区B07"）通过子串匹配处理
- 仅支持 macOS / Linux，Windows 需自行调整字体路径

## 许可

内部使用项目。
