# encoding:utf-8

"""
wechat channel
"""
from datetime import date
import sqlite3
import itchat
import json
from itchat.content import *
from channel.channel import Channel
from concurrent.futures import ThreadPoolExecutor
from common.log import logger
from config import conf
import requests
import io

thread_pool = ThreadPoolExecutor(max_workers=8)


@itchat.msg_register(TEXT)
def handler_single_msg(msg):
    WechatChannel().handle(msg)
    return None


@itchat.msg_register(TEXT, isGroupChat=True)
def handler_group_msg(msg):
    WechatChannel().handle_group(msg)
    return None


class WechatChannel(Channel):

    conn = None
    cursor = None

    def __init__(self):
        self.conn = sqlite3.connect('database.db', check_same_thread=False)
        self.cursor = self.conn.cursor()

        self.cursor.execute("""
        create table if not exists `user_request`(
            `user_id` varchat(50) NOT NULL,
            `date` date NOT NULL,
            `request_count` int(11) NOT NULL,
            PRIMARY KEY (`user_id`,`date`)
        )
        """)
        self.conn.commit()
        pass

    def startup(self):
        # login by scan QRCode
        itchat.auto_login(enableCmdQR=2)

        # start message listener
        itchat.run()

    def handle(self, msg):
        logger.debug("[WX]receive msg: " + json.dumps(msg, ensure_ascii=False))
        from_user_id = msg['FromUserName']
        to_user_id = msg['ToUserName']              # 接收人id
        other_user_id = msg['User']['UserName']     # 对手方id
        content = msg['Text']
        today = date.today()

        codeContent = content.replace(conf().get('group_chat_prefix'),"") 
        # 处理兑换码逻辑
        if codeContent.startswith("兑换码"):
            cdkey = codeContent[3:11]
            data = {"userId": cdkey}
            response = requests.post('https://www.shaobingriyu.com/api/user/openai/ticket/consume',data=data)
            if response.json().code == 0:
                self.cursor.execute("UPDATE user_request SET request_count = request_count + 3 WHERE user_id=? and date=?", (from_user_id, today))
                self.conn.commit()
                return [f"兑换码{cdkey}-兑换成功:提问次数 + 3."]
            else:
                return [f"兑换码{cdkey}-兑换失败:今日未激活该验证码或者已兑换."]

        #判断是否超过次数了
        result = 0
        cursor = self.cursor.execute("select request_count from user_request where user_id = ? and date = ?",(from_user_id,today))
        self.conn.commit()
        if cursor.rowcount > 0:
            result = cursor.fetchone()
    
        if result != 0 and result[0] == 0:
            return ["您今日的提问次数已消耗完, 看群公告获取兑换码, 可以增加3次."]
        
        match_prefix = self.check_prefix(content, conf().get('single_chat_prefix'))
        if from_user_id == other_user_id and match_prefix is not None:
            # 好友向自己发送消息
            if match_prefix != '':
                str_list = content.split(match_prefix, 1)
                if len(str_list) == 2:
                    content = str_list[1].strip()

            img_match_prefix = self.check_prefix(content, conf().get('image_create_prefix'))
            if img_match_prefix:
                content = content.split(img_match_prefix, 1)[1].strip()
                thread_pool.submit(self._do_send_img, content, from_user_id)
                self.updateUserCount(result,from_user_id,today)

            else:
                thread_pool.submit(self._do_send, content, from_user_id)
                self.updateUserCount(result,from_user_id,today)

        elif to_user_id == other_user_id and match_prefix:
            # 自己给好友发送消息
            str_list = content.split(match_prefix, 1)
            if len(str_list) == 2:
                content = str_list[1].strip()
            img_match_prefix = self.check_prefix(content, conf().get('image_create_prefix'))
            if img_match_prefix:
                content = content.split(img_match_prefix, 1)[1].strip()
                thread_pool.submit(self._do_send_img, content, to_user_id)
                self.updateUserCount(result,from_user_id,today)

            else:
                thread_pool.submit(self._do_send, content, to_user_id)
                self.updateUserCount(result,from_user_id,today)

    def updateUserCount(self,result,from_user_id,today):
        if result == 0:
            self.cursor.execute("INSERT INTO user_request (user_id, request_count, date) VALUES (?, ?, ?)", (from_user_id, 0, today))
            self.conn.commit()
        else:
            self.cursor.execute("UPDATE user_request SET request_count = request_count - 1 WHERE user_id=? and date=?", (from_user_id, today))
            self.conn.commit()

    def handle_group(self, msg):
        logger.debug("[WX]receive group msg: " + json.dumps(msg, ensure_ascii=False))
        group_name = msg['User'].get('NickName', None)
        group_id = msg['User'].get('UserName', None)
        from_user_id = msg['ActualUserName']
        if not group_name:
            return ""
        origin_content = msg['Content']
        content = msg['Content']

        today = date.today()

        # 处理兑换码逻辑
        if content.startswith("兑换码"):
            cdkey = content[3:11]
            data = {"userId": cdkey}
            response = requests.post('https://www.shaobingriyu.com/api/user/openai/ticket/consume',data=data)
            if response.json().code == 0:
                self.cursor.execute("UPDATE user_request SET request_count = request_count + 3 WHERE user_id=? and date=?", (from_user_id, today))
                self.conn.commit()
                return [f"兑换码{cdkey}-兑换成功:提问次数 + 3."]
            else:
                return [f"兑换码{cdkey}-兑换失败:今日未激活该验证码或者已兑换."]

        #判断是否超过次数了
        result = 0
        cursor = self.cursor.execute("select request_count from user_request where user_id = ? and date = ?",(from_user_id,today))
        self.conn.commit()
        if cursor.rowcount > 0:
            result = cursor.fetchone()
    
        if result != 0 and result[0] == 0:
            return ["您今日的提问次数已消耗完, 看群公告获取兑换码, 可以增加3次."]

        content_list = content.split(' ', 1)
        context_special_list = content.split('\u2005', 1)
        if len(context_special_list) == 2:
            content = context_special_list[1]
        elif len(content_list) == 2:
            content = content_list[1]

        config = conf()
        match_prefix = (msg['IsAt'] and not config.get("group_at_off", False)) or self.check_prefix(origin_content, config.get('group_chat_prefix')) \
                       or self.check_contain(origin_content, config.get('group_chat_keyword'))
        if ('ALL_GROUP' in config.get('group_name_white_list') or group_name in config.get('group_name_white_list') or self.check_contain(group_name, config.get('group_name_keyword_white_list'))) and match_prefix:
            img_match_prefix = self.check_prefix(content, conf().get('image_create_prefix'))
            if img_match_prefix:
                content = content.split(img_match_prefix, 1)[1].strip()
                thread_pool.submit(self._do_send_img, content, group_id)
                self.updateUserCount(result,from_user_id,today)
            else:
                thread_pool.submit(self._do_send_group, content, msg)
                self.updateUserCount(result,from_user_id,today)

    def send(self, msg, receiver):
        logger.info('[WX] sendMsg={}, receiver={}'.format(msg, receiver))
        itchat.send(msg, toUserName=receiver)

    def _do_send(self, query, reply_user_id):
        try:
            if not query:
                return
            context = dict()
            context['from_user_id'] = reply_user_id
            reply_text = super().build_reply_content(query, context)
            if reply_text:
                self.send(conf().get("single_chat_reply_prefix") + reply_text, reply_user_id)
        except Exception as e:
            logger.exception(e)

    def _do_send_img(self, query, reply_user_id):
        try:
            if not query:
                return
            context = dict()
            context['type'] = 'IMAGE_CREATE'
            img_url = super().build_reply_content(query, context)
            if not img_url:
                return

            # 图片下载
            pic_res = requests.get(img_url, stream=True)
            image_storage = io.BytesIO()
            for block in pic_res.iter_content(1024):
                image_storage.write(block)
            image_storage.seek(0)

            # 图片发送
            logger.info('[WX] sendImage, receiver={}'.format(reply_user_id))
            itchat.send_image(image_storage, reply_user_id)
        except Exception as e:
            logger.exception(e)

    def _do_send_group(self, query, msg):
        if not query:
            return
        context = dict()
        context['from_user_id'] = msg['ActualUserName']
        reply_text = super().build_reply_content(query, context)
        if reply_text:
            reply_text = '@' + msg['ActualNickName'] + ' ' + reply_text.strip()
            self.send(conf().get("group_chat_reply_prefix", "") + reply_text, msg['User']['UserName'])


    def check_prefix(self, content, prefix_list):
        for prefix in prefix_list:
            if content.startswith(prefix):
                return prefix
        return None


    def check_contain(self, content, keyword_list):
        if not keyword_list:
            return None
        for ky in keyword_list:
            if content.find(ky) != -1:
                return True
        return None
