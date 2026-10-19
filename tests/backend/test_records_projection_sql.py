"""Actual isolated PostgreSQL rejection/compatibility; no production connection."""

import json
import os
from pathlib import Path

import httpx
import pytest
from app.contracts.dto import RegimenVersionDTO

from .grouped_records_browser_server import build_grouped_records_app
from .records_browser_server import OWNER
from .test_conversation_threads_sql import db as db
from .test_record_history_adapter import adapter

pytestmark = pytest.mark.skipif(not os.environ.get("THREADS_TEST_DSN"), reason="isolated local PostgreSQL required")


def test_records_select_contract_against_actual_pre027_projection(db):
    from psycopg import errors, sql
    from psycopg.types.json import Jsonb

    root = build_grouped_records_app().state.container
    for table, values in [
        ("regimen_versions", root.store.regimens.values()),
        ("patient_medications", root.store.medications.values()),
    ]:
        columns = [
            row[0]
            for row in db.execute(
                "select column_name from information_schema.columns "
                "where table_schema='public' and table_name=%s order by ordinal_position",
                (table,),
            )
            if row[0] != "patient_edited"
        ]
        rows = [row.model_dump(mode="json") for row in values]
        db.execute(
            sql.SQL(
                "create temporary view {} as select {} from jsonb_array_elements({}::jsonb) entry "
                "cross join lateral jsonb_populate_record(null::public.{},entry) value"
            ).format(
                sql.Identifier("rt_" + table),
                sql.SQL(",").join(sql.SQL("value.{}").format(sql.Identifier(column)) for column in columns),
                sql.Literal(Jsonb(rows)),
                sql.Identifier(table),
            )
        )
    with pytest.raises(errors.UndefinedColumn) as failure, db.transaction():
        db.execute(
            sql.SQL("select {} from rt_regimen_versions").format(
                sql.SQL(",").join(map(sql.Identifier, RegimenVersionDTO.model_fields))
            )
        )
    assert failure.value.sqlstate == "42703"

    def handler(request):
        table = request.url.path.rsplit("/", 1)[-1]
        assert table in {"regimen_versions", "patient_medications"}
        assert request.url.params["select"] == "*"
        patient = request.url.params["patient_id"].removeprefix("eq.")
        total = db.execute(
            sql.SQL("select count(*) from {} where patient_id=%s").format(sql.Identifier("rt_" + table)), (patient,)
        ).fetchone()[0]
        cursor = db.execute(
            sql.SQL("select * from {} where patient_id=%s order by id limit %s offset %s").format(
                sql.Identifier("rt_" + table)
            ),
            (patient, int(request.url.params["limit"]), int(request.url.params["offset"])),
        )
        keys = [column.name for column in cursor.description]
        rows = [dict(zip(keys, row, strict=True)) for row in cursor.fetchall()]
        return httpx.Response(
            200, json=json.loads(json.dumps(rows, default=str)), headers={"Content-Range": f"0-{len(rows) - 1}/{total}"}
        )

    reader = adapter(handler)
    plans = reader.plans(OWNER)
    medicines = reader.medications(OWNER)
    assert len(plans) == len(root.store.regimens) and len(medicines) == len(root.store.medications)
    assert all(not row.patient_edited for row in plans)
    Path("outputs/records-42703-sql.json").write_text(
        json.dumps(
            {
                "environment": "isolated local PostgreSQL; exact pre027-column view over migrated record types; "
                "controlled HTTP translation, not live Supabase",
                "legacy_select_sqlstate": failure.value.sqlstate,
                "fixed_plan_rows": len(plans),
                "fixed_medication_rows": len(medicines),
                "production_migration": False,
            },
            indent=2,
        ),
        encoding="utf8",
    )
