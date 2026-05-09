# 餐饮订单合并与客单价分析系统

## 项目简介

这是一个用于餐饮POS系统订单智能合并与客单价（人均消费）计算的工具。通过启发式规则识别属于同一桌客人的订单（主订单+加单），还原真实的客单价，为营销决策提供准确的数据支撑。

## 目录结构

```
order_merger_skill/
├── __init__.py       # 包初始化文件
├── config.py         # 配置参数（可调优）
├── data_loader.py    # 数据加载与预处理模块
├── order_merger.py   # 订单合并算法模块
├── aggregator.py     # 数据聚合与客单价计算模块
├── report_generator.py  # Markdown报告生成模块
├── pdf_generator.py  # PDF重点订单分析报告生成模块
├── main.py           # 主程序入口
└── README.md         # 本文件
```

## 功能特性

### 核心功能
- 智能识别并合并同一桌客人的订单
- 计算真实的客单价（人均消费）
- 生成美观的Markdown格式完整分析报告
- 生成PDF格式重点订单分析报告（客单价最高/最低各3个）
- 按客单价从高到低排序展示

### 合并规则
采用两段式规则体系：

**强规则（硬约束）：**
1. 桌台一致性 - 必须是同一桌台
2. 时间窗截止 - 超过主单下单时间3小时不合并
3. 订单状态过滤 - 剔除作废/撤单订单
4. 翻台判定 - 结账后间隔过长且非小单形态不合并

**弱规则（打分系统，阈值60分）：**
- 小单/加单形态识别（20分）
- 会员手机号一致性（25分）
- 就餐人数相近（15分）
- 支付方式一致（5分）
- 菜品集合相似（10分）
- 员工/操作人一致（5分）
- 备注一致（5分）

## 安装与使用

### 环境要求
- Python 3.7+
- pandas
- openpyxl

### 安装依赖
```bash
# 创建虚拟环境（推荐）
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install pandas openpyxl
```

### 快速开始

#### 方式1：使用默认文件
```bash
cd order_merger_skill
python main.py
```

#### 方式2：指定文件路径
```bash
cd order_merger_skill
python main.py /path/to/your/order_file.xlsx
```

### 输出文件
程序会在Excel文件所在目录生成Markdown报告：
```
客单价分析报告_YYYY-MM-DD.md
```

## 配置参数

可以通过修改 `config.py` 中的参数进行调优：

| 参数名 | 默认值 | 说明 |
|--------|--------|------|
| T_WINDOW_HOURS | 3 | 时间窗口（小时） |
| T_REOPEN_MIN | 60 | 结账后容忍追加间隔（分钟） |
| SETTLE_GRACE_MIN | 15 | 紧邻结账强合并区间（分钟） |
| SMALL_RATIO | 0.30 | 小单比例阈值 |
| SMALL_LINE_CNT | 2 | 小单商品行数阈值 |
| HEADCOUNT_TOL | 1 | 就餐人数容忍度 |
| SCORE_THRESHOLD | 60 | 弱规则打分阈值 |

## 输入数据格式

### Excel文件要求
Excel文件需包含以下两个Sheet：

1. **店内订单明细**（订单表）
   - 订单号
   - 桌台
   - 下单时间
   - 结账时间
   - 订单金额
   - 订单收入
   - 就餐人数
   - 会员手机号
   - 订单类型
   - 支付方式
   - 整单备注

2. **商品-店内订单明细**（商品表）
   - 订单号
   - 商品编码
   - 商品名称
   - 规格
   - 单价
   - 数量
   - 菜品合计金额
   - 商品中类
   - 商品大类

## 报告说明

生成的Markdown报告包含：

- 按客单价从高到低排序的所有消费团体
- 每个团体的基本信息：
  - 首单订单号
  - 主单订单号（若有合并）
  - 下单/结账时间
  - 客人数
  - 总金额/订单收入
  - 人均消费（客单价）
  - 包含的订单号列表
- 详细的商品明细列表

## 示例

```python
# 在Python代码中使用
from order_merger_skill.main import main

# 处理Excel文件，生成Markdown和PDF报告
md_file, pdf_file = main("/path/to/order_file.xlsx")
print(f"Markdown报告: {md_file}")
print(f"PDF报告: {pdf_file}")

# 只生成Markdown报告，不生成PDF
md_file, _ = main("/path/to/order_file.xlsx", generate_pdf=False)
```

## 注意事项

1. 仅处理"堂食"类型的订单
2. `桌台` 名称含「外点自取」的订单视为外卖，不参与统计
3. 就餐人数优先取收入最高订单的人数，而非累加
4. 建议根据门店实际业务特点调优参数
5. 首次使用建议先用小数据集测试

## 技术支持

如有问题，请检查：
1. Excel文件格式是否正确
2. 是否包含必需的两个Sheet
3. 表头前的元数据是否能被自动识别
4. Python依赖是否完整安装

## 许可证

本项目仅供内部使用。
