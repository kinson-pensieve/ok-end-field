import json
import re
import keyword
from pathlib import Path


def normalize_field_name(name: str) -> str:
    name = name.lower()
    name = re.sub(r"[^0-9a-z]+", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")

    if not name:
        name = "empty"

    if keyword.iskeyword(name):
        name += "_"

    if name[0].isdigit():
        name = "_" + name

    return name


def module_to_path(module_path: str) -> Path:
    """
    把 src.data.feature 转成 src/data/feature.py
    """
    return Path(*module_path.split(".")).with_suffix(".py")


def generate_label_enum(coco_json: str, gen_label_enum: str):
    coco_json_path = Path(coco_json)
    output_path = module_to_path(gen_label_enum)

    if not coco_json_path.exists():
        raise FileNotFoundError(f"找不到文件: {coco_json_path.resolve()}")

    with coco_json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    categories = data.get("categories", [])

    lines = [
        "from enum import Enum\n\n",
        "class FeatureList(str, Enum):\n",
    ]

    used_names = set()

    for cat in categories:
        raw_name = cat["name"]
        enum_name = normalize_field_name(raw_name)

        base_name = enum_name
        index = 1
        while enum_name in used_names:
            enum_name = f"{base_name}_{index}"
            index += 1

        used_names.add(enum_name)
        lines.append(f'    {enum_name} = "{raw_name}"\n')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("".join(lines), encoding="utf-8")

    print(f"✅ 生成完成: {output_path.resolve()}")
if __name__ == "__main__":
    generate_label_enum("assets/coco_detection.json", "src.data.features")
