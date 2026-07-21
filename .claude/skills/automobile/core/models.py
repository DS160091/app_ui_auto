"""Pydantic 结构化输出模型 — 自动判定 pass/fail"""

from pydantic import BaseModel
from typing import Optional


class StepResult(BaseModel):
    """单个步骤的执行结果"""
    step_index: int
    description: str
    passed: bool
    screenshot_path: Optional[str] = None
    error: Optional[str] = None


class TestResult(BaseModel):
    """单条用例的测试结果"""
    case_name: str
    passed: bool
    order_id: str = ""
    failure_reason: Optional[str] = None
    steps_taken: int = 0
    screenshots: list[str] = []
    duration_seconds: float = 0.0
    steps: list[StepResult] = []


class SuiteReport(BaseModel):
    """回归测试套件汇总报告"""
    timestamp: str
    total: int
    passed: int
    failed: int
    pass_rate: float
    results: list[TestResult]
