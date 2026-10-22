"""简单有序规则判断，供后续填写流程复用；不是通用规则引擎。"""


def first_jump_target(question: dict, answer):
    """调用方先校验答案；无答案/无命中返回None，由填写流程顺序前进。"""
    if answer is None or answer == "" or answer == []:
        return None
    for rule in question.get("jump_rules", []):
        operator = rule["condition"]["operator"]
        value = rule["condition"]["value"]
        match = False
        if operator == "equals":
            match = isinstance(answer, str) and answer == value
        elif operator == "contains":
            match = isinstance(answer, list) and value in answer
        elif operator == "contains_all":
            match = isinstance(answer, list) and all(item in answer for item in value)
        elif type(answer) in {int, float}:
            if operator == "gt":
                match = answer > value
            elif operator == "gte":
                match = answer >= value
            elif operator == "lt":
                match = answer < value
            elif operator == "lte":
                match = answer <= value
            elif operator == "eq":
                match = answer == value
        if match:
            return dict(rule["target"])
    return None
