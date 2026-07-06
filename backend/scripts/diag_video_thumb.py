"""실 NAS 진단: 동영상 아이템의 썸네일이 왜 리스트에서 안 보이는지 확정한다.

목록에서 첫 동영상 아이템을 찾아 (1) additional.thumbnail 구조(cache_key 유무·
sm/m/xl 상태), (2) 실제 Thumbnail get 응답(이미지 바이트 vs JSON 에러)을 찍는다.
사진 아이템과 나란히 비교해 "동영상만" 다른지 드러낸다.

사용법 (backend 디렉터리에서):
    DSM_BASE_URL=https://192.168.0.10 DSM_PORT=5001 DSM_VERIFY_TLS=false \
    DSM_ACCOUNT=<계정> DSM_PASSWD=<비번> \
    python scripts/diag_video_thumb.py [team|personal]

주의: 읽기 전용. 파일을 바꾸지 않는다.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

import httpx

# app 패키지를 어디서 실행하든(호스트 backend/, 컨테이너 /app, stdin 파이프)
# import 가능하게 — __file__ 비의존(stdin 실행 시 __file__ 없음).
for _p in (os.getcwd(), os.path.join(os.getcwd(), "backend")):
    if os.path.isdir(os.path.join(_p, "app")) and _p not in sys.path:
        sys.path.insert(0, _p)
        break

from app.dsm.client import DsmClient  # noqa: E402


def _ns(space: str, api: str) -> str:
    return api.replace("SYNO.Foto", "SYNO.FotoTeam") if space == "team" else api


async def main() -> None:
    space = sys.argv[1] if len(sys.argv) > 1 else "team"
    base = os.environ["DSM_BASE_URL"].rstrip("/")
    port = os.environ.get("DSM_PORT", "5001")
    verify = os.environ.get("DSM_VERIFY_TLS", "true").lower() not in ("false", "0", "no")
    account = os.environ["DSM_ACCOUNT"]
    passwd = os.environ["DSM_PASSWD"]

    async with httpx.AsyncClient(verify=verify, timeout=30) as http:
        dsm = DsmClient(f"{base}:{port}/webapi", http)
        login = await dsm.login(account, passwd)
        sid = login.sid
        print(f"[login] ok as {account}, space={space}\n")

        # 목록에서 동영상 1개 + 사진 1개 찾기 (썸네일 additional 포함).
        data = await dsm.call(
            _ns(space, "SYNO.Foto.Browse.Item"),
            "list",
            version=1,
            sid=sid,
            extra={
                "offset": 0,
                "limit": 200,
                "additional": json.dumps(["thumbnail", "resolution", "video_meta"]),
            },
        )
        items = data.get("list", [])
        video = next((it for it in items if it.get("type") == "video"), None)
        photo = next((it for it in items if it.get("type") != "video"), None)

        # 라이브러리 전체 동영상 썸네일 상태 조사 — sm broken 비율과, 그중 m/xl로
        # 살릴 수 있는 비율을 집계해 "sm이 원인인지 + 폴백이 먹히는지" 확증한다.
        print("[survey] 전체 동영상 썸네일 상태 스캔 중...")
        offset = 0
        vids = 0
        sm_broken = 0
        sm_broken_m_ready = 0
        sm_broken_all_broken = 0
        no_cache_key = 0
        while True:
            page = (await dsm.call(
                _ns(space, "SYNO.Foto.Browse.Item"), "list", version=1, sid=sid,
                extra={"offset": offset, "limit": 1000,
                       "additional": json.dumps(["thumbnail"])},
            )).get("list", [])
            for it in page:
                if it.get("type") != "video":
                    continue
                vids += 1
                th = (it.get("additional") or {}).get("thumbnail") or {}
                if not th.get("cache_key"):
                    no_cache_key += 1
                    continue
                if th.get("sm") != "ready":
                    sm_broken += 1
                    if th.get("m") == "ready" or th.get("xl") == "ready":
                        sm_broken_m_ready += 1
                    else:
                        sm_broken_all_broken += 1
            if len(page) < 1000:
                break
            offset += 1000
        print(f"  동영상 총 {vids}개")
        print(f"  sm 정상(ready)          : {vids - sm_broken - no_cache_key}")
        print(f"  sm broken → m/xl로 복구가능: {sm_broken_m_ready}  ← 배포하면 이만큼 살아남")
        print(f"  sm broken → 전부 broken   : {sm_broken_all_broken}  ← 폴백 타일 표시")
        print(f"  cache_key 없음            : {no_cache_key}\n")

        # 앱이 실제로 쓰는 Thumbnail API 버전 확인 (앱은 pick_version(None)=max).
        info = await dsm.query_api_info(
            ("SYNO.Foto.Thumbnail", "SYNO.FotoTeam.Thumbnail")
        )
        for api_name, ep in info.items():
            print(f"[api] {api_name}: path={ep.path} "
                  f"min={ep.min_version} max={ep.max_version} "
                  f"→ 앱이 쓰는 version={ep.pick_version(None)}")
        print()

        thumb_api = _ns(space, "SYNO.Foto.Thumbnail")

        # 특정 아이템 직접 지정(실패한 그 항목) — DIAG_ITEM_ID/DIAG_CACHE_KEY.
        probe_id = os.environ.get("DIAG_ITEM_ID")
        probe_ck = os.environ.get("DIAG_CACHE_KEY")
        targets = [("VIDEO", video), ("PHOTO", photo)]
        if probe_id and probe_ck:
            targets.insert(0, ("TARGET", {
                "id": int(probe_id), "type": "?", "filename": "(지정)",
                "additional": {"thumbnail": {"cache_key": probe_ck}},
            }))

        for label, it in targets:
            if not it:
                print(f"[{label}] 목록에서 찾지 못함 (limit 200 내)\n")
                continue
            add = it.get("additional", {}) or {}
            thumb = add.get("thumbnail", {}) or {}
            ck = thumb.get("cache_key", "")
            print(f"[{label}] id={it.get('id')} type={it.get('type')} "
                  f"filename={it.get('filename')!r}")
            print(f"  thumbnail dict : {json.dumps(thumb, ensure_ascii=False)}")
            if not ck:
                print("  (cache_key 없음 → 썸네일 요청 자체 불가)\n")
                continue
            # 사이즈별로 (1) 앱 경로(pick_version=max) (2) version=1 직접호출을
            # 각각 시도해 어느 조합이 200을 주는지 대조한다.
            for sz in ("sm", "m", "xl"):
                # (1) 앱과 동일: endpoint.pick_version(None) + entry.cgi path
                app_params = {
                    "api": thumb_api, "version": str(info[thumb_api].pick_version(None)),
                    "method": "get", "id": it.get("id"), "cache_key": ck,
                    "type": "unit", "size": sz, "_sid": sid,
                }
                ra = await http.get(f"{base}:{port}/webapi/{info[thumb_api].path}",
                                    params=app_params)
                # (2) version=1 직접
                v1_params = {**app_params, "version": "1"}
                rv = await http.get(f"{base}:{port}/webapi/entry.cgi", params=v1_params)

                def _tag(r):
                    ct = r.headers.get("content-type", "")
                    if r.status_code != 200:
                        return f"HTTP {r.status_code}"
                    if ct.startswith("application/json"):
                        return f"JSON에러 {r.content[:80]!r}"
                    return f"OK image {len(r.content)}B"

                print(f"  size={sz:>2}: 앱경로(v{app_params['version']})={_tag(ra)}  |  "
                      f"직접(v1)={_tag(rv)}")
            print()

        # 앱의 실제 읽기 경로 검증 — raw DSM이 아니라 DsmPhotoSource.items()가
        # 프론트로 넘기는 PhotoItem.cache_key/type을 그대로 확인한다. 여기서
        # 동영상 cache_key가 비면 프론트 <img>가 실패하는 진짜 원인이 잡힌다.
        if video is not None:
            from datetime import date

            from app.photos.dsm_source import DsmPhotoSource

            src = DsmPhotoSource(dsm, sid)
            day = date.fromtimestamp(video.get("time", 0)).isoformat()
            day_items = await src.items(space, day)
            vid_id = str(video.get("id"))
            pi = next((i for i in day_items if i.id == vid_id), None)
            print(f"[app.items()] {space} {day} → {len(day_items)}개")
            if pi is None:
                print(f"  ⚠️ 동영상 {vid_id}가 items()에 없음 "
                      f"(taken_at 그룹핑/휴지통 필터 확인 필요)\n")
            else:
                print(f"  동영상 PhotoItem: id={pi.id} type={pi.type!r} "
                      f"cache_key={pi.cache_key!r}")
                print(f"  → 프론트 URL cache_key {'있음(정상)' if pi.cache_key else '비어있음(원인!)'}\n")

        await dsm.logout(sid)


if __name__ == "__main__":
    asyncio.run(main())
