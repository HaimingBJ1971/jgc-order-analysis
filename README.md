# 金谷仓餐厅订单与桌访合并分析系统

金谷仓餐厅（万荷店、保利店、湾里店）日常经营数据分析工具。核心功能：将 POS 散单合并为消费团体 → 关联桌访反馈修正人数 → 重新计算人均消费 → 输出 PDF/MD 报告。

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
```

## 快速开始

### 安装依赖

```bash
pip install pandas openpyxl reportlab
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
