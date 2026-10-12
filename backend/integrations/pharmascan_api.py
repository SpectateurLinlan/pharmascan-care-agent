# PharmaScan API: https://davidpansx-pharmascan-api.hf.space/docs#/default/feedback_v1_feedback_post

# P0
# POST /v1/embed
# POST /v1/match
# POST /v1/identify
# POST /v1/scan
# POST /v1/safety/medications
# POST /v1/safety/dose
# GET  /v1/pills/search
# GET  /v1/pills/{pill_id}

# P1
# GET /v1/safety/label
# POST /v1/feedback
# DELETE /v1/feedback/{consent_id}

# P2
# GET /v1/pills/{pill_id}/image/{n}

# /health 则用于后台 health check



# A. Personal verification
# /embed
# /match
# /scan
# 回答：“这是我自己的药吗？”
# 这是你们每日服药检查的核心。

# B. General pill identification
# /identify 支持1 张照片；正反两张照片；imprint;shape；colour；top-k。很适合家里找到一颗没有包装的药。系统可以返回：possible matches,而不是 confirmed identity。
# /pills/search
# /pills/{pill_id}
# 回答：“这颗不知道是什么的药，可能是什么？”

# C. Medication safety
# 你们甚至已经有：你们甚至已经有：/safety/medications
# 用于：
# - DDInter interaction
# - duplicate active ingredients
# - unknown medication alerts

# 以及：/safety/dose
# 用于：
# - double dose
# - extra pill
# - missed medication
# - unknown pill
# - ambiguous pill
# 这意味着我之前建议你们自己再建一个复杂 DDI checker，现在没有必要了。
# Agent 直接调用现成 tool。


# D. Continuous improvement
# 你们甚至已经有：
# POST /v1/feedback
# DELETE /v1/feedback/{consent_id}
# 支持：
# - opt-in；
# - consent ID；
# - pharmacist verified；
# - user confirmed；
# - monthly retraining；
# - consent withdrawal；
# - 删除对应图片。
# 这已经回答了我们之前讨论的：Personal Gallery 图片能不能拿去 retrain？

# 这个 API 的设计已经把它处理成：Personal Gallery use≠Model improvement consent
# 这是很好的 Responsible AI 设计。

# 但有一个地方我建议修改：目前 feedback API 允许 label_source = user_confirmed。对于真正进入全局模型训练的数据，我建议至少在你们自己的 Agent 层区分：
# pharmacist_verified
# user_confirmed
# 并且默认不要让普通 user-confirmed 样本直接拥有与 pharmacist-verified 相同的训练可信度。