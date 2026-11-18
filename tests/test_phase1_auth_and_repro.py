"""
tests/test_phase1_auth_and_repro.py — Unit tests for Phase 1:
- Database drift separation (eval.db vs app.db) & SHA-256 tamper protection
- Authentication (Argon2id / bcrypt hashing, session expiry, 5-attempt lockout, RBAC for astronaut vs flight_surgeon)
"""
import json
import os
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import ai_health_model as aim
import blind_test as bt
import generate_data as gd
import health_engine as he


def test_eval_and_app_databases_exist_and_hash_matches():
    assert os.path.exists(aim.EVAL_DB_PATH), "Frozen evaluation database must exist"
    assert os.path.exists(aim.EVAL_HASH_PATH), "Frozen evaluation SHA-256 manifest must exist"
    assert os.path.exists(aim.APP_DB_PATH), "Working application database must exist"
    digest = aim.verify_eval_db_hash()
    assert len(digest) == 64


def test_blind_test_refuses_tampered_eval_db(tmp_path):
    fake_db = tmp_path / "tampered_eval.db"
    fake_hash = tmp_path / "tampered_eval.db.sha256"
    shutil.copy2(aim.EVAL_DB_PATH, fake_db)
    shutil.copy2(aim.EVAL_HASH_PATH, fake_hash)

    # Modify a single row inside tampered_eval.db
    con = sqlite3.connect(str(fake_db))
    con.execute("UPDATE astronaut_profile SET age = 99 WHERE astronaut_id = 'A001'")
    con.commit()
    con.close()

    with pytest.raises(RuntimeError, match="SHA-256 HASH MISMATCH"):
        aim.verify_eval_db_hash(str(fake_db), str(fake_hash))

    with pytest.raises(RuntimeError, match="SHA-256 HASH MISMATCH"):
        bt.run(eval_db_path=str(fake_db))


def test_frontend_writeback_touches_only_app_db_not_eval_db():
    sha_before = gd.compute_sha256(aim.EVAL_DB_PATH)
    res = he.complete_task("A006", "resistance_training", 65.0)
    assert res["ok"] is True
    sha_after = gd.compute_sha256(aim.EVAL_DB_PATH)
    assert sha_before == sha_after, "Frontend write-back must NEVER mutate the frozen eval database"


def test_passwords_are_hashed_never_plaintext():
    with open(he.AUTH_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    con = sqlite3.connect(he.DB_PATH)
    rows = con.execute("SELECT user_id, role, password_hash FROM auth_users").fetchall()
    con.close()
    assert len(rows) >= 202
    for uid, role, pw_hash in rows:
        assert pw_hash.startswith("$argon2id$") or pw_hash.startswith("$2b$")
        for fs in cfg["flight_surgeons"]:
            assert fs["credential"] not in pw_hash
        for ov in cfg["astronaut_credential_rule"]["overrides"].values():
            assert ov not in pw_hash


def test_auth_login_lockout_expiry_and_rbac():
    with open(he.AUTH_CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    a001_pin = cfg["astronaut_credential_rule"]["overrides"]["A001"]
    a002_pin = cfg["astronaut_credential_rule"]["format"].format(astronaut_id="A002")
    fs_cred = cfg["flight_surgeons"][0]["credential"]

    t0 = datetime(2030, 6, 30, 12, 0, 0, tzinfo=timezone.utc)

    # 1. Missing password fails
    r_missing = he.login("A001")
    assert r_missing["ok"] is False

    # 2. 5 failed attempts on A002 trigger lockout
    con = sqlite3.connect(he.DB_PATH)
    con.execute("UPDATE auth_users SET failed_attempts = 0, locked_until = NULL WHERE user_id IN ('A001', 'A002', 'FS001')")
    con.commit()
    con.close()

    for attempt in range(1, 6):
        r_bad = he.login("A002", "WRONG-PIN", now=t0)
        assert r_bad["ok"] is False
        assert f"{attempt}/5" in r_bad["error"]

    # 6th attempt with CORRECT PIN while locked must still be rejected
    r_locked = he.login("A002", a002_pin, now=t0 + timedelta(seconds=60))
    assert r_locked["ok"] is False
    assert "locked" in r_locked["error"].lower()

    # After lockout expires (15+ minutes later), login with correct PIN succeeds
    r_unlocked = he.login("A002", a002_pin, now=t0 + timedelta(seconds=901))
    assert r_unlocked["ok"] is True
    assert r_unlocked["role"] == "astronaut"

    # 3. Astronaut login and session token RBAC
    r_a1 = he.login("A001", a001_pin, now=t0)
    assert r_a1["ok"] is True
    tok_a1 = r_a1["session_token"]

    # Astronaut A001 can read own profile
    prof_self = he.get_profile("A001", session_token=tok_a1, now=t0 + timedelta(seconds=10))
    assert prof_self["ok"] is True

    # Astronaut A001 CANNOT read A002's profile or list all astronauts
    prof_other = he.get_profile("A002", session_token=tok_a1, now=t0 + timedelta(seconds=10))
    assert prof_other["ok"] is False
    assert "access denied" in prof_other["error"].lower()

    crew_list_a1 = he.list_all_astronauts(tok_a1, now=t0 + timedelta(seconds=10))
    assert crew_list_a1["ok"] is False

    # 4. Session expiry
    expired_check = he.get_profile("A001", session_token=tok_a1, now=t0 + timedelta(seconds=3601))
    assert expired_check["ok"] is False
    assert "expired" in expired_check["error"].lower()

    # 5. Flight Surgeon role can access any astronaut and list all astronauts
    r_fs = he.login("FS001", fs_cred, now=t0)
    assert r_fs["ok"] is True
    assert r_fs["role"] == "flight_surgeon"
    tok_fs = r_fs["session_token"]

    prof_a2_by_fs = he.get_profile("A002", session_token=tok_fs, now=t0 + timedelta(seconds=30))
    assert prof_a2_by_fs["ok"] is True
    crew_by_fs = he.list_all_astronauts(tok_fs, now=t0 + timedelta(seconds=30))
    assert crew_by_fs["ok"] is True

    # Frozen eval.db always has the 200 synthetic cohort members; app.db has >= 200 (may include user signups)
    with sqlite3.connect(aim.EVAL_DB_PATH) as eval_con:
        eval_count = eval_con.execute("SELECT COUNT(*) FROM astronaut_profile").fetchone()[0]
    with sqlite3.connect(aim.APP_DB_PATH) as app_con:
        app_count = app_con.execute("SELECT COUNT(*) FROM astronaut_profile").fetchone()[0]
    assert eval_count == 200
    assert app_count >= 200
    assert crew_by_fs["n_astronauts"] == app_count
