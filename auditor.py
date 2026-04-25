import sqlite3
from datetime import datetime

class Auditor:
    def __init__(self):
        self.db = sqlite3.connect('audit.db')
        self.cursor = self.db.cursor()
        self.cursor.execute('CREATE TABLE IF NOT EXISTS signals (time TEXT, tf TEXT, res TEXT)')
        self.db.commit()

    def log_result(self, tf, res):
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.cursor.execute("INSERT INTO signals VALUES (?,?,?)", (now, tf, res))
        self.db.commit()
        