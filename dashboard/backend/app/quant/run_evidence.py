"""Fail-closed trust labels shared by every view of a persisted backtest."""
import json
import re
from pathlib import Path
from typing import Any

from quant_platform.backtest.validity import load_persisted_validity, legacy_unverified_report
from .runtime import BACKEND_ROOT, RUNTIME_ROOT

_SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def extract_run_id(raw: str | Path) -> str | None:
    """从相对或绝对路径中提取位于最后一个 ``runs/`` 下的单级 run_id。"""

    parts = [segment for segment in re.split(r"[\\/]+", str(raw).strip()) if segment]
    if len(parts) < 2 or parts[-2] != "runs":
        return None
    run_id = parts[-1]
    if run_id in {".", ".."} or not _SAFE_RUN_ID.fullmatch(run_id):
        return None
    return run_id


def relative_run_dir(path: str | Path) -> str:
    """将当前 RUNTIME_ROOT/runs 下的目录标准化为相对路径 ``runs/<id>``。"""

    raw = Path(str(path))
    runs_root = (RUNTIME_ROOT / "runs").resolve()
    try:
        resolved = raw.resolve()
        if resolved != runs_root and resolved.is_relative_to(runs_root):
            return f"runs/{resolved.relative_to(runs_root).as_posix()}"
    except OSError:
        pass
    return str(path)


def run_directory(result: dict[str, Any]) -> Path | None:
    raw = result.get("output_dir")
    if not raw:
        return None
    raw_str = str(raw).strip()
    if not raw_str:
        return None
    runs_root = (RUNTIME_ROOT / "runs").resolve()
    path = Path(raw_str)
    is_abs = path.is_absolute() or raw_str.startswith(("/", "\\")) or bool(re.match(r"^[A-Za-z]:[\\/]", raw_str))
    if not is_abs:
        for base in (RUNTIME_ROOT, BACKEND_ROOT):
            candidate = (base / path).resolve()
            if candidate != runs_root and candidate.is_relative_to(runs_root):
                return candidate
        return None
    if path.is_absolute():
        resolved = path.resolve()
        if resolved != runs_root and resolved.is_relative_to(runs_root):
            return resolved
    # 兼容旧版本部署目录或换机/跨系统后残留的绝对路径：按最后一段 runs/<run_id> 重定位到当前 RUNTIME_ROOT。
    run_id = extract_run_id(raw_str)
    if run_id is not None:
        relocated = (runs_root / run_id).resolve()
        if relocated != runs_root and relocated.is_relative_to(runs_root) and relocated.is_dir():
            return relocated
    return None


def run_evidence(result: dict[str, Any]) -> dict[str, Any]:
    directory = run_directory(result)
    validity = load_persisted_validity(directory) if directory else legacy_unverified_report()
    verified = bool(validity) and not validity.get("legacy_unverified", False)
    raw_issues = validity.get("issues")
    if not isinstance(raw_issues, list) or any(not isinstance(i, dict) for i in raw_issues):
        verified = False
        issues = [{"code": "CORRUPT_EVIDENCE", "severity": "ERROR", "message": "审计证据格式损坏，无法验证。"}]
    else:
        issues = list(raw_issues)
    status = str(validity.get("status") or "UNVERIFIED") if verified else "UNVERIFIED"
    if result.get("validity_status") == "INVALID":
        status = "INVALID"
    elif result.get("validity_status") == "WARNING" and status == "VALID":
        status = "WARNING"
    if verified and any(i.get("severity") == "ERROR" for i in issues):
        status = "INVALID"
    elif verified and any(i.get("severity") == "WARNING" for i in issues) and status == "VALID":
        status = "WARNING"
    reliable = (
        verified and status in {"VALID", "WARNING"}
        and validity.get("metrics_reliable") is True
        and result.get("metrics_reliable") is not False
        and not any(i.get("severity") == "ERROR" for i in issues)
    )
    return {
        "validity_status": status,
        "metrics_reliable": reliable,
        "legacy_unverified": not verified,
        "validity_issues": issues,
        "audit_version": validity.get("audit_version", 0),
    }


def with_run_evidence(result: dict[str, Any]) -> dict[str, Any]:
    directory = run_directory(result)
    kind = result.get("run_kind")
    if kind is None and directory:
        try:
            lifecycle = json.loads((directory / "run.json").read_text(encoding="utf-8"))
            kind = lifecycle.get("run_kind") if isinstance(lifecycle, dict) else None
        except (OSError, ValueError):
            pass
    return {**result, "run_kind": kind or "unknown", **run_evidence(result)}
