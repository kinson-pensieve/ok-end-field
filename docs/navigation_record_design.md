# 导航录制方案

## 概述

通过监听用户的键鼠操作，自动录制导航路线并写入 `configs/route.json`，替代手动编写路线配置。

## 整体流程

```
用户填写元数据（name / type / area / teleport）
  → 程序传送到指定传送点
  → 传送完成，自动开始录制
  → 用户手动操作（步行 / 转视角 / 上滑索）
  → 按 F12 停止录制
  → 生成 route 写入 route.json
```

## 录制内容

### 1. 步行按键（walk action）

监听 WASD、Shift、Space 的 press/release 事件，记录按键和持续时间。

- 单键：`{"key": "w", "duration": 1.5}`
- 组合键（同时按下多个键）：`{"key": ["w", "a"], "duration": 0.8}`

**合并规则**：
- on_press 记录按下时间戳和键名
- on_release 计算 duration = release_time - press_time
- 多个键在时间上重叠则合并为组合键

### 2. 鼠标移动（视角调整 action）

监听鼠标位移事件，累积 dx/dy，换算为角度输出。

- 输出格式：`{"angle_x": 45.5, "angle_y": -30.2}`
- 角度换算：`FULL_CIRCLE_RATIO = 2.222`（360° = 2.222 × 窗口宽度 像素）

**聚合规则**：
- 鼠标移动事件频率很高，需要在时间窗口内（如 100ms 无新移动）聚合为一条 action
- 累积窗口内的 dx 和 dy 总和，最终换算为角度

### 3. 滑索（zipline step）

当用户按 F 时，OCR 检测屏幕右下角是否有"登上滑索架"提示：

- **有**：进入滑索录制模式
  - 暂停 walk 录制
  - 等待用户在滑索上选择目标，OCR 记录每次选中的距离数字及视角偏移
  - 用户按 ESC 离开滑索架后，输出 `{"type": "zipline", "nodes": [{"distance": 66}, {"distance": 108, "angle_x": 15.3}]}`
  - 恢复 walk 录制
- **无**：作为普通 F 按键录入 walk action

### 4. 停止录制

按 F12 结束录制，不录入 F12 本身。

## 录制状态机

```
                 ┌──────────┐
                 │  IDLE    │  用户填写元数据
                 └────┬─────┘
                      │ 传送完成
                      ▼
                 ┌──────────┐
            ┌───→│ WALKING  │←──┐
            │    └────┬─────┘   │
            │         │ F键 +   │ ESC离开
            │         │ 检测到  │ 滑索架
            │         │ 滑索架  │
            │         ▼         │
            │    ┌──────────┐   │
            │    │ ZIPLINING│───┘
            │    └──────────┘
            │
            │ F12
            ▼
       ┌──────────┐
       │  DONE    │  保存到 JSON
       └──────────┘
```

## 输出格式

录制完成后生成一条完整路线，追加到 `route.json`：

```json
{
  "name": "用户填写的名称",
  "type": "采集物",
  "area": "谷地通道",
  "teleport": "通道入口",
  "steps": [
    {"type": "walk", "actions": [
      {"key": "w", "duration": 1.5},
      {"angle_x": 45.5, "angle_y": -30.2},
      {"key": ["w", "a"], "duration": 0.8}
    ]},
    {"type": "zipline", "nodes": [
      {"distance": 66},
      {"distance": 108, "angle_x": 15.3},
      {"distance": 53}
    ]},
    {"type": "walk", "actions": [
      {"key": "a", "duration": 0.4}
    ]}
  ]
}
```

注意：walk 和 zipline 交替出现时，会拆分为多个 step。

## 技术方案

### 输入监听

项目目前只有输入发送能力（`user32.keybd_event`、`user32.mouse_event`），没有输入监听能力。需要引入 `pynput` 库：

- `pynput.keyboard.Listener`：监听键盘 press/release
- `pynput.mouse.Listener`：监听鼠标移动

### 监听的按键范围

| 按键 | 处理方式 |
|------|---------|
| W / A / S / D | 录入 walk action，记录 duration |
| Shift | 录入 walk action（冲刺） |
| Space | 录入 walk action（跳跃） |
| F | 检测滑索架 → 进入滑索模式；否则录入 walk action |
| ESC | 滑索模式下离开滑索架，恢复 walk 录制 |
| F12 | 停止录制 |
| 鼠标移动 | 录入视角调整 action（角度） |

### 按键合并逻辑

```
按键状态表: {key: press_time}

on_press(key):
  if key not in 按键状态表:
    按键状态表[key] = current_time

on_release(key):
  if key in 按键状态表:
    duration = current_time - 按键状态表[key]
    # 检查是否有其他键同时按下（时间重叠）
    # 重叠的键合并为组合键 ["w", "a"]
    输出 action
    del 按键状态表[key]
```

### 鼠标聚合逻辑

```
鼠标缓冲: {dx: 0, dy: 0, last_time: 0}

on_move(dx, dy):
  鼠标缓冲.dx += dx
  鼠标缓冲.dy += dy
  鼠标缓冲.last_time = current_time

定时检查（每 100ms）:
  if 鼠标缓冲非零 and current_time - last_time > 100ms:
    将累积的 dx/dy 换算为 angle_x/angle_y
    输出 angle action
    清空缓冲
```

### 滑索录制逻辑

```
进入滑索模式后:
  nodes = []
  循环:
    OCR 检测底部文字
    if 检测到"离开滑索架"并且用户按了 ESC:
      输出 zipline step（nodes 列表）
      退出滑索模式
    if 检测到用户点击选择了某个距离:
      node = {"distance": 距离数字}
      if 有视角偏移:
        node["angle_x"] = 角度
        node["angle_y"] = 角度
      nodes.append(node)
```

## 涉及文件

| 操作 | 文件 |
|------|------|
| 新增依赖 | `requirements.txt`（添加 pynput） |
| 已实现 | `src/navigation/Recorder.py`（录制工具类） |
| 已实现 | `src/tasks/RecordTask.py`（UI 任务入口） |
| 修改 | `configs/route.json`（录制结果追加） |

## UI 配置项

RecordTask 需要用户填写以下配置：

| 配置项 | 类型 | 说明 |
|--------|------|------|
| 目的地名称 | 文本输入 | route 的 name |
| 目的地类型 | 下拉选择 | 采集物 / 矿物 / 回收站 / 角色 |
| 所属地区 | 下拉选择 | 从 teleport_points.json 的 area 去重获取 |
| 传送点 | 下拉选择 | 根据所选地区过滤 teleport_points.json |
