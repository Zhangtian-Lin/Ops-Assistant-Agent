"""CLI 命令行入口 — skill-scanner"""

import argparse
import sys

from .scan_engine import ScanEngine
from .reporters import generate_json, generate_markdown
from .rules import ALL_RULES


def main():
    parser = argparse.ArgumentParser(
        prog="skill-scanner",
        description="AI Security Skill Scanner — 对 NSEAP Skill 目录进行安全风险扫描",
    )
    parser.add_argument(
        "-i", "--input",
        default=None,
        help="Skill 目录路径",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="输出文件路径（默认输出到 stdout）",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["json", "markdown", "md"],
        default="markdown",
        help="输出格式 (default: markdown)",
    )
    parser.add_argument(
        "-l", "--min-level",
        choices=["L0", "L1", "L2", "L3", "L4", "L5"],
        default=None,
        help="最低风险等级过滤",
    )
    parser.add_argument(
        "--rules",
        default=None,
        help="指定规则 ID，逗号分隔（如 R1_CREDENTIAL_LEAK,R2_COMMAND_INJECTION）",
    )
    parser.add_argument(
        "--list-rules",
        action="store_true",
        help="列出所有可用规则",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="skill-scanner 1.0.0",
    )

    args = parser.parse_args()

    # --list-rules
    if args.list_rules:
        print("可用规则:")
        for r in ALL_RULES:
            print(f"  {r.rule_id:30s} {r.rule_name}")
        return

    # -i is required for scanning
    if not args.input:
        parser.error("the following arguments are required: -i/--input")

    # 创建引擎
    engine = ScanEngine()

    # 执行扫描
    try:
        if args.rules:
            rule_ids = [x.strip() for x in args.rules.split(",")]
            result = engine.scan_with_filter(args.input, rule_ids)
        elif args.min_level:
            result = engine.scan_with_level(args.input, args.min_level)
        else:
            result = engine.scan(args.input)
    except FileNotFoundError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(2)
    except Exception as e:
        print(f"扫描失败: {e}", file=sys.stderr)
        sys.exit(2)

    # 生成报告
    fmt = args.format
    if fmt in ("markdown", "md"):
        report = generate_markdown(result)
    else:
        report = generate_json(result)

    # 输出
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"报告已写入: {args.output}")
    else:
        print(report)

    # Exit code
    if result.verdict == "PASS":
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
