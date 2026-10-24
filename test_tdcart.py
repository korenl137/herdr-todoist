import os, tempfile, tdcart
from pathlib import Path

tdcart.CART = Path(tempfile.mkdtemp()) / "sub" / "cart.json"
t = {"id": "a1", "title": "제목", "url": "u"}
assert tdcart.load_cart() == []
assert tdcart.toggle(t) is True and tdcart.load_cart() == [t]
assert tdcart.toggle(t) is False and tdcart.load_cart() == []
assert tdcart.format_lines([t]) == "- 제목 (a1) u"
assert "\n" not in tdcart.format_oneline([t, t])
task = {"id": "z9", "title": "현미경 비교", "project": "Research", "labels": ["@act/code"], "desc": "기포 측정"}
assert tdcart.matches(task, "현미경 research") and tdcart.matches(task, "act/code 기포") and tdcart.matches(task, "z9")
assert not tdcart.matches(task, "현미경 없는말") and tdcart.matches(task, "")
tasks = [{"id": "c1", "parentId": "p"}, {"id": "p", "parentId": None}, {"id": "o", "parentId": "gone"}, {"id": "c2", "parentId": "c1"}]
assert [(x["id"], d, k) for x, d, k in tdcart.arrange(tasks)] == [("p", 0, 1), ("c1", 1, 1), ("c2", 2, 0), ("o", 0, 0)]
assert [x["id"] for x, _, _ in tdcart.arrange(tasks, {"c1"})] == ["p", "c1", "o"]
assert [d for _, d, _ in tdcart.arrange(tasks, nested=False)] == [0, 0, 0, 0]
assert tdcart.plain("> **유형** 정비\n\n## 목적\n먼지") == "유형 정비 목적 먼지"
assert [tdcart.priority_tag(n) for n in (4, 3, 2, 1)] == ["P1", "P2", "", ""]
print("ok")

import picker
assert picker.window(5, 50, 10) == 0 and picker.window(40, 50, 10) == 31 and picker.window(49, 50, 10) == 40
assert picker.fit("🗓️a", 3) == "🗓a " and picker.fit("한글ab", 6) == "한글ab" and picker.fit("한글abc", 6) == "한글a…"
assert picker.wrap("가나다라마바사", 6, 2) == ["가나다", "라마… "]
print("ok picker")
