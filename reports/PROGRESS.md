# 椤圭洰杩涘害璁板綍

> 姣忓畬鎴愪竴涓噷绋嬬鎴栨柊鎶€鑳?鍦ㄦ杩藉姞璁板綍銆傛牸寮?`[鏃ユ湡] 鐘舵€?- 鍐呭`(鐘舵€? 杩涜涓?/ 宸插畬鎴?/ 闃诲)

## 2026-08-12

- [x] 宸插畬鎴?- 椤圭洰楠ㄦ灦鎼缓: 鍒涘缓 `scripts/`(浜哄伐鐙珛杩愯鍏ュ彛)銆乣skills/`銆乣src/`銆乣tests/`銆乣utils/`銆乣assets/` 绛夌洰褰?- [x] 宸插畬鎴?- 姊崇悊鏋舵瀯瑙勮寖: Agent Skills 瑙勮寖(SKILL.md 缁撴瀯)銆乣src/models/`(ORM) + `src/schemas/`(DTO) 鍒嗗眰銆乤ssets 鎸夋媿鍝両D鍒嗘《
- [x] 宸插畬鎴?- 鐢熸垚 `AGENTS.md`(Agent 宸ヤ綔鎸囧紩)涓?`README.md`(椤圭洰璇存槑)
- [x] 宸插畬鎴?- **鍏媿缃戠埇铏妧鑳?`skills/gpai-crawler/`**: SKILL.md + scripts/crawler.py + references/xpath_rules.md
- [x] 宸插畬鎴?- 浜哄伐 CLI 鍏ュ彛 `scripts/crawl_gpai.py`(--restate/--with-images/--save-json)
- [x] 宸插畬鎴?- 濂戠害娴嬭瘯 `tests/test_gpai_crawler.py`(10 涓敤渚?鍏ㄩ儴閫氳繃)
- [x] 宸插畬鎴?- 瀹炴祴鐖彇: restate=1 鍏?74 鏉°€乺estate=2 鍏?7 鏉?鍧囦负鍙告硶鎷嶅崠鎴夸骇),璇︽儏椤靛浘鐗?8 寮?鏉?- [x] 宸插畬鎴?- 淇瀹炴祴鍙戠幇鐨勫樊寮? 浠锋牸鏍囩(璧锋媿浠?鍙樺崠浠?鏈€鏂颁环)銆佹椂闂存爣绛?寮€濮嬫椂闂?棰勮缁撴潫)銆佽瘎浼颁环鍗曚綅褰掍竴
- [x] 宸插畬鎴?- 淇鍗曢〉鐖敊: 椤甸潰鏈?2 涓?main-col-list,鍙彇绗竴涓?鍔?PAGE_CAP=20 鍗曢〉涓婇檺鏍￠獙
- [x] 宸插畬鎴?- 瀹炵幇鍥剧墖涓嬭浇(--download),瀹炴祴涓嬭浇 20 鏉℃埧婧?97 寮犲浘鐗囧埌 assets/{listing_id}/imgs/
- [x] 宸插畬鎴?- 纭缈婚〉瑙﹀彂婊戝潡楠岃瘉(鍙嶇埇),褰撳墠浠呯埇绗?1 椤?鎵归噺缈婚〉闇€浜哄伐/鎵撶爜
- [ ] 寰呭姙 - `src/models/` ORM 瀹炰綋瀹氫箟(listing / image / voice / video / publish)
- [ ] 寰呭姙 - 闃块噷璧勪骇鏁版嵁婧愯皟鐮?鏂瑰紡1鐖櫕 / 鏂瑰紡2 API)
- [ ] 寰呭姙 - 鏁版嵁娓呮礂(缁撴瀯鍖栧叆琛?+ 闈炵粨鏋勫寲 AI/瑙勫垯娓呮礂)
- [ ] 寰呭姙 - 鍥剧墖鍘绘按鍗?image-processor skill)
- [ ] 寰呭姙 - 鍥炬枃鎴愮墖(video-builder skill)
- [ ] 寰呭姙 - TTS 閰嶉煶鎺ュ叆(tts skill)
- [ ] 寰呭姙 - 椋庨櫓鏍￠獙(risk-checker skill)
- [ ] 寰呭姙 - 闊宠棰戝悎鎴?video-merger skill)
- [ ] 寰呭姙 - 澶氬钩鍙拌嚜鍔ㄥ彂甯?publisher skill)

## 2026-08-21 [宸插畬鎴怾 - 鍏媿缃戦噰闆嗚寖鍥存敹鏁?+ 閲囬泦鏃堕棿鎴?
- 鏂规B钀藉湴: 鍙噰闆?鍗冲皢寮€濮?(restate=1),鍒犻櫎"姝ｅ湪鎷嶅崠"(restate=2)鏀寔
  - `crawler.py`: 绉婚櫎 `--restate` CLI 鍙傛暟,`fetch_listings()` 鍥哄畾 restate=1,鍒犻櫎 end_time 瑙ｆ瀽閫昏緫
  - `src/schemas/listing.py`: `GpaiListing` 绉婚櫎 `end_time` 瀛楁,鏂板 `crawled_at`(ISO 閲囬泦鏃堕棿鎴?鍏ュ簱/鎺掗噸/瀹¤鐢?
  - 鍚屾鏇存柊: tests(16 閫氳繃)銆丼KILL.md銆亁path_rules.md銆乻cripts/crawl_gpai.py銆乷bserve_gpai_pagination.py
- 瀹炴祴閲囬泦 1 椤?20 鏉℃甯?鎬绘暟 74

## 2026-08-15 [宸插畬鎴怾 - 鐖櫕鍏叡鎶借薄 / 鍥剧墖閲嶈瘯 / start_time / 楠岃瘉鐮佸寮?/ 鍗曡〃鍘婚噸鍏ュ簱

- 璁″垝: `plans/2026-08-15-鐖櫕鍏叡鎶借薄涓庡幓閲嶅叆搴?txt`
- 鍏叡鎶借薄(甯︾被鍨嬫敞瑙?: `utils/parsing.py`(浠锋牸/鏃堕棿/閾炬帴/鏍囩)銆乣utils/browser.py`(UA/LAUNCH_ARGS/STEALTH_SCRIPT 澧炲己鐗?銆乣utils/download.py`(3娆￠噸璇?閫€閬?/2/4s 骞跺彂涓嬭浇)
  - ali/gpai 涓ょ埇铏垹闄ゆ湰鍦伴噸澶嶅壇鏈敼 import;gpai 鐨?download_images 鍚屾鍒囬噸璇曠増
- 闃块噷 start_time 浠庡垪琛ㄩ〉 `p.time-todo > span.value` 瑙ｆ瀽(`08鏈?5鏃?10:00` 鈫?琛ュ綋骞?,12-31 23:55 鍚庢墦鍗颁复鐣屾彁閱?瀹炴祴 120/120 濉厖
- 楠岃瘉鐮?DOM 妫€娴?鍒楄〃+瀛愰〉): `#nc_1__scale_text`/`#nc_1_nz1` + URL 鍙岄€氶亾;鐧诲綍姣?鍒嗛挓鑷姩鍒锋柊銆佹粦鍧楅殢鏈?-10鍒嗛挓鍒锋柊鎻愮ず浜哄伐
- 鍥剧墖涓嬭浇: 姣忓紶閲嶈瘯 3 娆°€侀€€閬?1/2/4s;鎵?3-5 寮犲苟鍙?涓嶈冻鍏ㄤ笅)
- 鍗曡〃 PostgreSQL 鍘婚噸: `models/listing.py`(椤跺眰,UNIQUE(source,item_id) + data JSONB)銆乣src/config.py`(.env DATABASE_URL)銆乣src/db.py`(engine/session/upsert 瀹归敊闄嶇骇)銆乣scripts/init_db.py`(寤鸿〃);ali CLI 鏂板 `--db`
- 渚濊禆: `pip install psycopg2-binary`
- 娴嬭瘯: 鏂板閲嶈瘯/start_time 瑙ｆ瀽鐢ㄤ緥,pytest 32 閫氳繃
- 寰呭姙: `.env` 濉湡瀹炲瘑鐮?鈫?`python scripts/init_db.py` 寤鸿〃 鈫?`--db` 瀹炴祴 upsert 鍘婚噸

## 2026-08-15 [宸插畬鎴怾 - 鍙屾簮閲囬泦瀹炴祴 + 婊戝潡鑷姩澶勭悊 + SQLAlchemy 鍏ュ簱鎵撻€?
- **鍙屾簮瀹炴祴鎴愬姛**(鍚?1 椤?:
  - 鍏媿缃? `python scripts/crawl_gpai.py --pages 1` 鈫?鎬绘暟 76,瑙ｆ瀽 20 鏉?璧锋媿浠?璇勪及浠?寮€濮嬫椂闂?閲囬泦鏃堕棿鎴冲潎鏈夋晥),`--save-json` 钀界洏
  - 闃块噷: `python scripts/crawl_ali.py --category 浣忓畢 --pages 1` 鈫?澹版槑 100,瑙ｆ瀽 120 鏉?start_time 120/120 鏈夋晥
- **婊戝潡鑷姩澶勭悊**: `_try_auto_slide`(crawler.py)妫€娴?`#nc_1_nz1` 鍚庢ā鎷熶汉鎵嬫嫋鍔?缂撳姩鏇茬嚎+闅忔満鎶栧姩/鍋滈】)鑷姩閫氳繃,1-2 娆″皾璇?澶辫触鎵嶈浆浜哄伐;鍒楄〃椤?瀛愰〉鍏辩敤
  - 鏂板濂戠害娴嬭瘯 `test_dom_blocked_detects_slider`/`test_try_auto_slide_success`/`test_try_auto_slide_no_slider`,pytest 36 閫氳繃
- **SQLAlchemy 鍏ュ簱鎵撻€?*:
  - `.env` 濉湡瀹炲瘑鐮?`1116lry`),鍒涘缓鏁版嵁搴?`auction`,`python scripts/init_db.py` 寤鸿〃鎴愬姛
  - 琛?`listings`: 涓婚敭 + `UNIQUE(source,item_id)` 鍞竴绾︽潫 + data JSONB
  - upsert 鍘婚噸瀹炴祴: 鍚屼竴 `(source,item_id)` 鎻掍袱娆?鈫?count=1 鍐呭鏇存柊,娴嬭瘯鏁版嵁宸叉竻鐞?  - 鍏ㄧ▼ SQLAlchemy(DeclarativeBase/engine/session),鏃犲師鐢?SQL 鎸佷箙鍖?
## 2026-08-15 [宸插畬鎴怾 - 澶氭簮骞惰閲囬泦 + gpai 鍏ュ簱

- 鏂板 `scripts/crawl_all.py` 骞惰缂栨帓: 瀛愯繘绋嬪悓鏃跺惎鍔ㄥ叕鎷嶇綉 + 闃块噷涓ゅ鐖櫕,鍚勬寔鐙珛 Chromium/profile/鐧诲綍鎬?浜掍笉闃诲
  - 鍙傛暟: `--pages`(閫氱敤)銆乣--ali-pages/--gpai-pages`(鐙珛)銆乣--ali-category`銆乣--download`銆乣--db`銆乣--headless`銆乣--skip-gpai/--skip-ali`
  - 淇 Windows 涓?`Popen` 涓嶈兘鐩存帴鎵ц `.py` 鈫?鍓嶇紑 `sys.executable`
- gpai crawler 鏂板 `--db`: 缁撴灉 upsert 杩?PostgreSQL(涓?ali 鍚屾ā寮忋€佸悓琛ㄣ€乣UNIQUE(source,item_id)` 鍘婚噸)
- 瀹炴祴 `python scripts/crawl_all.py --pages 1 --db`:
  - 涓ゆ簮骞惰鎴愬姛,鍏ュ簱 ali=120 鏉°€乬pai=20 鏉?price/time/data(assets_dir)/status 瀛楁瀹屾暣
  - **閲嶅璺戜竴娆″幓閲嶉獙璇?*: count 浠?120+20,鏃犻噸澶嶈褰?- 娴嬭瘯 36 鍏ㄧ豢

## 2026-08-15 [宸插畬鎴怾 - DB data 缁撴瀯閲嶆瀯 + gpai 璧勪骇杩佺Щ + 浠?DB 涓哄噯鏂偣缁紶

- **鏂?data 缁撴瀯(DB + meta.json)**:
  - `data.images` = `[{url, file|null}]`(file=鏈湴鏂囦欢鍚?鏈笅杞?null)
  - 绉婚櫎 `data.assets_dir`(璺緞鏀逛负鍙帹瀵?`assets/{source}/{item_id}/`)銆佺Щ闄?`data.raw` 鐨?href/title(淇濈暀璧锋媿/璇勪及/寮€濮嬫椂闂村璁℃枃鏈?
  - gpai 璧勪骇鐢?`assets/{item_id}/` 杩佽嚦 `assets/gpai/{item_id}/`(涓庨樋閲屽绉?;涓存椂 `scripts/migrate_schema.py` 杩佺Щ 140 鏉?+ 29 鐩綍鍚庡凡鍒犻櫎
  - ali 瀛橀噺 images 涓虹┖鐨?58 鏉¤ˉ URL(file 浠?null 鍥犳湰鍦版棤鍥?;61 鏉″洖濉?file;gpai 20 鏉?file 鍏ㄩ儴鍥炲～
- **鏂偣缁紶浠?DB 涓哄噯**:
  - `src/db.py::get_source_images(source)` 鈫?`{item_id: [{url, file}]}`
  - 涓ょ埇铏?`--skip-complete`: 鏈湴鍥鹃綈鍏ㄨ烦杩囧瓙椤?缂烘枃浠剁敤 DB URL 绂荤嚎琛ヤ笅(涓嶅紑娴忚鍣?
  - **淇杩佺Щ寮曞彂鐨勮鍒ゆ柇**: file=null 鏃?`(dir / "")` 閫€鍖栦负鐩綍鏈韩 exists=True 鈫?婕忓垽,鏀逛负鏄惧紡瑕佹眰 `x.get("file") and exists`
- **缂栨帓浠ｇ爜绉诲叆 `src/orchestrator.py`**(build_commands/run_sources),`scripts/crawl_all.py` 鍙樿杽浠?argparse,鏀寔 `--skip-complete`/`--only gpai|ali`
- 娴嬭瘯 39 鍏ㄧ豢;鐪熷疄鍥炲～楠岃瘉涓ゆ gpai `--pages 1 --download --skip-complete --db` 鍧囨甯?- 娓呯悊: 缁撴潫鏃╁墠閬楃暀鐨勪袱涓崱姝?ali 鐖櫕杩涚▼(1:42 鍚姩)

## 2026-08-15 [宸插畬鎴怾 - category 鍒椾慨澶?+ 鍘嗗彶鍥炲～

- **鏍瑰洜**: `AuctionListing` DTO 鏃?`category` 瀛楁,鍏ュ簱 `row = l.to_dict()` 姘歌繙鏃犺閿?鈫?DB `category` 鍏?NULL
- **姝ｅ紡浠ｇ爜**:
  - `src/schemas/listing.py::AuctionListing` 鏂板 `category: Optional[str] = None`
  - ali 涓ゅ鏋勯€?`_parse_listing`/`_fetch_category_impl`)浼?`category=category`
  - gpai 涓ゅ鏋勯€犱紶 `category="鎴夸骇"`(鍏媿缃戠被鍨嬬粺涓€涓烘埧浜?
- **鍘嗗彶鍥炲～**(涓€娆℃€?`scripts/backfill_category.py`,璺戝畬宸插垹): ali 120 鏉♀啋銆屼綇瀹呫€嶃€乬pai 20 鏉♀啋銆屾埧浜с€?- 娴嬭瘯 39 鍏ㄧ豢(鏂板 category 鏂█)

## 2026-08-15 [宸插畬鎴怾 - 鐩綍缁撴瀯閲嶆瀯: src鈫抋pp / db 鍖呮敹鏁?/ config 椤跺眰

璁″垝: `plans/2026-08-15-鐩綍缁撴瀯閲嶆瀯-src鍒癮pp涓巇b鍖?txt`
- **鑳屾櫙**: AGENTS/README 澹扮О `src/models/`,瀹為檯 ORM 鍦ㄩ《灞?`models/`,鏂囨。涓庡疄鐜颁笉涓€鑷?`config.py`/`db.py` 杩欑被鍩虹璁炬柦鏀?`src/` 灞傜骇瑙傛劅涓嶄匠
- **缁撴瀯鍙樺寲**(鐢ㄦ埛閫愰」纭):
  - `src/` 鈫?`app/`: 绾簲鐢ㄩ€昏緫,鍚?`schemas/`(DTO)+ `orchestrator.py`(缂栨帓)
  - `models/` 鈫?`db/`: ORM 鏀惰繘 `db/listing.py`;鍘?`src/db.py` 鏀惰繘 `db/db.py`;鏂板 `db/__init__.py` re-export(`from db import session_scope, upsert_listing, ...`)
  - `src/config.py` 鈫?椤跺眰 `config.py`(`PROJECT_ROOT` 鐢?`parents[1]` 鏀?`parents[0]`)
- **鍚屾淇敼 import**: `scripts/init_db.py`銆乣scripts/crawl_all.py`銆佷袱 skill crawler(鍚?4 澶?銆乣tests`(10 澶?,鍒犻櫎鏃?`src/`銆乣models/`
- **楠岃瘉**: pytest 39 鍏ㄧ豢;`python scripts/init_db.py` 寤鸿〃骞傜瓑閫氳繃;db re-export 涓庝袱 skill crawler 妯″潡鍔犺浇鍧?OK
- **鏂囨。鍚屾**: AGENTS.md銆丷EADME.md銆佷袱 SKILL.md 宸叉敼;鍘嗗彶璁″垝鏂囨。 `2026-08-15-鐖櫕鍏叡鎶借薄涓庡幓閲嶅叆搴?txt` 鏈敼鍐呭(浠呮柊璁″垝鏍囨敞)

## 2026-08-15 [宸插畬鎴怾 - 鏍囩殑鐗╂弿杩颁笌鍛ㄥ洿鎯呭喌鎶撳彇

- **鏁版嵁缁撴瀯鎵╁睍**:
  - `AuctionDetail` 鏂板 `description` 瀛楁(鏍囩殑鐗╂弿杩?
  - 鏂板 `transportation`/`education`/`shopping`/`medical`/`parks` 瀛楁(鍛ㄥ洿鎯呭喌)
  - 鎵€鏈夌被鍒兘鏈?`distance` 瀛楁

- **鍏媿缃戞爣鐨勭墿鎻忚堪鎶撳彇**:
  - 鍦?`skills/gpai-crawler/scripts/crawler.py` 鐨?`_fetch_detail_images_impl` 涓坊鍔?  - XPath: `//div[@class='d-article']`

- **闃块噷璧勪骇鏍囩殑鐗╂弿杩版姄鍙?*:
  - 鍦?`skills/ali-assets-crawler/scripts/crawler.py` 鐨?`_fetch_detail_images` 涓坊鍔?  - XPath: `//div[@id='J_NoticeDetail']`

- **闃块噷璧勪骇鍛ㄥ洿鎯呭喌鎶撳彇**:
  - 鏂板嚱鏁?`_fetch_surrounding_info` 鍦?`skills/ali-assets-crawler/scripts/crawler.py` 涓?  - 鎶撳彇閫昏緫: 婊氬姩鍒?鏍囩殑鐗╀綅缃? 鈫?绛夊緟gaode iframe 鈫?鍒囨崲5涓富鏍囩 鈫?鎶撳彇浜岀骇鏍囩鏁版嵁
  - 浣跨敤鑻辨枃key瀛樺偍(transportation/education/shopping/medical/parks)
  - 濡傛灉璇︽儏椤垫病鏈塯aode iframe锛岃繑鍥炵┖鐨刾oi鏁版嵁
  - 鏁欒偛鐨?骞煎効鍥?浜岀骇鏍囩鍙兘琚湴鍥炬爣璁伴伄鎸★紝闇€鐢╢orce click鎴栬烦杩?
- **淇鐨勯棶棰?*:
  - 瀛樺偍鏃朵娇鐢ㄤ腑鏂噆ey瀵艰嚧缁撴灉涓虹┖锛屾敼涓鸿嫳鏂噆ey
  - 鍒犻櫎澶氫綑鐨剆kip_all鍙傛暟
  - 澧炲姞鏍囩鍒囨崲鍚庣殑绛夊緟鏃堕棿

- **鏂囨。鏇存柊**:
  - `skills/ali-assets-crawler/references/xpath_rules.md` 娣诲姞鏍囩殑鐗╂弿杩板拰鍛ㄥ洿鎯呭喌XPath瑙勫垯
  - `plans/闃块噷璧勪骇鏍囩殑鐗╂弿杩颁笌鍛ㄥ洿鎯呭喌鎶撳彇瀹炵幇璁″垝.md` 璁板綍瀹炵幇璁″垝

- **娴嬭瘯**: pytest 39 鍏ㄧ豢
## 2026-08-16

- [已完成] 阿里资产周围情况抓取: 健壮性升级(基于DOM实测)
  - **关键发现**: irstPoiName--/childPoiName-- 仅出现在激活/未激活标签上, 不是所有标签共有; 点击定位改用容器选择器 div.h-48px p(主) / div.h-44px p(二级) + has_text, 避免漏掉未激活标签
  - **激活判定**: 主标签 p[class*='activePoiName--']、二级标签 p[class*='selectedChildPoiName--'] 取文本比对
  - **等待参数**: iframe等待上限 300s; 找到后随机0.5~1.5s; 主/二级标签点击后随机1.5~2.5s; page隐式等待上限10s
  - **切换验证兜底**: 点击后校验激活标签文本, 不一致则等3s重试(最多3次); 覆盖A切换失败重试 / B有数据记录 / C无数据再等2s确认三态
  - **修复**: rame.set_default_timeout 不存在 → 改 page.set_default_timeout; 点击改用 orce=True 防遮挡(解决幼儿园被地图marker遮挡超时)
  - 实测两链接(1069214519000 / 1065611814594)全量抓取成功, 购物中心切换未生效场景被重试逻辑兜底成功
  - **测试**: pytest 39 全绿; 临时调试脚本已清理

## 2026-08-16 [已完成] - description/location 入库 + poi 四态断点续传

- **DB 持久化扩展**:
  - ali `data` 写库: 新增 `description`、`location`(`_fetch_location`, 选择器 `//div[contains(@class,'item-address')]`)
  - ali `data.poi` 四态: 本次抓到(含各项为空)也回写, 避免重复刷新; 未抓到回填 DB 原有 `poi`
  - gpai `data` 写库: 新增 `description`
- **断点续传升级(仅阿里)**:
  - `skip_complete` 从纯图片清单改为富结构 `{item_id: {"images":[...], "poi":{...}|None}}`
  - 图片齐 + poi 在库 → 跳过; poi 缺 → 开浏览器补周围 `location` 字段; 图缺 → 离线补图(原有逻辑)
  - 新增 `db.get_source_poi(source) -> {item_id: dict|None}`
- **新增临时补填脚本** `scripts/fill_description_location.py`:
  - 巡检 DB 中缺 `description`(或阿里缺 `location`)的记录, 复用 skill 内部抓取接口补填后 upsert
  - 用法: `python scripts/fill_description_location.py [--source ali|gpai|all] [--limit N]`
- **文档**: ali SKILL.md 增加 `_fetch_location` 接口行与 `data` 写库/补填说明; 参数重命名 `skip_complete_images` → `skip_complete`
- **测试**: compile + pytest 待跑

## 2026-08-16 [已完成] - 标的描述按 docs 分段提取 + 存量重提取回填

- **问题**: 两爬虫 `_fetch_description` 原返回整篇 `d-article`/`J_NoticeDetail` 内文(含法院公告抬头), 不符合 `docs/初步信息.txt` 第15/65行「只提取 拍卖标的:… 到最近 X、 之间文字」的要求
- **新增** `utils/description.py::extract_auction_description`:
  - 起点标记 `拍卖标的(?:物)?[:：]`(兼容中英文冒号); 终点取标记后**最近**的 `[一二三四五六七八九十]+、`
  - 截断后过短(<6字)回退整段防误截; 无标记原样返回 -- 纯函数幂等
- **接入**: gpai/ali 两爬虫 `_fetch_description` 包一层解析; 回填脚本复用自动获得修正
- **存量回填**: `fill_description_location.py` 新增 `--reparse-description`, 对已存整篇(仍含「拍卖标的」)无条件 `extract` 后 upsert; 可重复跑幂等
- **无法处理打印链接**: 浏览器补填与 `--reparse-description` 中, 提取异常/描述为空/无法分段均打印房源 URL
- **测试**: 新增 `tests/test_description.py` 6 例; pytest 45 全绿
- **执行回填**: `python scripts/fill_description_location.py --reparse-description` 已跑, gpai 20 条重提取成功、0 失败(ali 存量描述均不含标记无需处理); 校验幂等 true
- **回退策略确认**: 无法按要求分段时保持回退整段原文(防丢数据); 修正无「拍卖标的」标记时不再按 `X、` 错位截断, 直接返回全文(新增回归用例, pytest 46 全绿)

## 2026-08-16 [已完成] - 描述提取新增「第N条」规则(需求.txt)

- **新规则(需求.txt)**: 描述通常以「第一条/第二条…」(或「第1条」)分节, 拍卖标的标记位于某一节内; 取「包含标记的 第N条」起到「第N+1条」前的文字, 换行替换为空格并去首尾空格
- **实现**: `utils/description.py` 新增 `_SECTION`(第N条)匹配, 优先按 第N条→第N+1条 截取; 无此分节结构时回退原「拍卖标的…→最近 X、」规则; 无标记/过短仍回退整段
- **测试**: 新增 2 例(中文序号样例、阿拉伯序号), pytest 48 全绿
- **数字空格兼容**: `第N条` 序号与文字间允许前后空格(`第\s*...\s*条`, 如 `第 1 条`/`第1 条`/`第 1条`), 新增回归用例, pytest 49 全绿

## 2026-08-16 [已完成] - log.txt 分析: 假失败 vs 阿里占位描述

- **log 里 gpai 6 条「无法分段」为假失败**: `--reparse-description` 原用 LIKE '%拍卖标的%', 把已分段正文里自然出现的「拍卖标的」(无冒号)当待处理; 已改为 PostgreSQL 正则 `data->>'description' ~ '拍卖标的(物)?[:：]'`, 只挑含真实冒号标记的整篇, 重跑后 0 更新 0 失败(公拍 20 条早已提取成功)
- **真正未提取成功的是阿里**: 58 条描述全为「公告详情加载…」占位文案, 63 条缺失; 根源是 J_NoticeDetail 动态加载, 抓取时拿到占位符
  - `ali._fetch_description` 增加轮询(最多 10×1.5s)等真实内容; 占位/过短视为无描述返回空串(不入库)
  - 浏览器补填 `_missing` 把含「公告详情」占位也视为缺失, 重新抓取覆盖; 仍无法抓到的打印链接
- **验证**: py_compile + pytest 49 全绿; `--reparse-description` 重跑干净(0 失败)

## 2026-08-16 [已完成] - 「标的物属性」区块采集(新字段 data.property_info)

- **探测结论**: 部分阿里详情页(诉讼资产 susong 模板)的 `J_NoticeDetail` 始终只有「公告详情加载中」占位, 无「拍卖标的」描述; 但页面存在「标的物属性」区块(无class 内联样式标题div), 其后为 `流转方式/物业类型/朝向/户型/建筑面积…` 键值对, 之后是「标的物详情描述」等后续区块; sf-item 模板一般无此区块
- **实现**:
  - `utils/description.py` 新增 `extract_property_info`(从「标的物属性」起到下一个主要标题 标的物详情描述/竞买人条件/第N条/X、 止, 换行折叠空格)
  - `app/schemas/listing.py` `AuctionDetail` 新增 `property_info: str = ""`
  - ali `_fetch_property_info(page)`: 定位 `//div[normalize-space()='标的物属性']`, JS 上溯取首个文本明显变长的容器, 交 `extract_property_info` 截取; `_fetch_detail` 组装
  - 写库(爬取 main / 补填 worker): `data["property_info"]` 新字段, 不覆盖 `description`
- **测试**: `extract_property_info` 3 例; pytest 全绿

## 2026-08-16 [已完成] - 「标的物属性」改为结构化存储
  - 用户确认: 标的物属性本身就是「键：值」对, 直接结构化存储, 不必折叠成整段字符串
  - `utils/description.py` `extract_property_info` 返回 `dict`: 从「标的物属性」起到下一主要标题(标的物详情描述/竞买人条件/第N条/X、)止, 按 `键：值`(`：` 同行或独占一行、值可续行)解析为 {属性名: 值}, 值内换行折叠空格; 无区块返回 `{}`
  - `app/schemas/listing.py` `AuctionDetail.property_info: str` → `dict`
  - ali `_fetch_property_info(page)` 返回 `dict`; 写库 `data["property_info"]` 为结构化 dict(JSONB 原生存储)
  - 测试: 结构断言 + 同行键值/多行值用例; pytest 全绿
- **文档**: 两 skill SKILL.md description 说明同步更新

## 2026-08-16 [已完成] - fill 脚本 bug 修复 + wart 收敛
- **关键 bug**: `Listing.data` 列是 PostgreSQL `json`(非 jsonb), fill/probe 的 `_missing` 里 `data->'property_info' = '{}'::jsonb` 会抛 `operator does not exist: json = jsonb`; 改用 `data->>'property_info'` 文本比较(= '' 或 = '{}')
- **wart 成因**: ali 一批记录既无 description 又无 property_info(页面确实没有), 每次 fill 都被 `_missing` 筛中、抓取全空、永不收敛(实测 121 条 ali 全缺 desc+prop, 其中 58 条已有 location)
- **收敛处理**: worker 抓到 desc/loc/prop 全空(或 gpai desc 空)时打 `data["_empty"] = True` 标记, `_missing` 排除 `_empty` 记录, 不再反复开浏览器
- **docstring 同步**: 注明阿里会填 property_info, 并提醒 json 文本比较陷阱
- **微优化**: ali worker 在 DB 已存 property_info 时跳过重复抓取, 打印「属性已存 N 项,跳过抓取」
- probe `_missing_urls` 同步修复同款 json/jsonb bug
- pytest 52 全绿

## 2026-08-16 [已完成] - data 结构探针 + 播放图标/重复图清洗
- alias 详情探针 `scripts/probe_ali_detail.py`: 打印将入库的 data 结构(images/raw/property_info/description/location/poi), 不写 DB
- `_fetch_images` 源头过滤: 剔除轮播混入的短视频播放图标(imgextra CDN / `tps-72-72.png`), 并按 URL 去重(同一图被重复引用)
- `scripts/clean_images_mixed.py`: 清洗存量 DB data->images, 去掉图标/占位/重复(`--remove-files` 连带删孤儿本地文件); dry-run 保驾
- 实测: 7 条含图标记录全部清洗(共去掉 14 张), DB 引用文件齐全; pytest 52 全绿

## 2026-08-16 [已完成] - 标的物属性优先于标的物描述
- susong 模板页面属性区块有值时不再抓描述(描述恒占位/空, 免 10×1.5s 轮询)
- `_fetch_detail` / 补填 worker: `property_info` 非空则跳过 `_fetch_description`; `fill` 判缺 SQL 视 `property_info` 已存为不缺描述
- 探针实测 1075845060425/1074884817646 属性结构化全部成功

## 2026-08-16 [已完成] - 补填脚本并行化 + 标签页复用

- **fill_description_location.py 并行化**:
  - 两源(`ali`/`gpai`)通过 `asyncio.gather` 同时起浏览器并行补填
  - 每源只开固定 `--workers` 个标签页(默认 3)**复用轮转**,逐条导航复用,不再逐条 `new_page`/close
  - `_open_detail_page`(ali)新增可选 `page` 参数: 传 key-value 复用已有页,不传保持原逻辑新建页(兼容 crawl 主流程)
  - 新增 `--workers` 参数; 逐条抓完即 upsert(保持逐条写)
  - 节流: 每个标签页每次开页面前随机等 0.8-2s,每 5 页额外随机等 2-3.5s
- **测试**: py_compile + pytest 39 全绿

## 2026-08-16 [已完成] - 「标的物介绍」表格兜底为属性 + 滑块把手 ID 修复 + 调研

### 「标的物介绍」表兜底(老模板)
- 探测确认: 老模板(sf-item)详情页无「标的物属性」区块, 但 `标的物介绍` tab(`div.addition-desc.J_Content`)内含结构化 `<table>`(每行 `<td>键</td><td>值</td>`, 分组行 rowspan 组名列可忽略)
- 新增 `ali._fetch_property_info_from_intro(page)`: JS 取该表末两格为键/值, 返回 dict; `_fetch_detail` 与 fill worker 在 `_fetch_property_info` 为空时兜底调用
- 实测: 老模板 1074812989697/1065500612065/1063648591260 等 9~14 个键全部抓到; 真全空页(如 1071316609892/1066999553311)标的物介绍仅附件无表 → 落 `_empty`
- fill `_empty` 判定修正: 只看 `desc/prop` 是否全空(原 `not(desc or loc or prop)` 会被已存在的 location 拦住 → wart 复发); location 单独存在仍照存
- fill `--source ali --limit 30` 实测: 21 条抓到属性, 9 条 `_empty` 收敛
- **DB 完整性核对**: 探针 `[:300]` 打印截断(`截至2026…`/`…建`)仅是显示, 库内 `欠费情况`/`处置参考价`/`备注` 均为全文

### 滑块把手 ID 修复 + 调研
- **把手 ID 疑似笔误**: 社区/官方 DOM 为 `nc_1_n1z`(n1z), 代码原写 `nc_1_nz1`(nz1); 现两候选都检测(`_dom_blocked`/`_try_auto_slide`), 测试断言同步
- **子代理调研结论**(GitHub/CSDN/StackOverflow/Reddit 等):
  - 淘宝滑块是「环境+行为+指纹」多维风控, 纯自动拖动无 2024+ 可持续复现的开源方案; Selenium 驱动下人工拖都可能不过, `_try_auto_slide` 从未成功非代码 bug
  - 针对淘宝 nc 滑块的开源项目全部停更于 2022 前; 活跃项目对的是阿里云 Captcha2.0(非淘宝 x5sec)
  - 替代路线优先级: ① 官方 TOP 司法拍卖 API(`taobao.auction.gov.auctions.get` / `auction.gov.get.auction.info`, 免滑块, 需 ISV AppKey) ② 低频浏览器直取 + storage_state 会话复用(x5sec 约 30 分钟, 登录 profile 可复用几天) ③ 打码平台只解决缺口识别、不解决行为判定
  - x5sec cookie 有效约 30 分钟; punish 时长无官方/实测精确数据, 按「触发即换 IP + 降频 + 干净 profile」设计
- pytest 52 全绿

### 待办
- [ ] ali 全量补填(第二轮 limit 0 进程被提前结束, 仍欠 ~91 条; 需人工滑块配合)
- [ ] 评估 TOP 官方司法拍卖 API 可行性(能否申请 AppKey / 是否免授权)作为爬虫替代


## 2026-08-18 [已完成] - 公拍网 property_info(标的物介绍表格)回填

- 调研定位: 77 条 gpai 中 8 条 description 无面积; 根因是面积只在「标的物介绍」tab 的调查情况表/审批表(d-article2)里, 原 _fetch_description 只抓竞买公告(d-article)
- 8 条分类: 52956/52951/52950/53044/53071 面积在调查表; 53063 多列权证表(desc 有 67.33/208.59 无「平方米」字样致漏判); 53061 面积埋于段落(91.49平方米, 公告无); 52947 审批表+公告均有(117.12)
- utils/description.py 新增 gpai 表格拍扁器:
  - _GpaiTableParser(HTMLParser) 展开 rowspan/colspan(_expand_gpai_grid), _gpai_row_cells 去重 + 起始列
  - _flatten_gpai_table 三形态: 两列 label/value(值列 colspan 合一)、rowspan 分组(组名丢弃保留子键/值, 组+单值保留 {组名:值})、多列多行权证表(行首标识列做前缀键, 如 建筑面积_779弄53号301室)
  - extract_gpai_property_info(intro_html, announce_text, intro_text): 面积优先级 表内键(建筑总面积/建筑面积…)→ 公告段落 regex → 标的物介绍段落 regex
- crawler 接线: 新增 _fetch_property_info(page) 定位 d-article2 中调查情况表/审批表块取 innerHTML+inner_text(排除竞买公告/须知/重要提示/竞买记录), 接入 _fetch_detail_impl 与 main() 写库 merge(detail.property_info 非空才覆盖)
- scripts/fill_description_location.py gpai 分支: 同时抓 desc + property_info; 两者全空才打 _empty(原只看 desc)
- 真实 HTML 验证: 52951/53044/53063/52950/53071 五个样本全部正确拍扁(52963 单格说明行 <2 单元格跳过, 修复越权键); 53044 rowspan 组、53063 多列前缀均符合预期
- 测试: test_gpai_crawler.py 新增 7 个契约测试(两列/rowspan 组/组+单值/多列多行/面积回退公告/面积回退介绍段落/空表); pytest 64 全绿

### 待办
- [ ] gpai 全量回填 77 条(跑 fill 或 crawl_gpai)
- [ ] ali 全量补填(第二轮欠 ~91 条; 需人工滑块配合)
