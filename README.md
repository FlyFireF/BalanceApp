# Money Manager — 本地个人记账桌面应用

Windows 本地运行的单用户财务管理应用：记录收入 / 支出，按月查看各渠道
（Channel）的消费额、余额与余额进度，严格区分「渠道 Channel / 实际账户
Account / 分类 Category」三层概念。

开源协议：[MIT License](LICENSE) · Copyright (c) 2026 FlyFireF

> 开发进度：**全部 Phase 完成**（Phase 1-10，含打包配置与文档）。
> 开发严格按《开发需求.md》分阶段进行，每个阶段完成后暂停确认。

## 功能

- 收入 / 支出记账：金额、日期、渠道、账户、分类、备注、标签（未选分类自动归入 Other）
- 三栏主界面：左侧导航 / 中间记账 + 历史记录 / 右侧月度 Dashboard
- Dashboard：本月收入 / 支出 / 净额；各渠道本月与累计收支、余额、月度口径剩余百分比
  与渐变进度条（红→绿）；渠道支持「每月固定金额」（如固定工资，统计自动计入）
- 历史记录：编辑、删除（二次确认）、搜索（Ctrl+F）、翻页（10/20/50/100 每页）、
  多级排序（最多 3 级）与筛选（类型/渠道/账户/分类/日期范围）
- 渠道 / 账户 / 分类管理：新增、编辑、停用/启用、删除（仅限已停用，二次确认）
- CSV / XLSX / JSON 导入导出（逐行校验、整体失败保护、重复自动跳过）
- SQLite 每日自动备份，保留天数可设置（默认 30 天）
- 主题：浅色 / 深色 / 跟随系统（默认），Windows 原生控件风格
- 快捷键：Ctrl+F 搜索、Esc 取消、Delete 删除（仍二次确认）
- 打包为 Windows 可执行程序（PyInstaller，见下方「Windows 打包」）

## 技术栈

| 组件 | 用途 |
| --- | --- |
| Python 3.10+（开发环境 3.13） | 语言 |
| PySide6（含 QtCharts） | GUI |
| SQLAlchemy 2.x | ORM |
| SQLite | 本地数据库 |
| openpyxl | XLSX 导入导出 |
| pytest | 测试 |

## 项目结构

```text
BalanceApp/
├── app.py                     # 应用入口
├── requirements.txt           # 运行依赖清单
├── requirements-build.txt     # 打包依赖（PyInstaller，仅构建时安装）
├── money_manager.spec         # PyInstaller 打包配置
├── build.bat                  # 一键打包脚本
├── conftest.py                # pytest 根配置
├── config/
│   └── settings.py            # 路径与默认配置
├── database/
│   ├── database.py            # 引擎 / 会话 / 初始化
│   ├── models.py              # ORM 模型（Channel/Account/Category/Transaction/Setting）
│   ├── seed.py                # 默认数据（首次启动自动写入）
│   ├── migrations.py          # Schema 版本迁移（绝不 drop_all）
│   └── repositories/
│       └── transaction_repository.py   # 交易数据访问
├── services/
│   ├── catalog_service.py     # 渠道/账户/分类查询与管理
│   ├── transaction_service.py # 交易创建/编辑/删除（含校验）
│   ├── statistics_service.py  # 月度统计（本月/累计/百分比/账户余额）
│   ├── import_service.py      # CSV / XLSX / JSON 导入（逐行校验）
│   ├── export_service.py      # CSV / XLSX / JSON 导出
│   ├── backup_service.py      # 每日自动备份 + 过期清理
│   ├── dto.py                 # 服务层数据结构
│   └── exceptions.py          # 服务层异常
├── ui/
│   ├── main_window.py         # 主窗口（三栏布局）
│   ├── sidebar.py             # 左侧导航
│   ├── bookkeeping_panel.py   # 直接记账面板
│   ├── history_panel.py       # 历史记录表格
│   ├── dashboard.py           # 月度 Dashboard（渠道卡片 + 渐变进度条）
│   ├── theme.py               # 主题（浅色 / 深色 / 跟随系统）
│   ├── widgets/transaction_form.py    # 共用记账表单
│   ├── widgets/entity_table.py        # 管理页通用表格
│   └── dialogs/               # 编辑/管理/数据导入导出/设置弹窗
├── utils/
│   ├── currency.py            # 金额解析 / 格式化（Decimal）
│   └── logger.py              # 日志
└── tests/                     # pytest 测试
```

架构方向（需求 §45）：

```text
UI → Service → Repository / ORM → SQLite
```

## 环境要求

- Windows 10 / 11
- Python 3.10 或更高版本

## 安装

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 运行

```bash
python app.py
```

## 测试

```bash
python -m pytest tests -v
```

## 数据位置（重要）

默认数据目录：`%LOCALAPPDATA%\MoneyManager\`

| 内容 | 路径 |
| --- | --- |
| 数据库 | `%LOCALAPPDATA%\MoneyManager\data\money_manager.db` |
| 自动备份 | `%LOCALAPPDATA%\MoneyManager\backups\` |
| 日志 | `%LOCALAPPDATA%\MoneyManager\logs\app.log` |

- 不放在程序安装目录的原因：Windows 下可能没有写权限；用户数据与程序分离，升级不丢数据（需求 §35/§36）。
- 高级用法：设置环境变量 `MONEY_MANAGER_DATA_DIR` 可以把数据目录改到任意位置（测试就是用它指向临时目录）。

## 金额精度说明

SQLite 没有真正的 DECIMAL 类型，用 float 会出现 `0.1 + 0.2 = 0.30000000000000004`
之类的精度问题。本项目的方案：

- 数据库：金额以「分」为单位存整数（`¥1234.56 → 123456`）
- Python：统一使用 `decimal.Decimal` 运算
- 显示：统一 `¥1,234.56` 格式

## 软外键说明

交易对渠道/账户/分类的引用是「软外键」：引用可空 + `ON DELETE SET NULL`。
即使某个渠道/账户/分类被删除，历史交易也完全不受影响（引用置空，界面显示
「已删除」）。新建交易时仍必须选择有效实体；编辑历史交易时允许保持原有引用不变。

## 导入导出

侧边栏「数据管理」提供三种格式的双向导入导出：

| 格式 | 导出内容 | 导入规则 |
| --- | --- | --- |
| JSON | 全量数据（渠道/账户/分类/交易/设置） | 同名实体复用、重复交易自动跳过、忽略文件 id |
| CSV | 交易（中文表头，UTF-8 BOM） | 逐行校验（日期/金额/实体存在性），任何错误整体不导入 |
| XLSX | 4 个 Sheet（Transactions/Channels/Accounts/Categories） | 同 JSON，实体 Sheet 可选 |

导入安全原则：绝不覆盖或删除现有数据；错误信息带行号定位；
引用已停用实体只警告不阻断。

## Windows 打包（PyInstaller）

打包为单文件 `MoneyManager.exe`，双击运行、无控制台窗口。

**1. 安装打包依赖**（一次性）：

```bash
pip install -r requirements-build.txt
```

**2. 构建**（二选一）：

```bash
# 方式 A：一键脚本
build.bat

# 方式 B：直接命令
python -m PyInstaller money_manager.spec
```

**3. 产物**：`dist\MoneyManager.exe`

- 把这个 exe 拷到任意电脑（Windows 10/11）双击即可运行，无需安装 Python；
- **用户数据与程序文件分离**：数据库/备份/日志始终在
  `%LOCALAPPDATA%\MoneyManager\`——升级 exe、移动 exe 都不会丢数据；
- 首次启动稍慢（单文件自解压），属正常现象；
- 自定义图标：项目根目录放 `icon.ico`，把 `money_manager.spec` 中
  `icon=None` 改为 `icon="icon.ico"` 后重新构建。

**常见问题**：

- **杀毒软件误报**：PyInstaller 单文件 exe 偶发被误报，添加信任即可（也可改用 onedir 模式降低误报率）；
- **不想打包也能用**：见「运行」——桌面快捷方式指向 `.venv\Scripts\pythonw.exe`，参数填 `app.py` 即可。

## 常见问题

**Q: 数据库在哪里？**
见上方「数据位置」。

**Q: 如何完全重置数据？**
关闭应用后删除 `%LOCALAPPDATA%\MoneyManager\` 目录（注意：会删除所有账务数据，请先确认备份）。

**Q: 测试报 ImportError？**
请用 `python -m pytest tests -v` 运行（`-m` 会把项目根目录加入模块搜索路径）。

**Q: 数据库结构会随版本自动升级吗？**
会。启动时自动执行版本化迁移（绝不 `drop_all`），升级程序不会丢数据。
