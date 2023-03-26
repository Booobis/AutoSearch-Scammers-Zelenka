from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By

import aiosqlite
import os
import time
import config
import asyncio
from loguru import logger


async def create_database():
    async with aiosqlite.connect("user_data.db") as db:
        await db.execute(
            "CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY)"
        )
        await db.execute(
            "CREATE TABLE IF NOT EXISTS banned_users (id TEXT, lenban INT, ban_reasons TEXT, lenbans INT, lenunbans INT, bans TEXT)"
        )
        await db.commit()


class ZelenkaScraper:
    def __init__(self):
        chrome_driver_path = os.path.join(os.getcwd(), "chromedriver.exe")
        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument("--headless")
        self.driver = webdriver.Chrome(options=chrome_options)
        service = Service(executable_path=chrome_driver_path)
        self.driver = webdriver.Chrome(service=service)
        self.users_data = {}
        self.banned_users = {}

        self.total_banned_users = 0
        self.total_unbanned_users = 0

    async def scrape_users(self, url):
        self.driver.get(url)
        self.driver.add_cookie({'name': 'xf_user', 'value': config.xf_user})
        self.driver.add_cookie({'name': 'xf_session', 'value': config.xf_session})
        self.driver.add_cookie({'name': 'xf_tfa_trust', 'value': config.xf_tfa_trust})
        self.driver.refresh()
        time.sleep(2)
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        user_links = [link['href'] for link in soup.select('a.username') if
                      link.find_parent('ol').get('class', [''])[0] != 'memberList']

        user_shared_ips_links = ['https://zelenka.guru/' + link + 'shared-ips/' for link in user_links]
        for shared_ips_link in user_shared_ips_links:
            self.shared_ips_link = shared_ips_link
            try:
                self.driver.get(shared_ips_link)
            except Exception as e:
                logger.error(f'link: {shared_ips_link}, Err: {e}')
            await self.scrape_shared_ips()

    async def scrape_online_users(self):

        self.driver.get('https://zelenka.guru/online/?type=registered')
        self.driver.add_cookie({'name': 'xf_user', 'value': config.xf_user})
        self.driver.add_cookie({'name': 'xf_session', 'value': config.xf_session})
        self.driver.add_cookie({'name': 'xf_tfa_trust', 'value': config.xf_tfa_trust})
        self.driver.refresh()
        time.sleep(2)
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        user_links = [link['href'] for link in soup.select('a.username')]
        return user_links

    async def scrape_banned_users(self):
        async with aiosqlite.connect("user_data.db") as db:
            for user_id, data in self.users_data.items():
                shared_ips, banned_ips = data
                banned_percentage = (banned_ips / shared_ips) * 100 if shared_ips > 0 else 0
                logger.info(
                    f"User ID: {user_id}, количество банов в общих: {banned_ips}, общее количество IP-адресов: {shared_ips}, процент забаненных: {banned_percentage:.2f}%")
                await asyncio.sleep(2)
                try:
                    await db.execute("INSERT INTO banned_users VALUES (?, ?)", (user_id, ""))
                except Exception as e:
                    logger.error(e)
                    continue
                await db.commit()
                logger.info(
                    '\n\nПосле всего вы можете выгрузить всех подозреваемых в txt построчно через скрипт withdraw.py')

    async def scrape_shared_ips(self):
        soup = BeautifulSoup(self.driver.page_source, 'html.parser')
        ban_reasons = soup.find('div', class_='banReason')
        user_id = self.shared_ips_link.split('/')[-3]
        shared_ips_count = len(user_id)

        if ban_reasons:
            bans = [ban_reasons.text.strip()]
            lenbans = len(ban_reasons)
            async with aiosqlite.connect("user_data.db") as db:
                await db.execute("INSERT OR IGNORE INTO banned_users VALUES (?, ?, ?, ?, ?, ?)", (
                    user_id, len(ban_reasons), ", ".join(bans), abs(lenbans), abs(shared_ips_count), ", ".join(bans)))
                await db.commit()
            self.total_banned_users += 1
        else:
            lenbans = 0
            async with aiosqlite.connect("user_data.db") as db:
                await db.execute("INSERT OR IGNORE INTO users VALUES (?)", (user_id,))
                await db.execute("INSERT OR IGNORE INTO banned_users VALUES (?, ?, ?, ?, ?, ?)",
                                 (user_id, 0, "", abs(lenbans), abs(shared_ips_count), ""))
                await db.commit()
            self.total_unbanned_users += 1

    async def create_complaint(self, user_id, banned_percentage, unbanned_percentage):
        self.driver.get('https://zelenka.guru/forums/801/create-thread')
        self.driver.add_cookie({'name': 'xf_user', 'value': config.xf_user})
        self.driver.add_cookie({'name': 'xf_session', 'value': config.xf_session})
        self.driver.add_cookie({'name': 'xf_tfa_trust', 'value': config.xf_tfa_trust})
        title_input = self.driver.find_element(By.ID, 'ctrl_title_thread_create')
        title_input.send_keys(f'Жалоба на пользователя https://zelenka.guru/members/{user_id}')
        complaint_text = f"""
        [club]
        1. https://zelenka.guru/members/{user_id}
        2. мульт мошенника
        3.
        Процент забаненных в общих айпи адресах: {banned_percentage:.2f}%
        Процент незабаненных в общих айпи адресах: {unbanned_percentage:.2f}%

        Данная жалоба создана автоматически, возможно бот неправильно подсчитает проценты, пажежа не баньте только ♥
        [/club]  
        """
        element = self.driver.find_element(By.XPATH,
                                           "/html/body/div[2]/div/div/div/form/fieldset[1]/dl[3]/dd/div/div[4]/div[2]/div/p")
        element.clear()
        element.send_keys(complaint_text)
        self.driver.switch_to.default_content()
        submit_button = self.driver.find_element(By.XPATH, '//input[@type="submit" and @value="Создать тему"]')
        submit_button.click()
        time.sleep(60)

    async def print_percentages(self):
        async with aiosqlite.connect("user_data.db") as db:
            cursor = await db.execute("SELECT * FROM banned_users")
            rows = await cursor.fetchall()

            for row in rows:
                user_id = row[0]
                lenbans = row[3]
                lenunbans = row[4]
                if lenbans == 0:
                    continue
                banned_percentage = (lenbans / (lenbans + lenunbans)) * 100 if (lenbans + lenunbans) > 0 else 0
                unbanned_percentage = 100 - banned_percentage
                logger.info(
                    f'User ID: {user_id}, {lenbans}, {lenunbans}, Процент забаненных: {banned_percentage:.2f}%, Процент незабаненных: {unbanned_percentage:.2f}%')
                if banned_percentage >= 50:
                    await self.create_complaint(user_id, banned_percentage, unbanned_percentage)

    async def run(self):
        await create_database()
        while True:
            await self.scrape_users('https://zelenka.guru/members')
            user_links = await self.scrape_online_users()
            for user_link in user_links:
                shared_ips_link = f'https://zelenka.guru/{user_link}shared-ips/'
                self.driver.add_cookie({'name': 'xf_user', 'value': config.xf_user})
                self.driver.add_cookie({'name': 'xf_session', 'value': config.xf_session})
                self.driver.add_cookie({'name': 'xf_tfa_trust', 'value': config.xf_tfa_trust})
                self.shared_ips_link = shared_ips_link
                try:
                    self.driver.get(shared_ips_link)
                except Exception as e:
                    logger.error(f'link: {shared_ips_link}, Err: {e}')
                await self.scrape_shared_ips()
            await self.scrape_banned_users()
            await self.print_percentages()
            time.sleep(60)


if __name__ == '__main__':
    scraper = ZelenkaScraper()
    asyncio.run(scraper.run())
