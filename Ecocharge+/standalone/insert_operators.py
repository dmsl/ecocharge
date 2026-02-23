import sqlite3
import bcrypt
import random

DATABASE_FILE = "MicroGrid.db"  # Adjust as needed

def create_fake_operators(n=100):
    conn = sqlite3.connect(DATABASE_FILE)
    cursor = conn.cursor()

    operator_ids = []

    for i in range(n):
        name = f"Operator{i}"
        surname = f"Operator_surname{i}"
        email = f"operator{i}@email.com"
        password = f"pass{i}"
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        cursor.execute('''
            INSERT INTO User (Name, Surname, Email, Password, Role)
            VALUES (?, ?, ?, ?, ?)
        ''', (name, surname, email, hashed, "Operator"))

        operator_ids.append(cursor.lastrowid)

    conn.commit()
    return operator_ids, conn, cursor

def assign_microgrids_balanced(operator_ids, cursor, conn):
    cursor.execute("SELECT GroupID FROM MicroGridDetails")
    group_ids = [row[0] for row in cursor.fetchall()]
    random.shuffle(group_ids)

    operator_assignments = []

    i = 0
    while group_ids:
        num_to_assign = random.choice([1, 2])  # Assign 1 or 2 microgrids
        if not group_ids:
            break
        assigned = group_ids[:num_to_assign]
        group_ids = group_ids[num_to_assign:]

        if i >= len(operator_ids):
            break  # all operators used

        for gid in assigned:
            operator_assignments.append((operator_ids[i], gid))
        i += 1

    for operator_id, group_id in operator_assignments:
        cursor.execute("""
            UPDATE MicroGridDetails SET OperatorUserID = ? WHERE GroupID = ?
        """, (operator_id, group_id))

    conn.commit()
    conn.close()

# Run it
fake_ids, conn, cursor = create_fake_operators(100)
assign_microgrids_balanced(fake_ids, cursor, conn)

print("Done: Each fake operator assigned to 1–2 microgrids.")