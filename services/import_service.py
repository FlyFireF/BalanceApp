"""数据导入服务（需求 §28-§32）。

原则：
- 先全量校验、后写入：任何一行有错 → 本次导入整体失败，
  绝不部分写入、绝不静默丢弃错误数据（需求 §32）；
- 错误信息带定位：CSV/XLSX 用「第 N 行」，JSON 用「channels[i]」等索引；
- 幂等安全：重复交易（8 个字段完全一致）自动跳过并计数；
  同名渠道/账户/分类复用已有实体，绝不覆盖或删除现有数据；
- JSON 导入忽略文件中的 id、以名称匹配实体（需求 §29 的 ID 冲突处理）；
- 停用的渠道/账户/分类不能用于导入的交易，逐行给出明确错误。
"""

from __future__ import annotations

import csv
import json
import logging
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from database import database
from database.models import Account, Category, CategoryType, Channel, Setting, Transaction
from database.repositories.transaction_repository import TransactionRepository
from services.dto import ImportResult
from utils.currency import parse_amount

logger = logging.getLogger(__name__)

_TRANSACTION_TYPES = (CategoryType.INCOME.value, CategoryType.EXPENSE.value)

_CENT = Decimal("0.01")

_FIELD_MAP = {
    "日期": "date",
    "类型": "type",
    "金额": "amount",
    "渠道": "channel",
    "账户": "account",
    "分类": "category",
    "备注": "note",
    "标签": "tags",
}

_ENTRY_KEYS = ("type", "amount", "date", "channel", "account", "category", "note", "tags")


class _ImportContext:
    """导入期间的实体名称查找表（含文件中的待建实体）。"""

    def __init__(self, session) -> None:
        self.channels = {
            c.name: {"id": c.id, "is_active": c.is_active, "is_new": False}
            for c in session.scalars(select(Channel))
        }
        self.accounts = {
            a.name: {"id": a.id, "is_active": a.is_active, "is_new": False}
            for a in session.scalars(select(Account))
        }
        self.categories = {
            (c.type, c.name): {"id": c.id, "is_active": c.is_active, "is_new": False}
            for c in session.scalars(select(Category))
        }


def _to_text(value) -> str:
    return "" if value is None else str(value)


def _parse_date(text) -> date | None:
    """解析常见日期写法（ISO、斜杠、点号）；失败返回 None。"""
    text = (text or "").strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _validate_transaction_entry(
    entry: dict, context: _ImportContext
) -> tuple[str | None, str | None, dict | None]:
    """校验并规范化单笔交易。返回 (错误, 警告, 规范化字段)。

    - 错误：阻断导入（如实体不存在、金额非法）；
    - 警告：不阻断（引用的实体已停用——用户确认的放宽规则）；
    - 字段中的渠道/账户/分类为名称。
    """
    tx_type = (entry.get("type") or "").strip()
    if tx_type not in _TRANSACTION_TYPES:
        return "交易类型无效", None, None

    try:
        amount = parse_amount(entry.get("amount") or "")
    except ValueError as exc:
        return str(exc), None, None
    if amount <= 0:
        return "金额必须大于 0", None, None
    amount = amount.quantize(_CENT, rounding=ROUND_HALF_UP)

    parsed_date = _parse_date(entry.get("date"))
    if parsed_date is None:
        return f"日期格式无效：{entry.get('date')!r}", None, None

    warning = None

    channel_name = (entry.get("channel") or "").strip()
    channel = context.channels.get(channel_name)
    if channel is None:
        return f"找不到 Channel = {channel_name}", None, None
    if not channel["is_active"]:
        warning = f"渠道 {channel_name} 已停用"

    account_name = (entry.get("account") or "").strip()
    account = context.accounts.get(account_name)
    if account is None:
        return f"找不到 Account = {account_name}", None, None
    if not account["is_active"]:
        warning = f"账户 {account_name} 已停用"

    category_name = (entry.get("category") or "").strip()
    if category_name:
        category = context.categories.get((tx_type, category_name))
        if category is None:
            return f"找不到 Category = {category_name}", None, None
        if not category["is_active"]:
            warning = f"分类 {category_name} 已停用"
    else:
        # 需求 §4.5：未填分类自动映射 Other
        if context.categories.get((tx_type, "Other")) is None:
            return "缺少 Other 分类，请先在分类管理中恢复", None, None
        category_name = "Other"

    note = (entry.get("note") or "").strip()
    tags = (entry.get("tags") or "").strip()
    if len(note) > 500:
        return "备注过长（最多 500 个字符）", None, None
    if len(tags) > 200:
        return "标签过长（最多 200 个字符）", None, None

    return None, warning, {
        "type": tx_type,
        "amount": amount,
        "date": parsed_date,
        "channel": channel_name,
        "account": account_name,
        "category": category_name,
        "note": note,
        "tags": tags,
    }


class ImportService:
    """数据导入：UI 只经由本服务读取文件并写入数据库。"""

    def __init__(self, session_factory: sessionmaker | None = None) -> None:
        self._session_factory = session_factory or database.get_session_factory()

    # ================= CSV =================

    def import_csv(self, path: Path) -> ImportResult:
        """导入交易 CSV（需求 §30/§32）：逐行校验，任何错误 → 整体不导入。"""
        from services.export_service import CSV_HEADERS

        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as f:
                rows = list(csv.reader(f))
        except (OSError, csv.Error) as exc:
            return ImportResult(errors=[f"无法读取文件：{exc}"])
        if not rows:
            return ImportResult(errors=["文件为空"])
        header = [cell.strip() for cell in rows[0]]
        if header != CSV_HEADERS:
            return ImportResult(errors=[f"表头不正确，应为：{'、'.join(CSV_HEADERS)}"])

        errors: list[str] = []
        warnings: list[str] = []
        candidates: list[dict] = []
        with database.session_scope(self._session_factory) as session:
            context = _ImportContext(session)
            for line_no, raw in enumerate(rows[1:], start=2):
                if not raw or all(not cell.strip() for cell in raw):
                    continue
                if len(raw) < len(CSV_HEADERS):
                    errors.append(f"第 {line_no} 行：列数不足（应为 {len(CSV_HEADERS)} 列）")
                    continue
                entry = {_FIELD_MAP[key]: value.strip() for key, value in zip(CSV_HEADERS, raw)}
                error, warning, prepared = _validate_transaction_entry(entry, context)
                if error:
                    errors.append(f"第 {line_no} 行：{error}")
                else:
                    if warning:
                        warnings.append(f"第 {line_no} 行：{warning}")
                    candidates.append(prepared)
        if errors:
            return ImportResult(errors=errors, warnings=warnings)

        # 应用：CSV 不含实体定义，实体必须已存在于数据库
        with database.session_scope(self._session_factory) as session:
            context = _ImportContext(session)

            def resolve(entry: dict) -> dict:
                return {
                    "type": entry["type"],
                    "amount": entry["amount"],
                    "date": entry["date"],
                    "channel_id": context.channels[entry["channel"]]["id"],
                    "account_id": context.accounts[entry["account"]]["id"],
                    "category_id": context.categories[(entry["type"], entry["category"])]["id"],
                    "note": entry["note"],
                    "tags": entry["tags"],
                }

            imported, skipped = self._apply_prepared(session, candidates, resolve)
        result = ImportResult(imported=imported, skipped_duplicates=skipped, warnings=warnings)
        logger.info("导入 CSV：%s（新增 %d，跳过重复 %d）", path, imported, skipped)
        return result

    # ================= JSON =================

    def import_json(self, path: Path) -> ImportResult:
        """导入完整 JSON（需求 §29）：实体按名称复用、交易新增、设置按键恢复。"""
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            return ImportResult(errors=[f"无法读取 JSON 文件：{exc}"])
        if not isinstance(data, dict):
            return ImportResult(errors=["JSON 结构错误：顶层必须是对象"])
        for key in ("channels", "accounts", "categories", "transactions"):
            if key not in data:
                return ImportResult(errors=[f"JSON 结构错误：缺少 {key}"])
        if not isinstance(data.get("transactions"), list):
            return ImportResult(errors=["JSON 结构错误：transactions 必须是数组"])

        errors: list[str] = []
        warnings: list[str] = []
        channel_entries, errors = _parse_channel_entries(data.get("channels"), errors)
        account_entries, errors = _parse_account_entries(data.get("accounts"), errors)
        category_entries, errors = _parse_category_entries(data.get("categories"), errors)
        settings_entries, errors = _parse_settings_entries(data.get("settings"), errors)
        if errors:
            return ImportResult(errors=errors)

        candidates: list[dict] = []
        with database.session_scope(self._session_factory) as session:
            context = _ImportContext(session)
            # 注入文件中定义的新实体（同名已在库中的复用）
            for name, entry in channel_entries.items():
                if name not in context.channels:
                    context.channels[name] = {"id": None, "is_active": entry["is_active"], "is_new": True}
            for name, entry in account_entries.items():
                if name not in context.accounts:
                    context.accounts[name] = {"id": None, "is_active": entry["is_active"], "is_new": True}
            for key, entry in category_entries.items():
                if key not in context.categories:
                    context.categories[key] = {"id": None, "is_active": entry["is_active"], "is_new": True}

            for idx, item in enumerate(data["transactions"]):
                if not isinstance(item, dict):
                    errors.append(f"transactions[{idx}]：必须是对象")
                    continue
                entry = {key: _to_text(item.get(key)) for key in _ENTRY_KEYS}
                error, warning, prepared = _validate_transaction_entry(entry, context)
                if error:
                    errors.append(f"transactions[{idx}]：{error}")
                else:
                    if warning:
                        warnings.append(f"transactions[{idx}]：{warning}")
                    candidates.append(prepared)
        if errors:
            return ImportResult(errors=errors, warnings=warnings)

        with database.session_scope(self._session_factory) as session:
            result = self._apply_with_entities(
                session, candidates, channel_entries, account_entries, category_entries,
                settings_entries,
            )
        result.warnings = warnings
        logger.info("导入 JSON：%s（%s）", path, result.summary())
        return result

    # ================= XLSX =================

    def import_xlsx(self, path: Path) -> ImportResult:
        """导入 Excel（需求 §31）：Transactions 必选，三个实体 Sheet 可选。"""
        from services.export_service import CSV_HEADERS

        try:
            from openpyxl import load_workbook

            workbook = load_workbook(path, read_only=True, data_only=True)
        except Exception as exc:
            return ImportResult(errors=[f"无法读取 Excel 文件：{exc}"])
        try:
            sheet_names = set(workbook.sheetnames)
            if "Transactions" not in sheet_names:
                return ImportResult(errors=["Excel 缺少 Transactions 工作表"])

            errors: list[str] = []
            channel_entries: dict[str, dict] = {}
            account_entries: dict[str, dict] = {}
            category_entries: dict[tuple[str, str], dict] = {}
            if "Channels" in sheet_names:
                channel_entries, errors = _parse_channel_entries(
                    _read_sheet_dicts(workbook["Channels"]), errors, prefix="Channels"
                )
            if "Accounts" in sheet_names:
                account_entries, errors = _parse_account_entries(
                    _read_sheet_dicts(workbook["Accounts"]), errors, prefix="Accounts"
                )
            if "Categories" in sheet_names:
                category_entries, errors = _parse_category_entries(
                    _read_sheet_dicts(workbook["Categories"]), errors, prefix="Categories"
                )
            if errors:
                return ImportResult(errors=errors)

            ws_tx = workbook["Transactions"]
            header = [
                _to_text(cell.value).strip() for cell in next(ws_tx.iter_rows(min_row=1, max_row=1))
            ]
            if header != CSV_HEADERS:
                return ImportResult(errors=[f"表头不正确，应为：{'、'.join(CSV_HEADERS)}"])

            candidates: list[dict] = []
            warnings: list[str] = []
            with database.session_scope(self._session_factory) as session:
                context = _ImportContext(session)
                for name, entry in channel_entries.items():
                    if name not in context.channels:
                        context.channels[name] = {"id": None, "is_active": entry["is_active"], "is_new": True}
                for name, entry in account_entries.items():
                    if name not in context.accounts:
                        context.accounts[name] = {"id": None, "is_active": entry["is_active"], "is_new": True}
                for key, entry in category_entries.items():
                    if key not in context.categories:
                        context.categories[key] = {"id": None, "is_active": entry["is_active"], "is_new": True}

                for line_no, row in enumerate(ws_tx.iter_rows(min_row=2, values_only=True), start=2):
                    if row is None or all(v is None or not str(v).strip() for v in row):
                        continue
                    raw = [_to_text(v) for v in row]
                    if len(raw) < len(CSV_HEADERS):
                        errors.append(f"第 {line_no} 行：列数不足（应为 {len(CSV_HEADERS)} 列）")
                        continue
                    entry = {_FIELD_MAP[key]: raw[i] for i, key in enumerate(CSV_HEADERS)}
                    error, warning, prepared = _validate_transaction_entry(entry, context)
                    if error:
                        errors.append(f"第 {line_no} 行：{error}")
                    else:
                        if warning:
                            warnings.append(f"第 {line_no} 行：{warning}")
                        candidates.append(prepared)
            if errors:
                return ImportResult(errors=errors, warnings=warnings)

            with database.session_scope(self._session_factory) as session:
                result = self._apply_with_entities(
                    session, candidates, channel_entries, account_entries, category_entries, None
                )
            result.warnings = warnings
            logger.info("导入 XLSX：%s（%s）", path, result.summary())
            return result
        finally:
            workbook.close()

    # ================= 内部：应用阶段 =================

    def _apply_with_entities(
        self,
        session,
        candidates: list[dict],
        channel_entries: dict,
        account_entries: dict,
        category_entries: dict,
        settings_entries: dict | None,
    ) -> ImportResult:
        """创建新实体与交易（重复跳过），恢复设置。"""
        context = _ImportContext(session)

        new_channels: dict[str, Channel] = {}
        created_channels = 0
        for name, entry in channel_entries.items():
            if name in context.channels:
                continue
            obj = Channel(
                name=name,
                description=entry["description"],
                monthly_amount=entry["monthly_amount"],
                is_active=entry["is_active"],
            )
            session.add(obj)
            new_channels[name] = obj
            created_channels += 1

        new_accounts: dict[str, Account] = {}
        created_accounts = 0
        for name, entry in account_entries.items():
            if name in context.accounts:
                continue
            obj = Account(
                name=name,
                description=entry["description"],
                initial_balance=entry["initial_balance"],
                is_active=entry["is_active"],
            )
            session.add(obj)
            new_accounts[name] = obj
            created_accounts += 1

        new_categories: dict[tuple[str, str], Category] = {}
        created_categories = 0
        for (cat_type, name), entry in category_entries.items():
            if (cat_type, name) in context.categories:
                continue
            obj = Category(
                name=name,
                type=cat_type,
                description=entry["description"],
                is_active=entry["is_active"],
            )
            session.add(obj)
            new_categories[(cat_type, name)] = obj
            created_categories += 1

        session.flush()  # 新实体获得 id

        def resolve(entry: dict) -> dict:
            # 优先查本次导入新建的实体，否则查数据库已有实体
            if entry["channel"] in new_channels:
                channel_id = new_channels[entry["channel"]].id
            else:
                channel_id = context.channels[entry["channel"]]["id"]
            if entry["account"] in new_accounts:
                account_id = new_accounts[entry["account"]].id
            else:
                account_id = context.accounts[entry["account"]]["id"]
            category_key = (entry["type"], entry["category"])
            if category_key in new_categories:
                category_id = new_categories[category_key].id
            else:
                category_id = context.categories[category_key]["id"]
            return {
                "type": entry["type"],
                "amount": entry["amount"],
                "date": entry["date"],
                "channel_id": channel_id,
                "account_id": account_id,
                "category_id": category_id,
                "note": entry["note"],
                "tags": entry["tags"],
            }

        imported, skipped = self._apply_prepared(session, candidates, resolve)

        if settings_entries:
            for key, value in settings_entries.items():
                setting = session.get(Setting, key)
                if setting is None:
                    session.add(Setting(key=key, value=value))
                else:
                    setting.value = value

        return ImportResult(
            imported=imported,
            skipped_duplicates=skipped,
            created_channels=created_channels,
            created_accounts=created_accounts,
            created_categories=created_categories,
        )

    def _apply_prepared(self, session, candidates: list[dict], resolve) -> tuple[int, int]:
        """按名称解析 id 后创建交易；与现有完全一致的重复自动跳过。"""
        repo = TransactionRepository(session)
        signatures = {self._tx_signature(t) for t in repo.list_all()}
        imported = skipped = 0
        for entry in candidates:
            fields = resolve(entry)
            signature = self._fields_signature(fields)
            if signature in signatures:
                skipped += 1
                continue
            repo.add(Transaction(**fields))
            signatures.add(signature)
            imported += 1
        return imported, skipped

    @staticmethod
    def _amount_text(amount) -> str:
        """金额归一化为两位小数字符串（数据库读回是 Decimal('30')，
        导入侧是 Decimal('30.00')，直接 str 会导致重复判定失效）。"""
        return f"{Decimal(str(amount)).quantize(_CENT):.2f}"

    @staticmethod
    def _tx_signature(tx: Transaction) -> tuple:
        return (
            tx.type, ImportService._amount_text(tx.amount), tx.date.isoformat(),
            tx.channel_id, tx.account_id, tx.category_id, tx.note, tx.tags,
        )

    @staticmethod
    def _fields_signature(fields: dict) -> tuple:
        return (
            fields["type"], ImportService._amount_text(fields["amount"]), fields["date"].isoformat(),
            fields["channel_id"], fields["account_id"], fields["category_id"],
            fields["note"], fields["tags"],
        )


# ================= 模块级：实体条目解析 =================


def _check_name(name: str, label: str) -> str | None:
    name = name.strip()
    if not name:
        return f"{label}名称无效"
    if len(name) > 50:
        return f"{label}名称过长（最多 50 个字符）"
    return None


def _check_description(description: str) -> str | None:
    if len(description) > 200:
        return "描述过长（最多 200 个字符）"
    return None


def _parse_active(value) -> bool | None:
    """启用标记解析：接受布尔或 "true"/"false"/"1"/"0" 等字符串；
    其他类型返回 None（无效，由调用方报错）。"""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1", "yes"):
            return True
        if text in ("false", "0", "no"):
            return False
    return None


def _entity_is_active(item: dict, errors: list[str], where: str) -> bool | None:
    """解析并校验 is_active 字段；失败追加错误并返回 None。"""
    active = _parse_active(item.get("is_active", True))
    if active is None:
        errors.append(f"{where}：is_active 无效（应为 true / false）")
        return None
    return active


def _parse_channel_entries(items, errors: list[str], prefix: str = "channels") -> dict:
    entries: dict[str, dict] = {}
    if not isinstance(items, list):
        errors.append(f"{prefix}：必须是数组")
        return entries
    for idx, item in enumerate(items):
        where = f"{prefix}[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{where}：必须是对象")
            continue
        raw_name = item.get("name")
        if not isinstance(raw_name, str):
            errors.append(f"{where}：渠道名称无效（必须是字符串）")
            continue
        name = raw_name.strip()
        error = _check_name(name, "渠道")
        if error:
            errors.append(f"{where}：{error}")
            continue
        if name in entries:
            errors.append(f"{where}：渠道名称重复：{name}")
            continue
        description = _to_text(item.get("description", "")).strip()
        error = _check_description(description)
        if error:
            errors.append(f"{where}：{error}")
            continue
        try:
            monthly = parse_amount(_to_text(item.get("monthly_amount", "0")))
        except ValueError as exc:
            errors.append(f"{where}：每月固定金额{str(exc).replace('金额', '')}")
            continue
        if monthly < 0:
            errors.append(f"{where}：每月固定金额不能为负数")
            continue
        active = _entity_is_active(item, errors, where)
        if active is None:
            continue
        entries[name] = {
            "description": description,
            "monthly_amount": monthly.quantize(_CENT, rounding=ROUND_HALF_UP),
            "is_active": active,
        }
    return entries, errors


def _parse_account_entries(items, errors: list[str], prefix: str = "accounts") -> dict:
    entries: dict[str, dict] = {}
    if not isinstance(items, list):
        errors.append(f"{prefix}：必须是数组")
        return entries
    for idx, item in enumerate(items):
        where = f"{prefix}[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{where}：必须是对象")
            continue
        raw_name = item.get("name")
        if not isinstance(raw_name, str):
            errors.append(f"{where}：账户名称无效（必须是字符串）")
            continue
        name = raw_name.strip()
        error = _check_name(name, "账户")
        if error:
            errors.append(f"{where}：{error}")
            continue
        if name in entries:
            errors.append(f"{where}：账户名称重复：{name}")
            continue
        description = _to_text(item.get("description", "")).strip()
        error = _check_description(description)
        if error:
            errors.append(f"{where}：{error}")
            continue
        try:
            balance = parse_amount(_to_text(item.get("initial_balance", "0")))
        except ValueError as exc:
            errors.append(f"{where}：初始余额{str(exc).replace('金额', '')}")
            continue
        active = _entity_is_active(item, errors, where)
        if active is None:
            continue
        entries[name] = {
            "description": description,
            "initial_balance": balance.quantize(_CENT, rounding=ROUND_HALF_UP),
            "is_active": active,
        }
    return entries, errors


def _parse_category_entries(items, errors: list[str], prefix: str = "categories") -> dict:
    entries: dict[tuple[str, str], dict] = {}
    if not isinstance(items, list):
        errors.append(f"{prefix}：必须是数组")
        return entries
    for idx, item in enumerate(items):
        where = f"{prefix}[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{where}：必须是对象")
            continue
        raw_name = item.get("name")
        if not isinstance(raw_name, str):
            errors.append(f"{where}：分类名称无效（必须是字符串）")
            continue
        name = raw_name.strip()
        error = _check_name(name, "分类")
        if error:
            errors.append(f"{where}：{error}")
            continue
        cat_type = _to_text(item.get("type")).strip()
        if cat_type not in _TRANSACTION_TYPES:
            errors.append(f"{where}：分类类型无效：{cat_type!r}")
            continue
        if (cat_type, name) in entries:
            errors.append(f"{where}：分类名称重复：{name}")
            continue
        description = _to_text(item.get("description", "")).strip()
        error = _check_description(description)
        if error:
            errors.append(f"{where}：{error}")
            continue
        active = _entity_is_active(item, errors, where)
        if active is None:
            continue
        entries[(cat_type, name)] = {
            "description": description,
            "is_active": active,
        }
    return entries, errors


def _parse_settings_entries(items, errors: list[str]) -> dict:
    entries: dict[str, str] = {}
    if items is None:
        return entries, errors
    if not isinstance(items, dict):
        errors.append("settings：必须是对象")
        return entries, errors
    for key, value in items.items():
        key_text = str(key).strip()
        value_text = _to_text(value)
        if not key_text or len(key_text) > 50:
            errors.append(f"settings：无效的键 {key!r}")
            continue
        if len(value_text) > 200:
            errors.append(f"settings：{key_text} 的值过长")
            continue
        entries[key_text] = value_text
    return entries, errors


def _read_sheet_dicts(worksheet) -> list[dict]:
    """把 Sheet 数据行（跳过表头）转为字典列表，供实体解析复用。

    列布局与导出一致：Channels=名称/描述/启用；Accounts=名称/描述/初始余额/启用；
    Categories=名称/类型/描述/启用。
    """
    rows = []

    def _parse_bool(text: str) -> bool:
        return text.strip().lower() not in ("false", "0", "")

    for row in worksheet.iter_rows(min_row=2, values_only=True):
        if row is None or all(v is None for v in row):
            continue
        values = [_to_text(v).strip() for v in row]
        title = worksheet.title
        if title == "Accounts":
            item = {
                "name": values[0] if len(values) > 0 else "",
                "description": values[1] if len(values) > 1 else "",
                "initial_balance": values[2] if len(values) > 2 else "0",
                "is_active": _parse_bool(values[3]) if len(values) > 3 else True,
            }
        elif title == "Categories":
            item = {
                "name": values[0] if len(values) > 0 else "",
                "type": values[1] if len(values) > 1 else "",
                "description": values[2] if len(values) > 2 else "",
                "is_active": _parse_bool(values[3]) if len(values) > 3 else True,
            }
        else:  # Channels：名称/描述/每月固定金额/启用
            item = {
                "name": values[0] if len(values) > 0 else "",
                "description": values[1] if len(values) > 1 else "",
                "monthly_amount": values[2] if len(values) > 2 else "0",
                "is_active": _parse_bool(values[3]) if len(values) > 3 else True,
            }
        rows.append(item)
    return rows
