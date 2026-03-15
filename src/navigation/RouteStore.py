import json
import os
import uuid


class RouteStore:
    """routes.json 的统一数据管理，内存持有 + 按需落盘

    用法:
        store = RouteStore()
        route = store.find("军械库", dest_type="采集物")
        store.save(route)
        store.flush()
    """

    _JSON_PATH = os.path.join("assets", "routes.json")

    def __init__(self):
        self._routes: list[dict] = []
        self._load()

    # ── 查询 ──

    def all(self) -> list[dict]:
        """返回全部路线"""
        return self._routes

    def find(self, name: str, dest_type: str = None) -> dict | None:
        """按 name + type 精确查找

        Args:
            name: 目的地名称
            dest_type: 目的地类型，用于同名不同类型的消歧
        """
        for route in self._routes:
            if route.get("name") == name:
                if dest_type is None or route.get("type") == dest_type:
                    return route
        return None

    def find_by_type(self, dest_type: str) -> list[dict]:
        """按 type 过滤所有路线"""
        return [r for r in self._routes if r.get("type") == dest_type]

    def find_by_area_and_type(self, area: str, dest_type: str) -> dict | None:
        """按 area + type 查找第一条匹配路线

        Args:
            area: 所属地区
            dest_type: 目的地类型
        """
        for route in self._routes:
            if route.get("area") == area and route.get("type") == dest_type:
                return route
        return None

    def find_by_id(self, route_id: str) -> dict | None:
        """按 id 查找"""
        for route in self._routes:
            if route.get("id") == route_id:
                return route
        return None

    # ── 写入（仅改内存）──

    def save(self, route: dict):
        """保存路线，按 id 或 name+type 匹配覆盖，否则追加"""
        if not route.get("id"):
            route = {"id": self._generate_id(), **route}
        elif list(route.keys())[0] != "id":
            # 确保 id 在第一位
            route = {"id": route.pop("id"), **route}

        # 先按 id 匹配
        for i, existing in enumerate(self._routes):
            if existing.get("id") == route["id"]:
                self._routes[i] = route
                return

        # 再按 name+type 匹配
        name = route.get("name")
        route_type = route.get("type")
        if name and route_type:
            for i, existing in enumerate(self._routes):
                if existing.get("name") == name and existing.get("type") == route_type:
                    route["id"] = existing.get("id", route["id"])
                    self._routes[i] = route
                    return

        self._routes.append(route)

    def delete(self, route_id: str) -> bool:
        """按 id 删除路线

        Returns:
            bool: 是否找到并删除
        """
        for i, route in enumerate(self._routes):
            if route.get("id") == route_id:
                self._routes.pop(i)
                return True
        return False

    # ── 落盘 ──

    def flush(self):
        """将内存数据写入拆分文件或 routes.json"""
        routes_dir = os.path.join("assets", "routes")

        # Mapping from Chinese type to English filename
        type_to_filename = {
            '采集物': 'collectibles',
            '矿物': 'minerals',
            '资源回收站': 'recycling_stations',
            '仓储节点': 'depot_nodes',
            '送货': 'deliveries',
        }

        # If split directory exists, write to split files
        if os.path.isdir(routes_dir):
            # Group by type
            routes_by_type = {}
            for route in self._routes:
                route_type = route.get('type', 'unknown')
                if route_type not in routes_by_type:
                    routes_by_type[route_type] = []
                routes_by_type[route_type].append(route)

            # Write each type to its file
            for route_type, type_routes in routes_by_type.items():
                if not route_type or route_type == 'unknown':
                    continue
                filename = type_to_filename.get(route_type, route_type) + '.json'
                filepath = os.path.join(routes_dir, filename)
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(type_routes, f, ensure_ascii=False, indent=2)
        else:
            # Fallback: write to routes.json
            with open(self._JSON_PATH, 'w', encoding='utf-8') as f:
                json.dump(self._routes, f, ensure_ascii=False, indent=2)

    # ── 重载 ──

    def reload(self):
        """从文件重新加载，丢弃未落盘的修改"""
        self._load()

    # ── 内部方法 ──

    def _load(self):
        """从文件加载路线，支持 routes.json 或 routes/ 目录拆分文件
        为无 id 的老数据自动补上 id
        """
        self._routes = []

        # Try loading from split routes/ directory first
        routes_dir = os.path.join("assets", "routes")
        if os.path.isdir(routes_dir):
            for filename in sorted(os.listdir(routes_dir)):
                if filename.startswith('_') or not filename.endswith('.json'):
                    continue
                filepath = os.path.join(routes_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        type_routes = json.load(f)
                        if isinstance(type_routes, list):
                            self._routes.extend(type_routes)
                except Exception as e:
                    print(f"Warning: Failed to load {filepath}: {e}")

        # Fallback to routes.json if split directory is empty or doesn't exist
        if not self._routes and os.path.exists(self._JSON_PATH):
            with open(self._JSON_PATH, 'r', encoding='utf-8') as f:
                self._routes = json.load(f)

        dirty = False
        for route in self._routes:
            if not route.get("id"):
                route["id"] = self._generate_id()
                dirty = True

        if dirty:
            self.flush()

    @staticmethod
    def _generate_id() -> str:
        """生成 UUID4 前 8 位作为唯一 id"""
        return uuid.uuid4().hex[:8]
