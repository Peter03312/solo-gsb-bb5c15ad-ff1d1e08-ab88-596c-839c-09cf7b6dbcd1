# 数控刀路禁入区审查服务

基于 **FastAPI + PostgreSQL** 的 HTTP API：登记毫米制二维多边形禁入区（含闭合 Z 高度范围，修改产生不可变新版本），并对 G-code 刀路做连续碰撞审查，输出不可变审查报告。

## 一键启动

```bash
docker compose up --build
```

- 服务地址：**http://localhost:8000**（交互式文档：http://localhost:8000/docs）
- PostgreSQL：localhost:5432（用户/密码/库名默认均为 `cnc`）
- 数据库表结构由应用启动时自动初始化（含等待数据库就绪的重试），无需手工执行 SQL。

### 配置（环境变量）

| 变量 | 默认值 | 说明 |
|---|---|---|
| `APP_PORT` | `8000` | API 对外端口（compose） |
| `DB_PORT` | `5432` | 数据库对外端口（compose） |
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `cnc` | 数据库账号 |
| `DATABASE_URL` | `postgresql+psycopg2://cnc:cnc@db:5432/cnc` | 应用侧连接串（直接运行应用时生效） |

本地开发（不用 Docker）：

```bash
pip install -r requirements.txt
DATABASE_URL=postgresql+psycopg2://cnc:cnc@localhost:5432/cnc \
  uvicorn app.main:app --host 0.0.0.0 --port 8000
# 测试（SQLite，无需数据库）：
python3 -m pytest tests/
```

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/zones` | 登记禁区（版本 1）：`polygon` 毫米制二维顶点、`z_min`/`z_max` 闭合高度范围 |
| `PUT` | `/zones/{zone_id}` | 修改禁区：生成**不可变新版本**，旧版本仍可查询、仍可用于审查 |
| `GET` | `/zones/{zone_id}` | 当前版本 |
| `GET` | `/zones/{zone_id}/versions` | 版本列表 |
| `GET` | `/zones/{zone_id}/versions/{version}` | 指定历史版本 |
| `POST` | `/reviews` | 审查刀路，生成不可变报告 |
| `GET` | `/reports` / `/reports/{id}` | 查询报告 |

### 审查输入（`POST /reviews`）

```json
{
  "zones": [{"zone_id": 1, "version": 2}],
  "initial_position": {"x": -10.0, "y": 5.0, "z": 0.0},
  "tool_radius": 1.0,
  "gcode": "G21 G17 G90\nG1 Z-2 F500\nX20 Y5\n"
}
```

- `zones`：一个或多个禁区，**各自钉定版本**；报告记录所用版本，之后禁区更新不影响旧报告。
- `initial_position`：毫米制初始刀尖坐标；`tool_radius`：毫米制刀具半径（≥0）。
- 报告内容：所用禁区版本、输入摘要（初始坐标、刀具半径、G-code 行数与 SHA-256）、**首个碰撞的原始行号与禁区编号**，或无碰撞结论。

### G-code 语义

- 模态解析：`G0/G1/G2/G3`（运动）、`G17`（XY 平面）、`G20/G21`（英寸/毫米，G20 自动换算为毫米）、`G90/G91`（绝对/增量）；缺省轴沿用前值。缺省模态：`G1 G17 G21 G90`。
- 圆弧仅限 XY 平面恒定 Z；`I/J` 始终相对弧起点；终点与起点相同表示整圆；`Z` 变化（螺旋弧）、`R` 格式、端点不在圆上、零半径均判为非法。
- 注释：`(...)` 与 `;` 至行尾；`F/S/T/M/N` 字忽略；`%` 行忽略。
- **碰撞判定**：按程序顺序对每段连续运动精确求距（非端点采样）——刀尖 Z 落在禁区闭合高度区间内，且水平路径到多边形的距离 ≤ 刀具半径即碰撞，**边界接触也算**。
- **明确拒绝（HTTP 422，且不留报告）**：非法多边形（自交/退化/面积为零）、非法 Z 区间、负刀具半径、非法圆弧、不支持的运动/坐标系指令（如 `G18/G19`、`G4`、`G54` 等未知 G 字）、未知字地址、无法解析的行。禁区版本不存在返回 404。

## 调用示例

```bash
bash examples/curl_examples.sh        # curl 全流程示例
python3 examples/review_example.py    # Python (requests) 全流程示例
```

## 项目结构

```
app/
  main.py       FastAPI 路由（禁区登记/版本、审查、报告）
  gcode.py      模态 G-code 解析器（G0-G3/G17/G20/G21/G90/G91）
  geometry.py   二维精确几何：简单多边形校验、线段/圆弧到多边形距离
  review.py     连续运动碰撞检查（含 Z 变化子段截取）
  db.py         SQLAlchemy 模型与初始化（zones / zone_versions / reports）
  schemas.py    Pydantic 请求/响应模型
examples/       调用示例（curl / Python）
tests/          pytest 测试（几何、解析器、碰撞、API 与报告不可变性）
```
