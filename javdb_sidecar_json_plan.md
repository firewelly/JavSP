# 需求文档：JavDB 抓取结果落盘 sidecar JSON（方案 A · JavSP_mac2 侧）

> 状态：**规划稿，未实施**。日期：2026-10-30
> 跨项目总方案（权威契约）：`../media/scrape_import_integration_plan.md` —— JSON schema 如需变更，须同步修订两份文档。
> 本文档只覆盖 JavSP_mac2 侧的需求；media 侧（NFO/JSON 导入升级）见总方案 §3.2。

---

## 1. 背景与目标

现状：本项目刮削普通影片时唯一数据源就是 JavDB（`config.yml:45` `normal: [javdb]`），`javsp/web/javdb.py` 会打开 JavDB 搜索页 + 详情页拿到全量数据（URL、时长、评分、原始标签、演员、磁力、预览图……）。但这些数据写 NFO 时被大量丢弃，媒体库项目（`../media`）随后还要用自己的爬虫把**同一个详情页再开一次**。

目标：刮削时把 JavDB 全量数据落盘为视频文件夹内的 sidecar JSON 文件（NFO 之外的附加文件），media 的 NFO 导入功能识别该文件后直接入库，**消除每个视频的第二次页面访问**。

## 2. 修改对象

- **主改：`javsp/web/javdb.py`** —— 本项目的 JavDB 主爬虫（Playwright 直连 javdb580.com，不走代理），与媒体库项目的 `../media/javdb_system/javdb_crawler_single.py` 同站同源（同为 Playwright + javdb580 直连方案）。media 侧"JAVDB信息获取"以同款爬虫为主、JavBus/JavSP 为回退，因此本项目以它为主数据源。
- **其余爬虫（fanza/fc2/avsox/javmenu/fc2ppvdb 等）不修改**，仅作为 fc2/cid 等特殊类型的回退链。

## 3. 需求明细

### R1 演员个人页链接抓取（改 `javsp/web/javdb.py` + `javsp/datatype.py`）

`parse_actress()`（javdb.py:113）目前只返回名字列表，链接被丢弃。而 media 侧批量更新器判断"是否已抓过"的谓词依赖演员的 `profile_url LIKE '%javdb.com%'`（`javdb_information_updater.py:383-391`）——**这是整个方案唯一必须动爬虫的点**。

要求：
1. `parse_actress()` 增强为同时提取每个 ♀ 演员的个人页链接，新旧两版页面结构都要兼容：
   - 新版：`<a>` 标签以 class 区分性别（`actor-female` / `actor-male`），取 `actor-female` 的 `@href`；
   - 旧版：按 ♀/♂ 符号定位性别，链接就在被遍历的 `<a>` 上，同样可取。
2. `MovieInfo`（javsp/datatype.py:16）新增字段 `actress_links = None`：`[{"name": str, "link": str|None}, ...]`，与 `actress` 列表**同序**；取不到链接时 `link=None`。
3. 链接归一化：相对路径 urljoin 到 `https://javdb.com`（`permanent_url`），与 `movie.url` 的归一惯例一致（javdb.py:271），最终形如 `https://javdb.com/actors/yERr`。
4. `_partial_parse_from_search`（VIP/登录回退路径，javdb.py:96）允许不产出 `actress_links`（字段为 None 即可）。
5. 其他爬虫不写此字段（保持 None），不产生兼容问题。

### R2 sidecar JSON 写出（新增 `javsp/sidecar.py` + 挂接 `javsp/__main__.py`）

1. **触发门槛（用户明确要求）：仅当 JavDB 爬虫成功时才写 JSON。**
   - 判定方式：`parallel_crawler()` 返回的 `all_info` 只保留抓取成功的爬虫键（`__main__.py:153`），故门槛即 `'javdb' in all_info`；该变量在写 NFO 处（`__main__.py:513`）的同层作用域内，可直接判断；
   - 其他源（fc2/avsox…）成功而 javdb 失败 → **不写** JSON。media 侧发现无 JSON 会走原有网页补抓路径，行为与今天完全一致。
2. 写出点：`write_nfo(movie.info, movie.nfo_file)` 调用旁（`__main__.py:513`），封装为独立函数 `write_sidecar_json(movie, javdb_info)`（放新文件 `javsp/sidecar.py`，NFO 逻辑不混入）。
3. 文件名：跟随 NFO 命名规则——`Cfg().summarizer.nfo.basename_pattern`（当前 `"movie"`）+ `.json`，与 NFO 同目录。media 侧查找顺序将按 `movie.json` → `<视频基名>.json` → 目录内含 `_schema` 标记的唯一 json 对称设计。
4. 内容：**javdb 爬虫实例的保真数据**（多源合并前的 `MovieInfo`；当前 `normal: [javdb]` 配置下即最终数据）。schema 见 §4。
5. 容错：写出失败仅 `logger.warning`，不得中断整理主流程；每次刮削重写（幂等）；多分集影片一个文件夹一份（与 NFO 同粒度）。
6. 线程安全：javdb 实例在后台线程填充，写 JSON 在主线程 finalize 阶段执行，无竞争。

### R3 配置开关（`javsp/config.py` + `config.yml`）

1. `Crawler` 模型（config.py:109）新增 `save_sidecar_json: bool = True`——**带默认值**，旧 `config.yml` 不改即生效；
2. `config.yml` 的 `crawler:` 节同步加注释示例，说明用途（供媒体库免二次抓取导入）与默认值。

### R4 明确不做

- **NFO 的内容与格式保持不变**（Kodi/Jellyfin 兼容优先，JSON 只服务于 media 导入）；
- 不直接读写 media 的数据库——跨项目只通过 JSON 文件契约；
- 不改翻译、命名、封面裁剪等其他流程。

## 4. JSON schema：`javsp-sidecar/1`

```json
{
  "_schema": "javsp-sidecar/1",
  "scraped_at": "2026-10-30 12:34:56",
  "source_base_url": "https://javdb580.com",
  "info": {
    "dvdid": "ABP-123", "cid": null,
    "url": "https://javdb.com/v/xxxxx",
    "title": "…", "ori_title": null,
    "cover": "https://…", "big_cover": null,
    "genre": ["巨乳", "单体作品"], "genre_id": ["tag1", "tag2"], "genre_norm": ["巨乳", "单人作品"],
    "score": "8.36",
    "serial": "…",
    "actress": ["…"],
    "actress_links": [{"name": "…", "link": "https://javdb.com/actors/xxxx"}],
    "director": "…", "duration": "150", "producer": "…", "publisher": "…",
    "uncensored": false, "publish_date": "2024-05-02",
    "magnet": ["magnet:?xt=urn:btih:…", "…"],
    "preview_pics": ["…"], "preview_video": "…", "plot": null
  }
}
```

字段与 media 侧去向的对照（media 导入契约，详见总方案 §3.2）：

| info 字段 | media 侧去向 |
|---|---|
| `dvdid` | `javdb_info.javdb_code` |
| `url` | `javdb_info.javdb_url` |
| `publish_date` | `javdb_info.release_date` |
| `duration` | `javdb_info.duration`（同为分钟数字串） |
| `producer` | `javdb_info.studio`（JavDB 片商） |
| `serial` | `javdb_info.series`（media 爬虫都没抓的字段，顺带补上） |
| `score` | `javdb_info.score` = **10 分制 ÷ 2**（现库为 5 分制）；原 10 分制字符串存 `rating` 列 |
| `cover` | `javdb_info.cover_url` |
| `magnet` | `javdb_info.magnet_links`（JSON 数组，纯 `magnet:` 串，`[javdb.com]` 前缀本项目已剥离） |
| `genre`（原始标签） | `javdb_tags`（与网页抓取同源） |
| `actress_links[].link` | `actors.profile_url`（**更新器"已抓过"谓词生效的关键**） |
| `title` / `genre_norm` / `director` / `plot` 等 | 兜底与暂存；media 显示类字段继续以 NFO 为准 |

约定：
- `scraped_at` 使用本地时区 `YYYY-MM-DD HH:MM:SS` 文本（media 仓时间字段存储约定）；
- `info` 内所有字段均为 optional，解析方按缺省处理；
- `genre_norm` 由本项目 `data/genre_javdb.csv` 映射产出（现有逻辑），media 侧 `videos.genre` 沿用 NFO 同值。

## 5. 验收清单

- [ ] 刮削一部普通番号 → 目标文件夹出现 `movie.json`，`actress_links` 齐全且为 `https://javdb.com/actors/…` 绝对链接
- [ ] `save_sidecar_json: false` → 不产生 JSON，其余行为与改动前一致
- [ ] NFO 文件与改动前逐字节一致
- [ ] 模拟 javdb 失败（如 fc2 源成功、javdb 超时）→ 不产生 JSON
- [ ] JSON 字段名与 §4 对照表逐一核对（media 侧按此解析）
- [ ] 多分集影片：一个文件夹仅一份 `movie.json`

## 6. 实施顺序提示

1. `datatype.py` 加 `actress_links` 字段（无副作用，先行）；
2. `javdb.py` 演员链接抓取（新旧页面双兼容）；
3. `sidecar.py` 写出函数 + `__main__.py` 挂接 + config 开关；
4. 回归：`unittest/data/` 下已有各站样例 JSON 可用于 `MovieInfo` 加载回归。
