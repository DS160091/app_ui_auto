"""回归报告 res-json 的可执行校验（格式真相源）。

字段与 core/config/report_template.json / report_template.md 完全一致：
- 固定字段必填、类型钉死；
- steps[].detail 为自由 JSON（dict|null），不约束内部结构，仅供后台展示。

对外只暴露一个入口 validate_report(report: dict) -> list[str]：
只**收集告警**（缺字段 / 类型错 / total_steps 对不上 / passed_steps 对不上 /
截图 step_no 对不上任何 step），**不抛异常、不阻断上传**（按既定约定：只警告）。
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ValidationError


class ReportStep(BaseModel):
    """steps[] 元素：步骤固定骨架 + 自由 detail。"""
    step_no: int
    step_type: str            # API / UI / ADB
    description: str
    result: str               # PASS / FAIL / SKIP / NA
    duration_sec: Optional[int] = None
    detail: Optional[dict] = None   # 自由 JSON，只做展示，不约束结构


class ReportScreenshot(BaseModel):
    """screenshots[] 元素：截图固定骨架。"""
    step_no: Optional[int] = None
    step_name: str
    cdn_url: str
    seq: int


class Report(BaseModel):
    """报告顶层固定字段。"""
    order_id: str
    run_id: str
    skill_name: str
    business_line: str
    app: str
    category: str
    scene: str
    case_name: str
    priority: str
    result: str               # PASS / FAIL
    total_steps: int
    passed_steps: int
    start_time: str           # ISO8601
    end_time: str             # ISO8601
    duration_sec: int
    steps: list[ReportStep]
    screenshots: list[ReportScreenshot]


def _flatten_pydantic_errors(exc: ValidationError) -> list[str]:
    """把 pydantic 的结构校验错误摊平成人可读的告警行。"""
    out: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err.get("loc", ())) or "<root>"
        out.append(f"字段 {loc}：{err.get('msg', '校验失败')}")
    return out


def validate_report(report: dict[str, Any]) -> list[str]:
    """校验一份 res-json，返回告警列表（空列表 = 无告警）。

    只收集问题、不抛异常、不阻断上传（约定：只警告）。涵盖两类检查：
    1. 结构校验：固定字段是否齐全、类型是否正确（交给 pydantic）。
    2. 跨字段一致性：total_steps / passed_steps 是否与 steps 吻合、
       截图关联的 step_no 是否真实存在于 steps。
    """
    warnings: list[str] = []

    # 1) 结构校验
    model: Optional[Report] = None
    try:
        model = Report.model_validate(report)
    except ValidationError as e:
        warnings.extend(_flatten_pydantic_errors(e))

    # 结构校验没过时，跨字段检查基于原始 dict 尽力做，避免误报二次刷屏。
    # 优先用已校验的 model.steps，拿不到再回退到原始 dict 的 steps。
    steps = model.steps if model is not None else report.get("steps")
    if not isinstance(steps, list):
        return warnings  # steps 本身就不是数组，前面已告警，无法再做一致性检查

    # 2) 跨字段一致性
    total = report.get("total_steps")
    if isinstance(total, int) and total != len(steps):
        warnings.append(f"total_steps={total} 与实际步数 {len(steps)} 不一致")

    def _step_result(s: Any) -> str:
        if isinstance(s, ReportStep):
            return s.result
        return s.get("result", "") if isinstance(s, dict) else ""

    def _step_no(s: Any) -> Any:
        if isinstance(s, ReportStep):
            return s.step_no
        return s.get("step_no") if isinstance(s, dict) else None

    passed = report.get("passed_steps")
    actual_passed = sum(1 for s in steps if _step_result(s) == "PASS")
    if isinstance(passed, int) and passed != actual_passed:
        warnings.append(f"passed_steps={passed} 与实际 PASS 步数 {actual_passed} 不一致")

    # 截图关联的 step_no 必须能对上某个 step
    valid_step_nos = {_step_no(s) for s in steps}
    shots = report.get("screenshots")
    if isinstance(shots, list):
        for i, shot in enumerate(shots):
            sn = shot.get("step_no") if isinstance(shot, dict) else getattr(shot, "step_no", None)
            if sn is not None and sn not in valid_step_nos:
                name = (shot.get("step_name") if isinstance(shot, dict) else getattr(shot, "step_name", "")) or f"#{i}"
                warnings.append(f"截图「{name}」关联的 step_no={sn} 在 steps 中不存在")

    return warnings

