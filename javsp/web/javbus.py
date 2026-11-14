"""从JavBus抓取数据"""
import json
import logging
import os

import lxml.html

from javsp.web.base import *
from javsp.web.pwcommon import launch_context, close_context, PLAYWRIGHT_PROFILE_ROOT, DEFAULT_UA
from javsp.web.exceptions import *
from javsp.func import *
from javsp.config import Cfg, CrawlerID
from javsp.datatype import MovieInfo, GenreMap


logger = logging.getLogger(__name__)
genre_map = GenreMap('data/genre_javbus.csv')
permanent_url = 'https://www.javbus.com'
if Cfg().network.proxy_server is not None:
    base_url = permanent_url
else:
    base_url = str(Cfg().network.proxy_free[CrawlerID.javbus])

# 年龄验证通过的cookie保存位置：与浏览器profile放在一起，验证一次后requests可长期复用
COOKIE_FILE = os.path.join(PLAYWRIGHT_PROFILE_ROOT, 'javbus_cookies.json')

USER_AGENT = DEFAULT_UA


def _load_saved_cookies() -> dict:
    try:
        with open(COOKIE_FILE, encoding='utf-8') as f:
            return {c['name']: c['value'] for c in json.load(f) if c.get('name')}
    except Exception:
        return {}


def _save_browser_cookies(cookies: list):
    try:
        os.makedirs(PLAYWRIGHT_PROFILE_ROOT, exist_ok=True)
        with open(COOKIE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cookies, f)
    except Exception as e:
        logger.debug(f'JavBus: 保存cookies失败: {e}')


def _get_proxy_settings():
    proxy_url = Cfg().network.proxy_server
    if proxy_url is None:
        return None
    server = str(proxy_url)
    if server.startswith('socks5h://'):
        server = 'socks5://' + server[len('socks5h://'):]
    return {'server': server}


def _playwright_fetch_html(url):
    """经持久化profile的浏览器抓取页面

    浏览器内可通过年龄验证（勾选并提交），验证cookie随profile持久化；同时提取
    cookies保存到本地，之后的影片可直接用requests+cookie访问，不再需要浏览器
    """
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser, context = launch_context(p, _get_proxy_settings(), user_agent=USER_AGENT)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(url, wait_until='domcontentloaded', timeout=60000)
            try:
                page.wait_for_load_state('networkidle', timeout=10000)
            except Exception:
                pass
            modal = page.locator('#ageVerify')
            if modal.count() > 0:
                box = modal.locator('input[type="checkbox"]')
                if box.count() > 0:
                    box.first.check()
                submit = modal.locator('#submit')
                if submit.count() > 0:
                    submit.first.click()
                    page.wait_for_load_state('domcontentloaded', timeout=30000)
                    page.wait_for_timeout(1500)
            # 保存会话cookie（含验证后的age=verified），供后续requests直接复用
            try:
                _save_browser_cookies(context.cookies())
            except Exception as e:
                logger.debug(f'JavBus: 提取cookies失败: {e}')
            html = lxml.html.fromstring(page.content())
            html.make_links_absolute(page.url, resolve_base_href=True)
            return html
        finally:
            close_context(browser, context)


def _parse_html(html, movie: MovieInfo):
    """从影片页的DOM解析数据并更新到movie"""
    # requests与浏览器两条抓取路径都会进入这里，404/验证页的判断统一在此处理
    page_title = html.xpath('/html/head/title/text()')
    if page_title and page_title[0].startswith('404 Page Not Found!'):
        raise MovieNotFoundError(__name__, movie.dvdid)
    if page_title and 'Age Verification' in page_title[0]:
        raise CredentialError(f'JavBus: 年龄验证未通过: {movie.dvdid}')
    containers = html.xpath("//div[@class='container']")
    if not containers:
        # 影片页结构与预期不符（如站点改版、无该影片的重定向页）
        logger.debug(f'JavBus: 页面结构异常(无container)，视为未收录: {movie.dvdid}')
        raise MovieNotFoundError(__name__, movie.dvdid)
    container = containers[0]
    titles_h3 = container.xpath("h3/text()")
    if not titles_h3:
        logger.debug(f'JavBus: 页面无标题，视为未收录: {movie.dvdid}')
        raise MovieNotFoundError(__name__, movie.dvdid)
    title = titles_h3[0]
    cover = container.xpath("//a[@class='bigImage']/img/@src")[0]
    preview_pics = container.xpath("//div[@id='sample-waterfall']/a/@href")
    infos = container.xpath("//div[@class='col-md-3 info']")
    if not infos:
        logger.debug(f'JavBus: 页面无信息栏，视为未收录: {movie.dvdid}')
        raise MovieNotFoundError(__name__, movie.dvdid)
    info = infos[0]
    dvdid = info.xpath("p/span[text()='識別碼:']")[0].getnext().text
    publish_date = info.xpath("p/span[text()='發行日期:']")[0].tail.strip()
    duration = info.xpath("p/span[text()='長度:']")[0].tail.replace('分鐘', '').strip()
    director_tag = info.xpath("p/span[text()='導演:']")
    if director_tag:    # xpath没有匹配时将得到空列表
        movie.director = director_tag[0].getnext().text.strip()
    producer_tag = info.xpath("p/span[text()='製作商:']")
    if producer_tag:
        text = producer_tag[0].getnext().text
        if text:
            movie.producer = text.strip()
    publisher_tag = info.xpath("p/span[text()='發行商:']")
    if publisher_tag:
        movie.publisher = publisher_tag[0].getnext().text.strip()
    serial_tag = info.xpath("p/span[text()='系列:']")
    if serial_tag:
        movie.serial = serial_tag[0].getnext().text
    # genre, genre_id
    genre_tags = info.xpath("//span[@class='genre']/label/a")
    genre, genre_id = [], []
    for tag in genre_tags:
        tag_url = tag.get('href')
        pre_id = tag_url.split('/')[-1]
        genre.append(tag.text)
        if 'uncensored' in tag_url:
            movie.uncensored = True
            genre_id.append('uncensored-' + pre_id)
        else:
            movie.uncensored = False
            genre_id.append(pre_id)
    # JavBus的磁力链接是依赖js脚本加载的，无法通过静态网页来解析
    # actress, actress_pics
    actress, actress_pics = [], {}
    actress_tags = html.xpath("//a[@class='avatar-box']/div/img")
    for tag in actress_tags:
        name = tag.get('title')
        pic_url = tag.get('src')
        actress.append(name)
        if not pic_url.endswith('nowprinting.gif'):     # 略过默认的头像
            actress_pics[name] = pic_url
    # 整理数据并更新movie的相应属性
    movie.url = f'{permanent_url}/{movie.dvdid}'
    movie.dvdid = dvdid
    movie.title = title.replace(dvdid, '').strip()
    movie.cover = cover
    movie.preview_pics = preview_pics
    if publish_date != '0000-00-00':    # 丢弃无效的发布日期
        movie.publish_date = publish_date
    movie.duration = duration if int(duration) else None
    movie.genre = genre
    movie.genre_id = genre_id
    movie.actress = actress
    movie.actress_pics = actress_pics


def parse_data(movie: MovieInfo):
    """从网页抓取并解析指定番号的数据

    优先使用requests直接抓取；被年龄验证墙（302到/doc/driver-verify，验证需
    浏览器执行JS）拦截时，经持久化profile的浏览器完成验证并抓取，验证cookie
    保存后后续影片恢复纯requests访问
    Args:
        movie (MovieInfo): 要解析的影片信息，解析后的信息直接更新到此变量内
    """
    url = f'{base_url}/{movie.dvdid}'
    resp = request_get(url, cookies=_load_saved_cookies(), delay_raise=True)
    if any('driver-verify' in (h.headers.get('Location') or '') for h in resp.history):
        # requests被年龄验证墙拦截：浏览器完成验证并直接在浏览器中抓取
        logger.debug(f'JavBus: 触发年龄验证墙，切换浏览器抓取: {movie.dvdid}')
        html = _playwright_fetch_html(url)
        _parse_html(html, movie)
        return
    # 疑似JavBus检测到类似爬虫的行为时会要求登录，不过发现目前不需要登录也可以从重定向前的网页中提取信息
    if resp.history and resp.history[0].status_code == 302:
        html = resp2html(resp.history[0])
    else:
        html = resp2html(resp)
    # 引入登录验证后状态码不再准确，因此还要额外通过检测标题来确认是否发生了404
    page_title = html.xpath('/html/head/title/text()')
    if page_title and page_title[0].startswith('404 Page Not Found!'):
        raise MovieNotFoundError(__name__, movie.dvdid)
    if page_title and 'Age Verification' in page_title[0]:
        # 端到端再次落在验证页（cookie失效等）：同样走浏览器
        logger.debug(f'JavBus: 年龄验证页，切换浏览器抓取: {movie.dvdid}')
        html = _playwright_fetch_html(url)
        _parse_html(html, movie)
        return
    _parse_html(html, movie)


def parse_clean_data(movie: MovieInfo):
    """解析指定番号的影片数据并进行清洗"""
    parse_data(movie)
    movie.genre_norm = genre_map.map(movie.genre_id)
    movie.genre_id = None   # 没有别的地方需要再用到，清空genre id（暗示已经完成转换）


if __name__ == "__main__":
    import pretty_errors
    pretty_errors.configure(display_link=True)
    logger.root.handlers[1].level = logging.DEBUG

    movie = MovieInfo('NANP-030')
    try:
        parse_clean_data(movie)
        print(movie)
    except CrawlerError as e:
        logger.error(e, exc_info=1)
