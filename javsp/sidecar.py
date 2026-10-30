"""将JavDB抓取到的全量数据保存为视频文件夹内的sidecar JSON

媒体库(../media)导入时可读取此文件直接入库，避免再次访问JavDB详情页。
schema定义见 ../media/scrape_import_integration_plan.md §3.2，变更时需同步修订。
"""
import json
import logging
import os
from datetime import datetime

from javsp.config import Cfg
from javsp.datatype import Movie, MovieInfo


logger = logging.getLogger(__name__)

SCHEMA = 'javsp-sidecar/1'

# 与媒体库约定的info字段（schema: javsp-sidecar/1）
INFO_FIELDS = (
    'dvdid', 'cid', 'url', 'title', 'ori_title',
    'cover', 'big_cover',
    'genre', 'genre_id', 'genre_norm',
    'score', 'serial',
    'actress', 'actress_links',
    'director', 'duration', 'producer', 'publisher',
    'uncensored', 'publish_date',
    'magnet', 'preview_pics', 'preview_video', 'plot',
)


def sidecar_file(movie: Movie) -> str:
    """sidecar JSON的路径: 与NFO同目录、同基名"""
    return os.path.splitext(movie.nfo_file)[0] + '.json'


def build_sidecar_payload(info: MovieInfo) -> dict:
    """将抓取到的MovieInfo转换为sidecar JSON的内容"""
    # 延迟导入，避免在未使用JavDB时加载playwright等依赖
    from javsp.web.javdb import base_url as source_base_url
    return {
        '_schema': SCHEMA,
        'scraped_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source_base_url': source_base_url,
        'info': {k: getattr(info, k, None) for k in INFO_FIELDS},
    }


def write_sidecar_json(movie: Movie, javdb_info: MovieInfo):
    """将JavDB的抓取结果写入视频文件夹内的sidecar JSON

    仅应在JavDB抓取成功时调用；写出失败只记录警告，不影响整理主流程。

    Returns:
        sidecar JSON的路径；未启用或写出失败时返回None
    """
    if not Cfg().crawler.save_sidecar_json:
        return None
    path = None
    try:
        path = sidecar_file(movie)
        payload = build_sidecar_payload(javdb_info)
        with open(path, 'wt', encoding='utf-8') as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write('\n')
        logger.debug(f"已写入sidecar JSON: '{path}'")
        return path
    except Exception as e:
        logger.warning(f'写入sidecar JSON失败: {e}')
        return None
