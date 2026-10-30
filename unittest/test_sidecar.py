import json
import os
import sys
from types import SimpleNamespace

import lxml.html


file_dir = os.path.dirname(__file__)
sys.path.insert(0, os.path.abspath(os.path.join(file_dir, '..')))

from javsp import sidecar
from javsp.datatype import Movie, MovieInfo
from javsp.web import javdb
from javsp.web.javdb import parse_actress_entries


SAMPLE = os.path.join(file_dir, 'data', 'IPX-177 (javdb).json')


def make_span(html):
    """模拟get_html_wrapper: 将相对链接按实际访问的镜像站域名展开"""
    node = lxml.html.fromstring(html)
    node.make_links_absolute('https://javdb580.com/v/xxxxx', resolve_base_href=True)
    return node


def build_movie(folder):
    movie = Movie('IPX-177')
    movie.save_dir = str(folder)
    movie.nfo_file = str(folder / 'movie.nfo')
    return movie


def test_parse_actress_entries_new_page():
    node = make_span(
        '<span><a class="actor-female" href="/actors/yERr">相沢みなみ</a>'
        '<a class="actor-male" href="/actors/male1">男优</a></span>')
    assert parse_actress_entries(node) == [
        {'name': '相沢みなみ', 'link': 'https://javdb.com/actors/yERr'},
    ]


def test_parse_actress_entries_old_page():
    node = make_span(
        '<span><a href="/actors/o1"><b>♀</b>上原亜衣</a>'
        '<strong>♂</strong><a href="/actors/o2">男优</a></span>')
    assert parse_actress_entries(node) == [
        {'name': '上原亜衣', 'link': 'https://javdb.com/actors/o1'},
    ]


def test_parse_actress_entries_without_link():
    node = make_span('<span><a class="actor-female">无链接</a></span>')
    assert parse_actress_entries(node) == [{'name': '无链接', 'link': None}]


def test_write_sidecar_json(tmp_path):
    info = MovieInfo(from_file=SAMPLE)
    info.actress_links = [{'name': '相沢みなみ', 'link': 'https://javdb.com/actors/yERr'}]
    path = sidecar.write_sidecar_json(build_movie(tmp_path), info)

    assert path == str(tmp_path / 'movie.json')
    with open(path, encoding='utf-8') as f:
        payload = json.load(f)
    assert payload['_schema'] == 'javsp-sidecar/1'
    assert payload['source_base_url'] == javdb.base_url
    assert payload['info']['dvdid'] == 'IPX-177'
    assert payload['info']['actress_links'] == info.actress_links
    assert set(payload['info']) == set(sidecar.INFO_FIELDS)

    # 重复写入应幂等覆盖
    assert sidecar.write_sidecar_json(build_movie(tmp_path), info) == path


def test_write_sidecar_json_disabled(tmp_path, monkeypatch):
    fake_cfg = lambda: SimpleNamespace(crawler=SimpleNamespace(save_sidecar_json=False))
    monkeypatch.setattr(sidecar, 'Cfg', fake_cfg)
    info = MovieInfo(from_file=SAMPLE)
    assert sidecar.write_sidecar_json(build_movie(tmp_path), info) is None
    assert not (tmp_path / 'movie.json').exists()


def test_write_sidecar_json_failure_tolerated():
    # nfo_file未设置时写出失败，只记录警告而不抛出异常
    info = MovieInfo(from_file=SAMPLE)
    assert sidecar.write_sidecar_json(Movie('IPX-177'), info) is None
