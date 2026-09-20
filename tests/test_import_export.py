"""测试导入导出（需求 §28-§32/§50）：三种格式 Export → Import → 数据一致。"""

from __future__ import annotations

import csv
import json
from datetime import date
from decimal import Decimal

from openpyxl import Workbook

from database.models import Setting
from services.catalog_service import CatalogService
from services.export_service import ExportService
from services.import_service import ImportService
from services.transaction_service import TransactionService
from helpers import seed_official_scenario


def _seed_source(seeded_factory, transaction_service, catalog_service) -> None:
    """源库：官方场景 + 自定义渠道（含每月固定金额）/账户/分类 + 新实体交易 + 改设置。"""
    seed_official_scenario(seeded_factory, transaction_service)
    channel_id = catalog_service.create_channel("稿费收入", "副业", Decimal("500"))
    account_id = catalog_service.create_account("证券账户", "股票", Decimal("1000.50"))
    category_id = catalog_service.create_category("打车", "expense", "出行")
    transaction_service.create(
        type="expense", amount=Decimal("30.00"), date=date(2026, 9, 15),
        channel_id=channel_id, account_id=account_id, category_id=category_id,
        note="打车费", tags="travel",
    )
    with seeded_factory() as session:
        session.get(Setting, "backup_retention_days").value = "60"
        session.commit()


# ================= JSON =================

def test_json_export_contains_all_sections(seeded_factory, transaction_service, catalog_service, tmp_path):
    _seed_source(seeded_factory, transaction_service, catalog_service)
    path = tmp_path / "backup.json"
    counts = ExportService(session_factory=seeded_factory).export_json(path)

    assert counts == {"channels": 6, "accounts": 5, "categories": 15, "transactions": 5}
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("channels", "accounts", "categories", "transactions", "settings"):
        assert key in data
    tx = next(t for t in data["transactions"] if t["note"] == "打车费")
    assert isinstance(tx["amount"], str)  # 金额存字符串保精度
    assert tx["channel"] == "稿费收入"
    assert data["settings"]["backup_retention_days"] == "60"


def test_json_export_then_import_roundtrip(seeded_factory, transaction_service, catalog_service, target_factory, tmp_path):
    """需求 §50：Export → Import → 数据一致；重复导入全部跳过、实体不重复。"""
    _seed_source(seeded_factory, transaction_service, catalog_service)
    path = tmp_path / "backup.json"
    ExportService(session_factory=seeded_factory).export_json(path)

    target_import = ImportService(session_factory=target_factory)
    result = target_import.import_json(path)
    assert result.errors == []
    assert result.imported == 5
    assert result.created_channels == 1
    assert result.created_accounts == 1
    assert result.created_categories == 1

    target_tx = TransactionService(session_factory=target_factory)
    records = target_tx.list_transactions()
    assert len(records) == 5
    tx = next(r for r in records if r.note == "打车费")
    assert tx.amount == Decimal("30.00")
    assert tx.channel_name == "稿费收入"
    assert tx.account_name == "证券账户"
    assert tx.category_name == "打车"
    assert tx.tags == "travel"

    target_catalog = CatalogService(session_factory=target_factory)
    account = next(a for a in target_catalog.list_all_accounts() if a.name == "证券账户")
    assert account.initial_balance == Decimal("1000.50")
    channel = next(c for c in target_catalog.list_all_channels() if c.name == "稿费收入")
    assert channel.monthly_amount == Decimal("500")  # 每月固定金额随导出恢复
    with target_factory() as session:
        assert session.get(Setting, "backup_retention_days").value == "60"

    # 重复导入：交易全部跳过，实体复用不重复（需求 §29 的 ID 冲突/重复处理）
    again = target_import.import_json(path)
    assert again.errors == []
    assert again.imported == 0
    assert again.skipped_duplicates == 5
    assert again.created_channels == 0
    assert again.created_accounts == 0
    assert again.created_categories == 0
    assert len(target_catalog.list_all_channels()) == 6  # 5 默认 + 稿费收入


def test_json_import_structure_errors(target_factory, tmp_path):
    target_import = ImportService(session_factory=target_factory)

    # 缺少必要字段
    (tmp_path / "bad.json").write_text(json.dumps({"channels": []}), encoding="utf-8")
    result = target_import.import_json(tmp_path / "bad.json")
    assert result.errors and any("缺少" in e for e in result.errors)

    # 分类类型无效
    (tmp_path / "bad2.json").write_text(
        json.dumps(
            {
                "channels": [], "accounts": [], "transactions": [],
                "categories": [{"name": "X", "type": "transfer"}],
            }
        ),
        encoding="utf-8",
    )
    result = target_import.import_json(tmp_path / "bad2.json")
    assert any("分类类型无效" in e for e in result.errors)

    # 交易引用了不存在的渠道
    (tmp_path / "bad3.json").write_text(
        json.dumps(
            {
                "channels": [], "accounts": [], "categories": [],
                "transactions": [
                    {
                        "type": "expense", "amount": "10.00", "date": "2026-09-18",
                        "channel": "不存在", "account": "Bank", "category": "餐饮",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    result = target_import.import_json(tmp_path / "bad3.json")
    assert any("找不到 Channel = 不存在" in e for e in result.errors)

    # 非 JSON 文件
    (tmp_path / "bad4.json").write_text("这不是 JSON", encoding="utf-8")
    result = target_import.import_json(tmp_path / "bad4.json")
    assert result.errors


def test_json_import_errors_import_nothing(target_factory, tmp_path):
    """有错时整体失败：不写入任何数据。"""
    (tmp_path / "bad.json").write_text(
        json.dumps(
            {
                "channels": [], "accounts": [], "categories": [],
                "transactions": [
                    {
                        "type": "expense", "amount": "abc", "date": "2026-09-18",
                        "channel": "Salary", "account": "Bank", "category": "餐饮",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    target_import = ImportService(session_factory=target_factory)
    result = target_import.import_json(tmp_path / "bad.json")
    assert not result.ok
    assert TransactionService(session_factory=target_factory).list_transactions() == []


# ================= CSV =================

def test_csv_export_then_import_roundtrip(seeded_factory, transaction_service, target_factory, tmp_path):
    seed_official_scenario(seeded_factory, transaction_service)
    path = tmp_path / "transactions.csv"
    ExportService(session_factory=seeded_factory).export_csv(path)

    # BOM + 中文表头
    raw = path.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")

    target_import = ImportService(session_factory=target_factory)
    result = target_import.import_csv(path)
    assert result.errors == []
    assert result.imported == 4

    target_tx = TransactionService(session_factory=target_factory)
    records = target_tx.list_transactions()
    assert len(records) == 4
    lunch = next(r for r in records if r.amount == Decimal("500.00"))
    assert lunch.type == "expense"
    assert lunch.date == date(2026, 9, 10)
    assert lunch.channel_name == "Salary"
    assert lunch.category_name == "餐饮"

    again = target_import.import_csv(path)
    assert again.imported == 0 and again.skipped_duplicates == 4


def test_csv_import_row_errors_reported(seeded_factory, transaction_service, target_factory, tmp_path):
    """需求 §32：第 N 行级错误信息；任何错误 → 整体不导入。"""
    seed_official_scenario(seeded_factory, transaction_service)
    path = tmp_path / "bad.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["日期", "类型", "金额", "渠道", "账户", "分类", "备注", "标签"])
        writer.writerow(["2026-09-18", "expense", "10.00", "Salary", "Bank", "餐饮", "合法行", ""])
        writer.writerow(["2026-09-18", "expense", "abc", "Salary", "Bank", "餐饮", "", ""])
        writer.writerow(["2026-09-18", "expense", "20.00", "Salary2", "Bank", "餐饮", "", ""])
        writer.writerow(["2026-13-99", "expense", "30.00", "Salary", "Bank", "餐饮", "", ""])

    result = ImportService(session_factory=target_factory).import_csv(path)
    assert result.imported == 0  # 整体失败
    assert any("第 3 行" in e and "金额不是有效数字" in e for e in result.errors)
    assert any("第 4 行" in e and "找不到 Channel = Salary2" in e for e in result.errors)
    assert any("第 5 行" in e and "日期格式无效" in e for e in result.errors)
    assert TransactionService(session_factory=target_factory).list_transactions() == []


def test_csv_import_wrong_header(target_factory, tmp_path):
    path = tmp_path / "bad_header.csv"
    path.write_text("日期,金额\n2026-09-18,10\n", encoding="utf-8-sig")
    result = ImportService(session_factory=target_factory).import_csv(path)
    assert result.errors and any("表头" in e for e in result.errors)


def test_csv_import_empty_file(target_factory, tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8-sig")
    result = ImportService(session_factory=target_factory).import_csv(path)
    assert result.errors == ["文件为空"]


def test_csv_import_inactive_channel_warns_not_blocks(seeded_factory, target_factory, tmp_path):
    """放宽规则（用户确认）：引用已停用实体只警告、不阻断导入。"""
    catalog = CatalogService(session_factory=target_factory)
    salary = next(c for c in catalog.list_all_channels() if c.name == "Salary")
    catalog.set_channel_active(salary.id, False)

    path = tmp_path / "inactive.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["日期", "类型", "金额", "渠道", "账户", "分类", "备注", "标签"])
        writer.writerow(["2026-09-18", "expense", "10.00", "Salary", "Bank", "餐饮", "", ""])

    result = ImportService(session_factory=target_factory).import_csv(path)
    assert result.ok
    assert result.imported == 1
    assert any("已停用" in w for w in result.warnings)
    records = TransactionService(session_factory=target_factory).list_transactions()
    assert records[0].channel_name == "Salary"


def test_json_import_is_active_string_false(seeded_factory, target_factory, tmp_path):
    """"false" 字符串正确解析为停用（用户确认的健壮性规则）。"""
    (tmp_path / "active.json").write_text(
        json.dumps(
            {
                "channels": [{"name": "新渠道", "is_active": "false"}],
                "accounts": [], "categories": [], "transactions": [],
            }
        ),
        encoding="utf-8",
    )
    result = ImportService(session_factory=target_factory).import_json(tmp_path / "active.json")
    assert result.ok
    assert result.created_channels == 1
    catalog = CatalogService(session_factory=target_factory)
    created = next(c for c in catalog.list_all_channels() if c.name == "新渠道")
    assert created.is_active is False


def test_json_import_channel_name_not_string_rejected(target_factory, tmp_path):
    (tmp_path / "bad_name.json").write_text(
        json.dumps(
            {
                "channels": [{"name": {"x": 1}}],
                "accounts": [], "categories": [], "transactions": [],
            }
        ),
        encoding="utf-8",
    )
    result = ImportService(session_factory=target_factory).import_json(tmp_path / "bad_name.json")
    assert any("渠道名称无效" in e for e in result.errors)


def test_json_import_is_active_invalid_rejected(target_factory, tmp_path):
    (tmp_path / "bad_active.json").write_text(
        json.dumps(
            {
                "channels": [{"name": "X", "is_active": 123}],
                "accounts": [], "categories": [], "transactions": [],
            }
        ),
        encoding="utf-8",
    )
    result = ImportService(session_factory=target_factory).import_json(tmp_path / "bad_active.json")
    assert any("is_active 无效" in e for e in result.errors)


def test_json_import_transactions_not_list(target_factory, tmp_path):
    (tmp_path / "bad_tx.json").write_text(
        json.dumps(
            {"channels": [], "accounts": [], "categories": [], "transactions": 123}
        ),
        encoding="utf-8",
    )
    result = ImportService(session_factory=target_factory).import_json(tmp_path / "bad_tx.json")
    assert any("transactions 必须是数组" in e for e in result.errors)


def test_csv_import_empty_category_maps_to_other(target_factory, tmp_path):
    """需求 §4.5：CSV 分类列为空 → 自动映射 Other。"""
    path = tmp_path / "no_category.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["日期", "类型", "金额", "渠道", "账户", "分类", "备注", "标签"])
        writer.writerow(["2026-09-18", "expense", "10.00", "Salary", "Bank", "", "无分类", ""])

    result = ImportService(session_factory=target_factory).import_csv(path)
    assert result.ok and result.imported == 1
    records = TransactionService(session_factory=target_factory).list_transactions()
    assert records[0].category_name == "Other"


# ================= XLSX =================

def test_xlsx_export_then_import_roundtrip(seeded_factory, transaction_service, catalog_service, target_factory, tmp_path):
    """需求 §31：多 Sheet 导出 → 导入恢复实体与交易。"""
    _seed_source(seeded_factory, transaction_service, catalog_service)
    path = tmp_path / "backup.xlsx"
    counts = ExportService(session_factory=seeded_factory).export_xlsx(path)
    assert counts["transactions"] == 5

    target_import = ImportService(session_factory=target_factory)
    result = target_import.import_xlsx(path)
    assert result.errors == []
    assert result.imported == 5
    assert result.created_channels == 1
    assert result.created_accounts == 1
    assert result.created_categories == 1

    target_tx = TransactionService(session_factory=target_factory)
    tx = next(r for r in target_tx.list_transactions() if r.note == "打车费")
    assert tx.amount == Decimal("30.00")
    assert tx.channel_name == "稿费收入"
    assert tx.category_name == "打车"

    target_catalog = CatalogService(session_factory=target_factory)
    account = next(a for a in target_catalog.list_all_accounts() if a.name == "证券账户")
    assert account.initial_balance == Decimal("1000.50")
    channel = next(c for c in target_catalog.list_all_channels() if c.name == "稿费收入")
    assert channel.monthly_amount == Decimal("500")  # 每月固定金额随 Sheet 恢复

    again = target_import.import_xlsx(path)
    assert again.imported == 0 and again.skipped_duplicates == 5


def test_xlsx_import_row_errors(seeded_factory, target_factory, tmp_path):
    workbook = Workbook()
    ws = workbook.active
    ws.title = "Transactions"
    ws.append(["日期", "类型", "金额", "渠道", "账户", "分类", "备注", "标签"])
    ws.append(["2026-09-18", "expense", "abc", "Salary", "Bank", "餐饮", "", ""])
    ws.append(["2026-09-18", "expense", "20.00", "Salary2", "Bank", "餐饮", "", ""])
    path = tmp_path / "bad.xlsx"
    workbook.save(path)

    result = ImportService(session_factory=target_factory).import_xlsx(path)
    assert result.imported == 0
    assert any("第 2 行" in e and "金额不是有效数字" in e for e in result.errors)
    assert any("第 3 行" in e and "找不到 Channel = Salary2" in e for e in result.errors)


def test_xlsx_import_missing_sheet(target_factory, tmp_path):
    workbook = Workbook()
    workbook.active.title = "Channels"
    path = tmp_path / "no_tx.xlsx"
    workbook.save(path)
    result = ImportService(session_factory=target_factory).import_xlsx(path)
    assert any("Transactions" in e for e in result.errors)
