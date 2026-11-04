"""Bounded record entry phrases; filters and patient confirmation stay typed."""

import re


def record_entry(text: str) -> str | None:
    patterns = (
        ("observation.list", r"(?:please )?show health notes|(?:请)?查看健康观察"),
        ("observation.add", r"(?:please )?add a health note|(?:请)?添加健康观察"),
        ("observation.edit", r"(?:please )?edit a health note|(?:请)?编辑健康观察"),
        ("observation.delete", r"(?:please )?delete a health note|(?:请)?删除健康观察"),
        ("inventory.view", r"(?:please )?show medication inventory|(?:请)?查看药物库存"),
        ("inventory.count", r"(?:please )?record medication stock|(?:请)?记录药物库存"),
        ("barrier.list", r"(?:please )?show medication difficulties|(?:请)?查看用药困难"),
        ("barrier.add", r"(?:please )?record a medication difficulty|(?:请)?记录用药困难"),
        ("followup.list", r"(?:please )?show medication followups|(?:请)?查看用药跟进"),
        ("followup.add", r"(?:please )?add a medication followup|(?:请)?添加用药跟进"),
        ("followup.edit", r"(?:please )?edit a medication followup|(?:请)?编辑用药跟进"),
        ("followup.contacted", r"(?:please )?mark a followup contacted|(?:请)?标记跟进已联系"),
        ("followup.complete", r"(?:please )?complete a medication followup|(?:请)?完成用药跟进"),
        ("followup.defer", r"(?:please )?defer a medication followup|(?:请)?延期用药跟进"),
        ("followup.cancel", r"(?:please )?cancel a medication followup|(?:请)?取消用药跟进"),

        ("medication.knowledge", r"(?:please )?look up a medicine|(?:请)?查询药物知识"),
        ("dose.late.review", r"(?:please )?record a late dose|(?:请)?补记服药"),
        ("dose.correction.review", r"(?:please )?correct a dose report|(?:请)?更正服药记录"),
        ("dose.report", r"(?:please )?record a dose|(?:请)?记录服药自述"),
        ("dose.prn.report", r"(?:please )?record an as-needed dose|(?:请)?记录按需服药自述"),
        ("medication.today", r"(?:show|view)(?: my)? today'?s (?:medicines|medications)|(?:请)?查看(?:今日|今天)用药"),
        ("medication.due", r"(?:show|view) due doses|(?:请)?查看待自述剂次"),
        ("medication.status", r"(?:check|view|show) medication status|(?:请)?查看服药状态"),
        ("medication.history", r"(?:show|view) medication history|(?:请)?查看用药历史"),
        ("medication.source.view", r"(?:show|view) medication sources|(?:请)?查看药物原始来源"),
        ("medication.instructions", r"(?:show|view)(?: my)? medication instructions|(?:请)?查看我的服药说明"),
        ("record.catalogue", r"(?:show|view) record catalogue|(?:请)?查看记录目录"),
        ("record.history", r"(?:show|view) medication records|(?:请)?查看服药记录"),
        ("record.summary", r"(?:show|view) weekly medication summary|(?:请)?查看本周用药统计"),
        ("record.visit.prepare", r"(?:please )?prepare for my visit|(?:请)?准备复诊"),
    )
    return next((capability for capability, pattern in patterns if re.fullmatch(pattern, text)), None)
