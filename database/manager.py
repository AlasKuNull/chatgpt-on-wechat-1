import hashlib
import json
import logging
import time
from sqlite3 import Cursor

import sqlite3


# 数据库管理
# 为其他模块提供数据库操作接口
class DatabaseManager:
    conn = None
    cursor = None

    def __init__(self):

        self.reconnect()

    # 连接到数据库文件
    def reconnect(self):
        self.conn = sqlite3.connect('database.db', check_same_thread=False)
        self.cursor = self.conn.cursor()

    def close(self):
        self.conn.close()

    def execute(self, *args, **kwargs) -> Cursor:
        # logging.debug('SQL: {}'.format(sql))
        c = self.cursor.execute(*args, **kwargs)
        self.conn.commit()
        return c

    # 初始化数据库的函数
    def initialize_database(self):
        self.execute("""
        create table if not exists `user_request`(
            `user_id` varchat(50) NOT NULL,
            `date` date NOT NULL,
            `request_count` int(11) NOT NULL,
            PRIMARY KEY (`user_id`,`date`)
        )
        """)
        print('Database initialized.')
