# 金谷仓订单分析 Skill

该目录是可移植的 Skill 壳层，复用同级目录 `order_merger_skill` 中的成熟算法，输入一份门店订单 Excel，输出两个 PDF 报告。

## 目录说明

- `SKILL.md`：Skill 规范与触发说明
- `requirements.txt`：依赖列表
- `scripts/run_analysis.py`：执行入口

## 使用方式（Openclaw 4.2 / macOS）

1. 将压缩包解压到任意目录，确保以下两个目录并列存在：
   - `jin-gu-cang-order-analysis`
   - `order_merger_skill`
2. 安装依赖：

```bash
python3 -m pip install -r jin-gu-cang-order-analysis/requirements.txt
```

3. 执行：

```bash
python3 jin-gu-cang-order-analysis/scripts/run_analysis.py --excel "/path/to/店内订单明细xxxx.xlsx"
```

## 业务排除

- `桌台` 名称中含 **「外点自取」** 的订单视为外卖，**不参与**统计；商品明细中对应订单号一并剔除。

## 输出

脚本会输出 JSON，其中包含：

- `complete_pdf`：订单列表 PDF
- `highlight_pdf`：客单价重点订单分析 PDF

默认输出目录为 Excel 所在目录，可通过 `--output-dir` 指定。
