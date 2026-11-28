from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3

from app.config import get_settings
from app.maintenance.database import MaintenanceConflict, compact_database, inspect_database


def main() -> int:
    """Run read-only inspection or verified offline compaction."""
    parser = argparse.ArgumentParser(description="NAS File Center 数据库维护")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="查看数据库文件占用和预计可回收空间")
    compact = commands.add_parser("compact", help="离线备份并压缩数据库，校验通过后删除临时备份")
    compact.add_argument("--apply", action="store_true", help="确认已停止 API 和 Worker 并执行压缩")
    compact.add_argument("--backup-dir", type=Path, help="临时备份目录，默认使用配置卷下的 backups")
    args = parser.parse_args()

    settings = get_settings()
    try:
        if args.command == "compact" and args.apply:
            result = compact_database(settings.database_path, args.backup_dir or settings.backups_dir)
        else:
            result = inspect_database(settings.database_path)
    except (MaintenanceConflict, OSError, sqlite3.Error) as error:
        parser.exit(1, f"数据库维护失败：{error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
