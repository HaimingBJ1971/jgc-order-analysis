#!/usr/bin/env python3
"""
金谷仓订单分析 Skill 执行脚本。
"""
import argparse
import json
import os
import sys


def build_parser():
    parser = argparse.ArgumentParser(
        description="读取餐饮订单 Excel 并生成两个 PDF 报告。"
    )
    parser.add_argument(
        "--excel",
        required=True,
        help="订单 Excel 文件路径（.xlsx）",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="输出目录，默认与 Excel 同目录",
    )
    return parser


def resolve_project_module():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    workspace_root = os.path.dirname(base_dir)
    module_dir = os.path.join(workspace_root, "order_merger_skill")
    if module_dir not in sys.path:
        sys.path.insert(0, module_dir)
    return module_dir


def main():
    args = build_parser().parse_args()
    excel_path = os.path.abspath(args.excel)

    if not os.path.isfile(excel_path):
        raise FileNotFoundError(f"Excel 文件不存在: {excel_path}")
    if not excel_path.lower().endswith(".xlsx"):
        raise ValueError(f"仅支持 .xlsx 文件: {excel_path}")

    output_dir = (
        os.path.abspath(args.output_dir) if args.output_dir else os.path.dirname(excel_path)
    )
    os.makedirs(output_dir, exist_ok=True)

    module_dir = resolve_project_module()
    if not os.path.isdir(module_dir):
        raise FileNotFoundError(
            f"未找到核心模块目录: {module_dir}。请确认压缩包中包含 order_merger_skill 目录。"
        )

    from main import main as run_pipeline  # type: ignore

    markdown_path, complete_pdf_path, highlight_pdf_path = run_pipeline(
        excel_file_path=excel_path,
        output_dir=output_dir,
        generate_pdf=True,
    )

    if complete_pdf_path is None or highlight_pdf_path is None:
        raise RuntimeError("PDF 生成失败，未返回完整的输出路径。")

    result = {
        "excel": excel_path,
        "output_dir": output_dir,
        "complete_pdf": os.path.abspath(complete_pdf_path),
        "highlight_pdf": os.path.abspath(highlight_pdf_path),
        "markdown": os.path.abspath(markdown_path),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
