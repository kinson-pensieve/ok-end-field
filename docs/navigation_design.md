# 终末地自动寻路方案

## 概述

完整的自动导航链路：

```
打开地图 → 传送到传送点 → 步行/滑索 → 到达目的地 → 执行交互
```

本方案分为七个模块，导航相关模块统一放在 `src/navigation/` 目录下，任务入口保留在 `src/tasks/`。

### 目录结构

```
src/
├── navigation/              # 导航相关模块
│   ├── __init__.py
│   ├── RouteStore.py   # 路线数据管理（内存持有 + 按需落盘）
│   ├── Navigator.py         # 编排类（串联传送、滑索、步行、交互）
│   ├── Teleporter.py        # 传送
│   ├── Zipliner.py          # 滑索
│   ├── Walker.py            # 步行
│   ├── Interactor.py        # 目的地交互
│   └── Recorder.py          # 录制
├── tasks/                   # 任务入口（UI 层）
│   ├── NavigationTask.py
│   ├── RecordTask.py
│   └── ...
```

---

## 一、传送实现方案

### 状态：已稳定

### 实现

- 工具类：`src/navigation/Teleporter.py`
- 配置文件：`assets/teleport_points.json`、`assets/area_coordinates.json`

### 流程

1. 按 m 打开地图
2. OCR 识别当前位置（世界/区域/地区）
3. 切换到目标区域
4. 拖拽地图、点击传送点坐标
5. 点击"传送"按钮

### 数据格式

```json
{
  "name": "传送点名称",
  "world": "塔卫二",
  "region": "武陵",
  "area": "武陵城",
  "direction": "bottom_right",
  "coordinates": "0.45,0.62"
}
```

---

## 二、滑索实现方案

### 状态：已稳定

### 实现

- 工具类：`src/navigation/Zipliner.py`
- 滑索数据内联在 `assets/route.json` 的 steps 中，以 nodes 列表形式存储

### 核心流程

1. 检测屏幕右下角"登上滑索架"提示，按 F 登上
2. 等待底部出现"向目标移动"或"离开滑索架"确认已在滑索上
3. 对每个节点：
   - 若有 `angle_x`/`angle_y` 或 `mouse_x`/`mouse_y`，先调整视角
   - 两阶段 OCR 对齐距离数字到屏幕中心 → 点击选择 → 等待到达下一节点
4. 全部滑完后按 ESC 离开滑索架

### OCR 对齐策略

采用**角度开环移动 + 两阶段搜索 + 金色确认**的对齐方式：

**色彩过滤**（HSV 范围定义在 `src/image/hsv_config.py` 的 `HSVRange` 枚举中）：

- `GOLD_SELECTED`：选中态金色文字（H=20-35, S=45-80, V=230-255）
- `WHITE`：未选中白色文字（H=0-180, S=0-50, V=200-255）

**阶段1 — 大范围扫描**：
- 全屏范围同时扫描金色和白色，金色优先
- 找到目标后计算角度偏移，一步移动到目标位置
- 白色命中时移动量 ×0.7 避免过冲
- 未找到目标时系统化扫描（每次固定转 30°，12 轮覆盖 360°）

**阶段2 — 小范围金色确认**：
- 切换到屏幕中心 40% 区域，仅扫描金色
- 金色命中且偏移 ≤ 容差（10px）→ 对齐完成
- 金色命中但偏差大 → 微调移动（×0.7 衰减防震荡）
- 连续 10 次未找到金色 → 回退阶段1

**关键参数**：
- 容差：10px
- 最大尝试轮次：50
- 角度换算：`FULL_CIRCLE_RATIO = 2.222`（360° = 2.222 × 窗口宽度 像素）

### 数据格式

每个节点包含必填的 `distance` 和可选的视角调整参数：

```json
{
  "type": "zipline",
  "nodes": [
    {"distance": 66},
    {"distance": 108, "angle_x": -20},
    {"distance": 53}
  ]
}
```

| 字段 | 必填 | 说明 |
|------|------|------|
| `distance` | 是 | 目标滑索距离（整数） |
| `angle_x` | 否 | 对齐前水平视角调整（角度，正值向右） |
| `angle_y` | 否 | 对齐前垂直视角调整（角度，正值向下） |
| `mouse_x` | 否 | 对齐前鼠标水平位移（像素，兼容旧格式） |
| `mouse_y` | 否 | 对齐前鼠标垂直位移（像素，兼容旧格式） |

> 推荐使用 `angle_x`/`angle_y`（角度），录制器默认输出此格式。`mouse_x`/`mouse_y`（像素）为兼容旧数据保留。

### API

```python
zipliner = Zipliner(task)  # task 为 BaseEfTask 实例
zipliner.execute([
    {"distance": 66},
    {"distance": 108, "angle_x": -20},
    {"distance": 53},
])
```

---

## 三、步行实现方案

### 状态：已稳定

### 实现

- 工具类：`src/navigation/Walker.py`

### API

```python
walker = Walker(task)  # task 为 BaseEfTask 实例
walker.execute([
    {"key": "w", "duration": 3},                    # 单键
    {"key": ["w", "a"], "duration": 1.5},            # 组合键
    {"angle_x": 90, "angle_y": 0},                   # 视角调整（角度）
    {"mouse_x": 200, "mouse_y": 0},                  # 鼠标位移（像素，兼容旧格式）
    {"button": "left"},                              # 鼠标左键点击
    {"button": "right"},                             # 鼠标右键点击
    {"sleep": 1.0},                                  # 等待
])
```

支持的指令字段（同一 action 中可组合，按顺序执行）：

| 字段 | 说明 |
|------|------|
| `key` + `duration` | 按键（单键或组合键列表） |
| `angle_x` / `angle_y` | 视角调整（角度） |
| `mouse_x` / `mouse_y` | 鼠标位移（像素，兼容旧格式） |
| `button` | 鼠标点击（`"left"` / `"right"`） |
| `sleep` | 等待指定秒数 |
| `after_sleep` | 动作完成后额外等待 |
| `count` | 重复执行次数（默认 1） |

---

## 四、路线数据管理

### 状态：已实现

### 实现

- 数据管理类：`src/navigation/RouteStore.py`
- 数据文件：`assets/route.json`

### 设计原则

- 内存持有：启动时从 JSON 加载全部路线到内存，所有查询和修改操作都在内存中完成
- 按需落盘：仅在显式调用 `flush()` 时写入文件
- 每条路线有唯一 `id`（UUID4 前 8 位），加载时自动为无 id 的老数据补上

### 数据格式

```json
{
  "id": "a3f8b2c1",
  "name": "军械库",
  "type": "采集物",
  "area": "谷地通道",
  "teleport": "通道入口",
  "steps": [...]
}
```

### API

```python
store = RouteStore()

# 查询
store.all()                              # 全部路线
store.find(name, dest_type=None)         # 按 name + type 精确查找
store.find_by_type(dest_type)            # 按 type 过滤
store.find_by_id(route_id)               # 按 id 查找

# 写入（仅改内存）
store.save(route)                        # 有相同 id 则覆盖，无 id 则生成并追加
store.delete(route_id)                   # 按 id 删除

# 落盘
store.flush()                            # 将内存数据写入 route.json

# 重载
store.reload()                           # 从文件重新加载（丢弃未落盘的修改）
```

### 调用方

| 调用方 | 使用的方法 |
|--------|-----------|
| Navigator | `find()`, `find_by_type()`, `all()` |
| NavigationTask | `find()`, `save()`, `flush()` |
| RecordTask | `save()`, `flush()` |

---

## 五、自动导航实现方案

### 状态：已实现

### 实现

- 数据管理：`src/navigation/RouteStore.py` — 路线数据内存管理与落盘
- 编排类：`src/navigation/Navigator.py` — 串联传送、滑索、步行、交互完成完整路线
- 任务类：`src/tasks/NavigationTask.py` — UI 任务入口，提供目的地下拉选择
- 配置文件：`assets/route.json`

### 数据格式

每条路线是一个有序的 steps 列表，系统按顺序执行：

```json
{
  "name": "军械库",
  "type": "采集物",
  "area": "谷地通道",
  "teleport": "通道入口",
  "steps": [
    {"type": "zipline", "nodes": [
      {"distance": 66},
      {"distance": 108, "angle_x": -20},
      {"distance": 53}
    ]},
    {"type": "walk", "actions": [
      {"key": "a", "duration": 0.4},
      {"angle_x": 90},
      {"button": "left"}
    ]}
  ]
}
```

### step 类型说明

| type | 字段 | 说明 |
|------|------|------|
| `walk` | `actions` | 步行指令序列（按键、视角调整、鼠标点击、等待） |
| `zipline` | `nodes` | 滑索节点列表，每个节点含 `distance` 及可选的 `angle_x`/`angle_y` |

### 执行流程

```
输入：目的地名称 + 类型（如 "军械库", "采集物"）

1. 从 route.json 按 name + type 查找路线
2. Teleporter.teleport_to(teleport) 传送到起始点
3. 按顺序执行 steps:
   - walk    → Walker.execute(actions)
   - zipline → Zipliner.execute(nodes)
4. 到达目的地后执行交互 → Interactor.execute(type, dest)
```

### API

```python
navigator = Navigator(task)
navigator.navigate_to("军械库", dest_type="采集物")  # 按名称+类型导航
navigator.find_routes_by_type("采集物")              # 按类型查找路线
```

---

## 六、目的地交互实现方案

### 状态：部分已实现

### 实现

- 工具类：`src/navigation/Interactor.py`
- 交互类型复用 `route.json` 中路线的 `type` 字段

### 目的地类型

| 类型 | 说明 | 交互方式 |
|------|------|------|
| `采集物` | 可采集资源 | 无需 Interactor，交互已内联在路线 walk actions 中 |
| `矿物` | 矿石资源 | 无需 Interactor，交互已内联在路线 walk actions 中 |
| `资源回收站` | 资源回收点 | OCR 检测"收取资源" → 按 F |
| `送货` | 送货目的地 | OCR 检测目的地名称 → 按 F |
| `仓储节点` | 取货点 | OCR 检测"取货" → 按 F |
| `能量淤积点` | 能量清除点 | TODO |

### 集成

Navigator 在导航完成后自动调用 Interactor：

```
导航到目的地 → 执行 steps → 读取 type → Interactor.execute(type, dest)
```

采集物和矿物类型不会触发 Interactor，其交互操作直接录制在路线的 walk actions 中（如按 F 采集、攻击矿石等）。

### API

```python
interactor = Interactor(task)
interactor.execute("资源回收站", dest)
```

---

## 七、导航录制实现方案

### 状态：已实现

### 实现

- 录制类：`src/navigation/Recorder.py` — 键鼠监听、状态机、按键合并、滑索检测
- 任务类：`src/tasks/RecordTask.py` — UI 任务入口
- 详细设计：`docs/navigation_record_design.md`

### 流程

```
用户填写元数据（name / type / area / teleport）
  → 程序传送到指定传送点
  → 传送完成，自动开始录制
  → 用户手动操作（步行 / 转视角 / 点击 / 上滑索）
  → 按 F12 停止录制
  → 生成路线追加到 route.json
```

### 录制内容

| 操作 | 录制结果 |
|------|---------|
| WASD / Shift / Space | `{"key": "w", "duration": 1.5}` 或组合键 `{"key": ["w", "a"], ...}` |
| 鼠标移动 | `{"angle_x": 45.5, "angle_y": -30.2}` |
| 鼠标左右键点击 | `{"button": "left"/"right"}` |
| F 键 + 检测到滑索架 | 进入滑索模式，OCR 记录距离及视角偏移，输出 `{"type": "zipline", "nodes": [{"distance": 66}, {"distance": 108, "angle_x": 15.3}]}` |
| F 键 + 无滑索架 | `{"key": "f", "duration": 0.1}` |
| F12 | 停止录制 |
