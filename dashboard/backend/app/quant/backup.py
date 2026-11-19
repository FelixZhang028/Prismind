"""每天自动备份一次用户数据：账户数据库、配置文件、回测证据与 AI 研究经验。

- 数据库用 SQLite 的在线备份接口复制，备份时网站照常使用，得到的是一份完整、一致的文件；
- 一起复制：登录令牌的签名密钥（丢了所有人都要重新登录）、数据源和知识库的设置、
  回测审计证据目录（``runs/``，相对上一份备份按文件硬链接增量复制）和 AI 研究经验（``agent_lab/``）；
- 放在 ``FELLOWQUANT_BACKUP_DIR``（默认 ``data/backups``，最好设成另一块硬盘或同步盘），
  每天一个文件夹，保留最近 ``FELLOWQUANT_BACKUP_KEEP`` 份（默认 14）；
- 管理员也可以在管理后台手动备份（升级前先备份一次），手动备份另外保留最近 ``MANUAL_KEEP`` 份；
- 停服务后可通过 ``python -m app.quant.backup restore <备份文件夹>`` 恢复；
- 行情数据不备份：体积大，而且可以从数据源重新下载。
- ``FELLOWQUANT_BACKUP=off`` 关闭。
"""

from __future__ import annotations

import logging
import os
import shutil
import sqlite3
import sys
import threading
from datetime import date, datetime
from pathlib import Path

from ..database import DB_PATH
from .runtime import BACKEND_ROOT, RUNTIME_ROOT

logger = logging.getLogger("uvicorn.error")
CHECK_SECONDS = 3600
EXTRA_FILES = ("app-secret.key", "data_source_settings.json", "weknora_settings.json")
MANUAL_KEEP = 5
MANUAL_MARK = "-manual-"


def enabled() -> bool:
    return os.getenv("FELLOWQUANT_BACKUP", "on").strip().lower() not in ("0", "off", "false", "no")


def backup_root() -> Path:
    configured = os.getenv("FELLOWQUANT_BACKUP_DIR", "").strip()
    return Path(configured) if configured else BACKEND_ROOT / "data" / "backups"


def keep() -> int:
    try:
        return max(1, int(os.getenv("FELLOWQUANT_BACKUP_KEEP", "") or 14))
    except ValueError:
        return 14


def _latest_backup(root: Path) -> Path | None:
    if not root.is_dir():
        return None
    folders = sorted(
        (p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".") and (p / "app.db").exists()),
        key=lambda p: p.name,
        reverse=True,
    )
    return folders[0] if folders else None


def _copy_or_hardlink(source: Path, target: Path, previous: Path | None) -> None:
    if previous is not None and previous.is_file():
        try:
            src_stat = source.stat()
            prev_stat = previous.stat()
            if src_stat.st_size == prev_stat.st_size and abs(src_stat.st_mtime_ns - prev_stat.st_mtime_ns) <= 1_000_000:
                os.link(previous, target)
                return
        except OSError:
            pass
    shutil.copy2(source, target)


def _copy_runs_incremental(source_runs: Path, target_runs: Path, previous_runs: Path | None) -> None:
    if not source_runs.is_dir():
        return
    target_runs.mkdir(parents=True, exist_ok=True)
    for item in source_runs.rglob("*"):
        rel = item.relative_to(source_runs)
        dest = target_runs / rel
        if item.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            prev_file = (previous_runs / rel) if previous_runs is not None else None
            _copy_or_hardlink(item, dest, prev_file)


def backup(today: date | None = None, *, root: Path | None = None, database: Path | None = None,
           runtime: Path | None = None, agent_root: Path | None = None, manual: bool = False) -> Path | None:
    """Back up today's data unless already done; returns the folder written (None if it existed).

    ``manual``: a backup the administrator asked for, named with the time, always written."""

    root = root or backup_root()
    name = (today or date.today()).isoformat()
    if manual:
        name += f"{MANUAL_MARK}{datetime.now():%H%M%S}"
    folder = root / name
    if (folder / "app.db").exists():
        return None
    previous = _latest_backup(root)
    temporary = root / f".{folder.name}.partial"
    shutil.rmtree(temporary, ignore_errors=True)
    temporary.mkdir(parents=True)
    source = sqlite3.connect(str(database or DB_PATH))
    target = sqlite3.connect(str(temporary / "app.db"))
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    effective_runtime = runtime or RUNTIME_ROOT
    for extra in EXTRA_FILES:
        path = effective_runtime / extra
        if path.exists():
            shutil.copy2(path, temporary / extra)
    prev_runs = (previous / "runs") if previous is not None and (previous / "runs").is_dir() else None
    _copy_runs_incremental(effective_runtime / "runs", temporary / "runs", prev_runs)
    effective_agent = agent_root or (effective_runtime / "agent_lab")
    if effective_agent.is_dir():
        shutil.copytree(effective_agent, temporary / "agent_lab")
    temporary.rename(folder)  # 复制完整以后才出现正式的文件夹
    folders = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    # 每天的和手动的分开保留，手动备份多了也不会挤掉每天的。
    for kept, group in ((keep(), [p for p in folders if MANUAL_MARK not in p.name]),
                        (MANUAL_KEEP, [p for p in folders if MANUAL_MARK in p.name])):
        for old in group[:-kept]:
            shutil.rmtree(old, ignore_errors=True)
    return folder


def _stash_existing(target: Path, stamp: str) -> Path | None:
    if not target.exists():
        return None
    stashed = target.with_name(f"{target.name}.before-restore.{stamp}")
    target.rename(stashed)
    return stashed


def restore(
    folder: Path | str,
    *,
    database: Path | None = None,
    runtime: Path | None = None,
    agent_root: Path | None = None,
) -> dict[str, list[str]]:
    """停服务后从指定备份文件夹恢复数据库、配置、回测证据和 AI 研究经验。"""

    source_dir = Path(folder)
    if not source_dir.is_dir() or not (source_dir / "app.db").is_file():
        raise ValueError(f"备份目录无效或缺少 app.db：{source_dir}")
    stamp = datetime.now().strftime("%Y%m%d%H%M%S")
    restored: list[str] = []
    stashed: list[str] = []

    db_target = Path(database or DB_PATH)
    db_target.parent.mkdir(parents=True, exist_ok=True)
    old_db = _stash_existing(db_target, stamp)
    if old_db is not None:
        stashed.append(str(old_db))
    src_conn = sqlite3.connect(str(source_dir / "app.db"))
    dst_conn = sqlite3.connect(str(db_target))
    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()
    restored.append("app.db")

    effective_runtime = Path(runtime or RUNTIME_ROOT)
    effective_runtime.mkdir(parents=True, exist_ok=True)
    for extra in EXTRA_FILES:
        src_file = source_dir / extra
        if src_file.is_file():
            dst_file = effective_runtime / extra
            old_file = _stash_existing(dst_file, stamp)
            if old_file is not None:
                stashed.append(str(old_file))
            shutil.copy2(src_file, dst_file)
            restored.append(extra)

    src_runs = source_dir / "runs"
    if src_runs.is_dir():
        dst_runs = effective_runtime / "runs"
        old_runs = _stash_existing(dst_runs, stamp)
        if old_runs is not None:
            stashed.append(str(old_runs))
        shutil.copytree(src_runs, dst_runs)
        restored.append("runs")

    src_agent = source_dir / "agent_lab"
    if src_agent.is_dir():
        dst_agent = Path(agent_root or (effective_runtime / "agent_lab"))
        dst_agent.parent.mkdir(parents=True, exist_ok=True)
        old_agent = _stash_existing(dst_agent, stamp)
        if old_agent is not None:
            stashed.append(str(old_agent))
        shutil.copytree(src_agent, dst_agent)
        restored.append("agent_lab")

    return {"restored": restored, "stashed": stashed}


def folder_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def listing(root: Path | None = None) -> list[dict]:
    """已有的备份，新的在前：名字、是不是手动备份、大小。"""

    root = root or backup_root()
    if not root.is_dir():
        return []
    folders = sorted((p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")), key=lambda p: p.name, reverse=True)
    return [{"name": p.name, "manual": MANUAL_MARK in p.name, "size": folder_size(p)} for p in folders]


class BackupScheduler:
    """Checks once an hour in a daemon thread and backs up once per day."""

    def __init__(self) -> None:
        self._stop = threading.Event()

    def tick(self) -> None:
        if not enabled():
            return
        try:
            folder = backup()
            if folder is not None:
                logger.info("已备份用户数据：%s", folder)
        except Exception:  # noqa: BLE001 - 备份失败不能影响网站
            logger.exception("每日备份失败")

    def _loop(self) -> None:
        self.tick()
        while not self._stop.wait(CHECK_SECONDS):
            self.tick()

    def start(self) -> None:
        threading.Thread(target=self._loop, name="daily-backup", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) == 2 and args[0] == "restore":
        summary = restore(Path(args[1]))
        print(f"已恢复：{', '.join(summary['restored'])}")
        if summary["stashed"]:
            print(f"原有文件已保留备份：{', '.join(summary['stashed'])}")
        return 0
    print("用法：python -m app.quant.backup restore <备份文件夹>")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
