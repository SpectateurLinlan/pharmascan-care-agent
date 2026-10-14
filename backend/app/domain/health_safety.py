"""Small conditional safety notice, NOT a validated triage or diagnosis model.

Emergency information: https://www.scdf.gov.sg/home/about-scdf/emergency-medical-services
"""


def needs_urgent_help_notice(text: str) -> bool:
    lowered = text.lower()
    return any(
        term in lowered
        for term in (
            "cannot breathe",
            "can't breathe",
            "difficulty breathing",
            "trouble breathing",
            "chest pain",
            "severe",
            "呼吸困难",
            "胸痛",
            "严重",
        )
    )


def urgent_help_notice(language: str) -> str:
    if language == "zh":
        return (
            "若您现在有严重症状，请及时寻求专业帮助。危及生命的紧急情况请联系当地急救服务"
            "（新加坡为995），不要等待本演示处理。不会自动保存感受或服药记录。"
        )
    return (
        "For a life-threatening emergency, call your local emergency service (995 in Singapore). "
        "If severe symptoms are happening now, seek prompt professional help; do not wait for this demo. "
        "No health note or dose report has been saved automatically."
    )
