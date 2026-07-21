"""路由配置类 —— 把用户诉求匹配到具体叶子流程。

唯一事实来源是 `core/config/routes.yaml`。最外层路由 Skill 拿到用户诉求后:
  1. 调本模块得到候选(match / list)
  2. 由编排层(Claude)做语义定夺,确认唯一目标
  3. 调 resolve() 拿到 (skill_name, LEAF_DIR 绝对路径) 直接执行

CLI 用法(供路由层 Skill 调用):
  python3 core/router.py list                 # 列出所有已注册流程(JSON)
  python3 core/router.py match "跑一下系统设置飞行模式"  # 关键词打分预筛(JSON)
  python3 core/router.py resolve <skill_name>  # 取 skill_name + 绝对 LEAF_DIR(JSON)
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

import yaml

CORE_DIR = Path(__file__).resolve().parent       # core/
SKILL_ROOT = CORE_DIR.parent                       # automobile/(Skill 根)
ROUTES_PATH = CORE_DIR / "config" / "routes.yaml"


@dataclass
class Route:
    """一条已注册的回归流程。"""

    skill_name: str
    business_line: str
    app: str
    category: str
    scene: str
    leaf_dir: str                  # 相对 Skill 根
    description: str = ""
    keywords: tuple[str, ...] = ()

    @property
    def leaf_path(self) -> Path:
        """叶子目录绝对路径(= 运行时应设置的 LEAF_DIR)。"""
        return (SKILL_ROOT / self.leaf_dir).resolve()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["leaf_path"] = str(self.leaf_path)
        d["leaf_exists"] = self.leaf_path.exists()
        return d


class Router:
    """加载 routes.yaml,提供匹配与解析。"""

    def __init__(self, routes_path: Path = ROUTES_PATH):
        self.routes_path = routes_path
        self.apps: dict = {}
        self.routes: list[Route] = self._load()

    def _load(self) -> list[Route]:
        if not self.routes_path.exists():
            raise FileNotFoundError(f"路由配置不存在: {self.routes_path}")
        data = yaml.safe_load(self.routes_path.read_text(encoding="utf-8")) or {}
        self.apps = data.get("apps", {}) or {}
        routes: list[Route] = []
        for raw in data.get("routes", []):
            routes.append(
                Route(
                    skill_name=raw["skill_name"],
                    business_line=raw.get("business_line", ""),
                    app=raw.get("app", ""),
                    category=raw.get("category", ""),
                    scene=raw.get("scene", ""),
                    leaf_dir=raw["leaf_dir"],
                    description=raw.get("description", ""),
                    keywords=tuple(raw.get("keywords", [])),
                )
            )
        return routes

    def list(self) -> list[Route]:
        """全部已注册流程。"""
        return list(self.routes)

    def get(self, skill_name: str) -> Route | None:
        """按 skill_name 精确取一条。"""
        for r in self.routes:
            if r.skill_name == skill_name:
                return r
        return None

    def resolve(self, skill_name: str) -> dict:
        """取最终执行所需的 skill_name + 绝对 LEAF_DIR。

        路由层确认唯一目标后调用本方法,返回值可直接用于设置 LEAF_DIR 与调用叶子 playbook。
        """
        route = self.get(skill_name)
        if route is None:
            raise KeyError(f"未注册的 skill_name: {skill_name}")
        if not route.leaf_path.exists():
            raise FileNotFoundError(f"叶子目录不存在: {route.leaf_path}")
        app_meta = self.apps.get(route.app, {}) or {}
        return {
            "skill_name": route.skill_name,
            "leaf_dir": str(route.leaf_path),
            "skill_md": str(route.leaf_path / "SKILL.md"),
            "description": route.description,
            "app": route.app,
            "app_package": app_meta.get("package", ""),
            "app_label": app_meta.get("app_label", ""),
        }

    def match(self, query: str) -> list[dict]:
        """关键词打分预筛,返回按得分降序的候选(含得分)。

        仅做粗筛兜底;真正的语义定夺由编排层(Claude)结合候选与诉求完成。
        无任何命中时返回全部流程(得分 0),交由路由层让用户选。
        """
        q = (query or "").lower()
        scored: list[tuple[int, Route]] = []
        for r in self.routes:
            fields = [r.business_line, r.app, r.category, r.scene, *r.keywords]
            score = sum(1 for kw in fields if kw and kw.lower() in q)
            scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored and scored[0][0] == 0:
            # 全员 0 分:不臆测,返回全部供用户选
            return [{**r.to_dict(), "score": 0} for _, r in scored]
        return [{**r.to_dict(), "score": s} for s, r in scored if s > 0]


def _main(argv: list[str]) -> int:
    router = Router()
    if len(argv) < 2:
        print(json.dumps({"error": "用法: router.py [list|match <query>|resolve <skill_name>]"}, ensure_ascii=False))
        return 2
    cmd = argv[1]
    if cmd == "list":
        print(json.dumps([r.to_dict() for r in router.list()], ensure_ascii=False, indent=2))
        return 0
    if cmd == "match":
        query = argv[2] if len(argv) > 2 else ""
        print(json.dumps(router.match(query), ensure_ascii=False, indent=2))
        return 0
    if cmd == "resolve":
        if len(argv) < 3:
            print(json.dumps({"error": "resolve 需要 skill_name 参数"}, ensure_ascii=False))
            return 2
        try:
            print(json.dumps(router.resolve(argv[2]), ensure_ascii=False, indent=2))
            return 0
        except (KeyError, FileNotFoundError) as e:
            msg = e.args[0] if e.args else str(e)
            print(json.dumps({"error": msg}, ensure_ascii=False))
            return 1
    print(json.dumps({"error": f"未知命令: {cmd}"}, ensure_ascii=False))
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv))
