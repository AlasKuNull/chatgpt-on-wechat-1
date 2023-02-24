# encoding:utf-8

"""
wechaty channel
Python Wechaty - https://github.com/wechaty/python-wechaty
"""
from datetime import date
import io
import os
import json
import sqlite3
import time
import asyncio
import requests
from typing import Optional, Union
from wechaty_puppet import MessageType, FileBox, ScanStatus  # type: ignore
from wechaty import Wechaty, Contact
from wechaty.user import Message, Room, MiniProgram, UrlLink
from channel.channel import Channel
from common.log import logger
from config import conf


class WechatyChannel(Channel):

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
        asyncio.run(self.main())

    async def main(self):
        config = conf()
        # 使用PadLocal协议 比较稳定(免费web协议 os.environ['WECHATY_PUPPET_SERVICE_ENDPOINT'] = '127.0.0.1:8080')
        token = config.get('wechaty_puppet_service_token')
        os.environ['WECHATY_PUPPET_SERVICE_TOKEN'] = token
        global bot
        bot = Wechaty()

        bot.on('scan', self.on_scan)
        bot.on('login', self.on_login)
        bot.on('message', self.on_message)
        await bot.start()

    async def on_login(self, contact: Contact):
        logger.info('[WX] login user={}'.format(contact))

    async def on_scan(self, status: ScanStatus, qr_code: Optional[str] = None,
                      data: Optional[str] = None):
        contact = self.Contact.load(self.contact_id)
        logger.info('[WX] scan user={}, scan status={}, scan qr_code={}'.format(contact, status.name, qr_code))
        # print(f'user <{contact}> scan status: {status.name} , 'f'qr_code: {qr_code}')

    async def on_message(self, msg: Message):
        """
        listen for message event
        """
        from_contact = msg.talker()  # 获取消息的发送者
        to_contact = msg.to()  # 接收人
        room = msg.room()  # 获取消息来自的群聊. 如果消息不是来自群聊, 则返回None
        from_user_id = from_contact.contact_id
        to_user_id = to_contact.contact_id  # 接收人id
        # other_user_id = msg['User']['UserName']  # 对手方id
        content = msg.text()
        mention_content = await msg.mention_text()  # 返回过滤掉@name后的消息

        match_prefix = self.check_prefix(content, conf().get('single_chat_prefix'))

        if match_prefix is not None and msg.type() == MessageType.MESSAGE_TYPE_TEXT:
            today = date.today()

            # 处理兑换码逻辑
            if mention_content.startswith("兑换码"):
                cdkey = mention_content[3:11]
                data = {"userId": cdkey}
                response = requests.post('https://www.shaobingriyu.com/api/user/openai/ticket/consume',data=data)
                if response.json().code == 0:
                    self.cursor.execute("UPDATE user_request SET request_count = request_count + 3 WHERE user_id=? and date=?", (from_user_id, today))
                    self.conn.commit()
                    appendText = f"兑换码{cdkey}-兑换成功:提问次数 + 3."
                    if room is None:
                        reply_text = conf().get("single_chat_reply_prefix") + appendText
                        await self.send(reply_text, from_user_id)
                    else:
                        reply_text = '@' + from_contact.name + ' ' + appendText
                        await self.send_group(conf().get("group_chat_reply_prefix", "") + reply_text, room.room_id)
                    return
                else:
                    appendText = f"兑换码{cdkey}-兑换失败:今日未激活该验证码或者已兑换."
                    if room is None:
                        reply_text = conf().get("single_chat_reply_prefix") + appendText
                        await self.send(reply_text, from_user_id)
                    else:
                        reply_text = '@' + from_contact.name + ' ' + appendText
                        await self.send_group(conf().get("group_chat_reply_prefix", "") + reply_text, room.room_id)
                    return 

            #判断是否超过次数了
            result = 0
            cursor = self.cursor.execute("select request_count from user_request where user_id = ? and date = ?",(from_user_id,today))
            self.conn.commit()
            if cursor.rowcount > 0:
                result = cursor.fetchone()
    
            if result != 0 and result[0] == 0:
                appendText = "您今日的提问次数已消耗完, 看群公告获取兑换码, 可以增加3次."
                if room is None:
                    reply_text = conf().get("single_chat_reply_prefix") + appendText
                    await self.send(reply_text, from_user_id)
                else:
                    reply_text = '@' + from_contact.name + ' ' + appendText
                    await self.send_group(conf().get("group_chat_reply_prefix", "") + reply_text, room.room_id)
                return

        conversation: Union[Room, Contact] = from_contact if room is None else room

        if room is None and msg.type() == MessageType.MESSAGE_TYPE_TEXT:
            if not msg.is_self() and match_prefix is not None:
                # 好友向自己发送消息
                if match_prefix != '':
                    str_list = content.split(match_prefix, 1)
                    if len(str_list) == 2:
                        content = str_list[1].strip()

                img_match_prefix = self.check_prefix(content, conf().get('image_create_prefix'))
                if img_match_prefix:
                    content = content.split(img_match_prefix, 1)[1].strip()
                    await self._do_send_img(content, from_user_id)
                else:
                    await self._do_send(content, from_user_id)
                self.updateUserCount(from_user_id)

            elif msg.is_self() and match_prefix:
                # 自己给好友发送消息
                str_list = content.split(match_prefix, 1)
                if len(str_list) == 2:
                    content = str_list[1].strip()
                img_match_prefix = self.check_prefix(content, conf().get('image_create_prefix'))
                if img_match_prefix:
                    content = content.split(img_match_prefix, 1)[1].strip()
                    await self._do_send_img(content, to_user_id)
                else:
                    await self._do_send(content, to_user_id)

        elif room and msg.type() == MessageType.MESSAGE_TYPE_TEXT:
            # 群组&文本消息
            room_id = room.room_id
            room_name = await room.topic()
            from_user_id = from_contact.contact_id
            from_user_name = from_contact.name
            is_at = await msg.mention_self()
            content = mention_content
            config = conf()
            match_prefix = (is_at and not config.get("group_at_off", False)) \
                           or self.check_prefix(content, config.get('group_chat_prefix')) \
                           or self.check_contain(content, config.get('group_chat_keyword'))
            if ('ALL_GROUP' in config.get('group_name_white_list') or room_name in config.get(
                    'group_name_white_list') or self.check_contain(room_name, config.get(
                'group_name_keyword_white_list'))) and match_prefix:
                img_match_prefix = self.check_prefix(content, conf().get('image_create_prefix'))
                if img_match_prefix:
                    content = content.split(img_match_prefix, 1)[1].strip()
                    await self._do_send_group_img(content, room_id)
                else:
                    await self._do_send_group(content, room_id, from_user_id, from_user_name)
                self.updateUserCount(from_user_id)

    def updateUserCount(self,from_user_id):
        today = date.today()
        try:
            self.cursor.execute("INSERT INTO user_request (user_id, request_count, date) VALUES (?, ?, ?)", (from_user_id, 0, today))
            self.conn.commit()
        except Exception as e:
            self.cursor.execute("UPDATE user_request SET request_count = request_count - 1 WHERE user_id=? and date=?", (from_user_id, today))
            self.conn.commit()

    async def send(self, message: Union[str, Message, FileBox, Contact, UrlLink, MiniProgram], receiver):
        logger.info('[WX] sendMsg={}, receiver={}'.format(message, receiver))
        if receiver:
            contact = await bot.Contact.find(receiver)
            await contact.say(message)

    async def send_group(self, message: Union[str, Message, FileBox, Contact, UrlLink, MiniProgram], receiver):
        logger.info('[WX] sendMsg={}, receiver={}'.format(message, receiver))
        if receiver:
            room = await bot.Room.find(receiver)
            await room.say(message)

    async def _do_send(self, query, reply_user_id):
        try:
            if not query:
                return
            context = dict()
            context['from_user_id'] = reply_user_id
            reply_text = super().build_reply_content(query, context)
            if reply_text:
                await self.send(conf().get("single_chat_reply_prefix") + reply_text, reply_user_id)
        except Exception as e:
            logger.exception(e)

    async def _do_send_img(self, query, reply_user_id):
        try:
            if not query:
                return
            context = dict()
            context['type'] = 'IMAGE_CREATE'
            img_url = super().build_reply_content(query, context)
            if not img_url:
                return
            # 图片下载
            # pic_res = requests.get(img_url, stream=True)
            # image_storage = io.BytesIO()
            # for block in pic_res.iter_content(1024):
            #     image_storage.write(block)
            # image_storage.seek(0)

            # 图片发送
            logger.info('[WX] sendImage, receiver={}'.format(reply_user_id))
            t = int(time.time())
            file_box = FileBox.from_url(url=img_url, name=str(t) + '.png')
            await self.send(file_box, reply_user_id)
        except Exception as e:
            logger.exception(e)

    async def _do_send_group(self, query, group_id, group_user_id, group_user_name):
        if not query:
            return
        context = dict()
        context['from_user_id'] = str(group_id) + '-' + str(group_user_id)
        reply_text = super().build_reply_content(query, context)
        if reply_text:
            reply_text = '@' + group_user_name + ' ' + reply_text.strip()
            await self.send_group(conf().get("group_chat_reply_prefix", "") + reply_text, group_id)

    async def _do_send_group_img(self, query, reply_room_id):
        try:
            if not query:
                return
            context = dict()
            context['type'] = 'IMAGE_CREATE'
            img_url = super().build_reply_content(query, context)
            if not img_url:
                return
            # 图片发送
            logger.info('[WX] sendImage, receiver={}'.format(reply_room_id))
            t = int(time.time())
            file_box = FileBox.from_url(url=img_url, name=str(t) + '.png')
            await self.send_group(file_box, reply_room_id)
        except Exception as e:
            logger.exception(e)

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
