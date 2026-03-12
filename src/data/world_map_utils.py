from src.data.world_map import outpost_dict, goods_dict, stages_dict


def get_area_by_outpost_name(outpost_name: str) -> str:
    """
    根据据点名称获取该据点所在区域
    参数:
        outpost_name: 据点名称
    返回值:
        该据点所在区域，如果据点不存在返回空字符串
    """
    for area, outposts in outpost_dict.items():
        if outpost_name in outposts:
            return area
    return ""


def get_goods_by_outpost_name(outpost_name: str) -> list[str]:
    """
    根据据点名称获取该据点可交易的货物列表
    参数:
        outpost_name: 据点名称
    返回值:
        该据点的货物列表，如果据点不存在返回空列表
    """
    for area, outposts in outpost_dict.items():
        if outpost_name in outposts:
            return goods_dict.get(area, [])
    return []


def get_stage_category(stage_name):
    for category, stages in stages_dict.items():
        if stage_name in stages:
            return category
    return None
