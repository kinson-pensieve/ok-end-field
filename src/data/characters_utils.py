from src.data.characters import characters
from src.data.FeatureList import FeatureList


def get_contact_list_with_feature_list() -> dict[str, str]:
    feature_set = {f.value for f in FeatureList}

    en_to_zh = {info["en"] + "_contact": info["zh"] for info in characters.values()}

    common = feature_set & en_to_zh.keys()

    return {en_to_zh[c]: c for c in common}
