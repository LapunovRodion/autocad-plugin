#!/usr/bin/env python3
"""
Заливка исходных дампов в локальную Oracle XE и проверка результата.

Почему не sqlplus: три строки в GEOMETRY.sql длиннее 2499 символов
(максимум 2858 — длинные POLYGON в GEOWKT), а SQL*Plus отвергает такие
строки с SP2-0027 и продолжает работу. Потеря прошла бы молча.
python-oracledb в thin-режиме этого ограничения не имеет и не требует
Instant Client — это чистый Python.

Скрипт идемпотентен: таблицы дропаются перед загрузкой, потому что сами
дампы начинаются с CREATE TABLE.

Использование:
    ./infra/load-dumps.py            залить и проверить
    ./infra/load-dumps.py --check    только проверки
"""

import os
import re
import sys
import time

import oracledb

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DSN = os.environ.get("ORACLE_DSN", "localhost:1521/XEPDB1")
USER = os.environ.get("APP_USER", "TASK")
PASSWORD = os.environ.get("APP_USER_PASSWORD", "task")

# Порядок произволен: внешних ключей между таблицами нет.
DUMPS = ["GPO", "PROBA", "PARAM", "GEOMETRY"]

# Выверено по исходным .sql-файлам.
EXPECTED_ROWS = {"GEOMETRY": 5228, "GPO": 182, "PROBA": 1331, "PARAM": 1316}


def connect(timeout=300):
    """Подключение с ожиданием: контейнер может ещё подниматься."""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            return oracledb.connect(user=USER, password=PASSWORD, dsn=DSN)
        except oracledb.Error as exc:
            last = exc
            time.sleep(3)
    print(f"Не удалось подключиться к {DSN} за {timeout} с: {last}", file=sys.stderr)
    sys.exit(1)


def statements(path):
    """Разбор дампа на отдельные команды.

    Разделитель — ';' в конце строки. Внутри строковых литералов дампа
    точка с запятой не встречается (проверено), поэтому разбиение
    однозначно. COMMIT пропускаем: транзакцией управляем сами.
    """
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    for chunk in re.split(r";\s*\n", text):
        chunk = chunk.strip()
        if chunk and not chunk.upper().startswith("COMMIT"):
            yield chunk


def drop_tables(cur):
    for table in EXPECTED_ROWS:
        try:
            cur.execute(f"DROP TABLE {table} PURGE")
        except oracledb.DatabaseError as exc:
            # ORA-00942: таблицы нет — нормально при первом запуске.
            if exc.args[0].code != 942:
                raise


def load(conn):
    cur = conn.cursor()
    drop_tables(cur)
    conn.commit()

    for name in DUMPS:
        path = os.path.join(ROOT, f"{name}.sql")
        count = 0
        started = time.time()
        for sql in statements(path):
            cur.execute(sql)
            count += 1
        conn.commit()
        print(f"  {name:<9} {count - 1:>5} строк за {time.time() - started:.1f} с")


def scalar(cur, sql):
    cur.execute(sql)
    return cur.fetchone()[0]


def check(conn):
    """Проверки. Возвращает True, если всё сошлось."""
    cur = conn.cursor()
    ok = True

    def report(label, actual, expected):
        nonlocal ok
        good = actual == expected
        ok = ok and good
        print(f"  [{'ok' if good else 'ОШИБКА'}] {label:<46} {actual} (ожидалось {expected})")

    print("\nЧисло строк:")
    for table, expected in EXPECTED_ROWS.items():
        report(table, scalar(cur, f"SELECT COUNT(*) FROM {table}"), expected)

    print("\nЦелостность:")
    # Именно DISTINCT: 'р112' входит в десятку проб с двумя записями в
    # PARAM, поэтому COUNT(*) здесь дал бы 2 и ничего не сказал о кодировке.
    report(
        "кириллица в PROBA_NUM ('р112')",
        scalar(cur, "SELECT COUNT(DISTINCT PROBA_NUM) FROM PARAM WHERE PROBA_NUM = 'р112'"),
        1,
    )
    report(
        "пункты со связью PROBA.ID -> GPO.ID",
        scalar(cur, "SELECT COUNT(DISTINCT p.ID) FROM PROBA p JOIN GPO g ON p.ID = g.ID"),
        177,
    )
    report(
        "пробы с химией PARAM -> PROBA",
        scalar(
            cur,
            "SELECT COUNT(DISTINCT a.PROBA_NUM) FROM PARAM a "
            "JOIN PROBA p ON a.PROBA_NUM = p.PROBA_NUM",
        ),
        1306,
    )
    report(
        "пробы с конфликтующими значениями KCl",
        scalar(
            cur,
            "SELECT COUNT(*) FROM (SELECT PROBA_NUM FROM PARAM "
            "GROUP BY PROBA_NUM HAVING COUNT(*) > 1)",
        ),
        10,
    )
    report(
        "точки в слое пунктов опробования",
        scalar(
            cur,
            "SELECT COUNT(*) FROM GEOMETRY "
            "WHERE SUBLAYERGUID = '92E19C56-1E9B-4453-97E9-C881C78CF893'",
        ),
        182,
    )
    report(
        "самый длинный GEOWKT (символов)",
        scalar(cur, "SELECT MAX(LENGTH(GEOWKT)) FROM GEOMETRY"),
        2698,
    )

    return ok


def main():
    only_check = "--check" in sys.argv
    conn = connect()
    try:
        if not only_check:
            print(f"Загрузка дампов в {USER}@{DSN}:")
            load(conn)
        if not check(conn):
            # Без flush сообщение из stderr обгоняет буферизованный stdout
            # и оказывается в выводе раньше самих проверок.
            sys.stdout.flush()
            print("\nПроверки не пройдены.", file=sys.stderr)
            sys.exit(1)
        print("\nВсе проверки пройдены.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
