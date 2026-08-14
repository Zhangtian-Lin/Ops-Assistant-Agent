"""Skill 解析器 — 读取并解析 SKILL.md 及所有脚本文件"""

from pathlib import Path

# 需要读取内容的脚本文件扩展名
SCANNABLE_EXTENSIONS = {".py", ".sh", ".js", ".rb", ".pl", ".ps1", ".bash", ".zsh"}


def parse_skill(skill_dir: str) -> dict:
    """解析一个 Skill 目录，返回结构化数据。

    读取 SKILL.md 全文以及所有 .py/.sh/.js 等脚本文件内容，
    解决"只扫 SKILL.md"的漏报问题。

    Args:
        skill_dir: Skill 目录路径

    Returns:
        {
            "path": str,
            "skill_md": str,
            "files": [str],
            "file_contents": {filename: content},
        }
    """
    p = Path(skill_dir)
    if not p.is_dir():
        raise FileNotFoundError(f"目录不存在: {skill_dir}")

    # 读取 SKILL.md（支持多编码回退）
    skill_md_path = p / "SKILL.md"
    skill_md = ""
    if skill_md_path.exists():
        for encoding in ("utf-8", "gbk", "gb2312", "latin-1"):
            try:
                skill_md = skill_md_path.read_text(encoding=encoding)
                break
            except (UnicodeDecodeError, LookupError):
                continue

    # 收集所有文件 + 读取脚本内容
    files: list[str] = []
    file_contents: dict[str, str] = {}

    for f in p.rglob("*"):
        if not f.is_file():
            continue
        rel_path = str(f.relative_to(p))
        files.append(rel_path)

        # 对脚本文件读取内容
        if f.suffix.lower() in SCANNABLE_EXTENSIONS:
            try:
                file_contents[rel_path] = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, PermissionError):
                # 二进制文件或无权限跳过
                file_contents[rel_path] = f"[无法读取: {f.suffix}]"

    return {
        "path": str(p.resolve()),
        "skill_md": skill_md,
        "files": files,
        "file_contents": file_contents,
    }
