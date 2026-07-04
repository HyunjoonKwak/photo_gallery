"""실 NAS 진단: 동영상 아이템의 썸네일이 왜 리스트에서 안 보이는지 확정한다.

목록에서 첫 동영상 아이템을 찾아 (1) additional.thumbnail 구조(cache_key 유무·
sm/m/xl 상태), (2) 실제 Thumbnail get 응답(이미지 바이트 vs JSON 에러)을 찍는다.
사진 아이템과 나란히 비교해 "동영상만" 다른지 드러낸다.

사용법 (backend 디렉터리에서):
    DSM_BASE_URL=https://192.168.1.113 DSM_PORT=5001 DSM_VERIFY_TLS=false \
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

        for label, it in (("VIDEO", video), ("PHOTO", photo)):
            if not it:
                print(f"[{label}] 목록에서 찾지 못함 (limit 200 내)\n")
                continue
            add = it.get("additional", {}) or {}
            thumb = add.get("thumbnail", {}) or {}
            print(f"[{label}] id={it.get('id')} type={it.get('type')} "
                  f"filename={it.get('filename')!r}")
            print(f"  additional keys: {sorted(add.keys())}")
            print(f"  thumbnail dict : {json.dumps(thumb, ensure_ascii=False)}")
            ck = thumb.get("cache_key", "")
            print(f"  cache_key      : {ck!r}")

            # 실제 sm 썸네일 요청 결과 확인.
            if ck:
                url = f"{base}:{port}/webapi/entry.cgi"
                params = {
                    "api": _ns(space, "SYNO.Foto.Thumbnail"),
                    "version": "1",
                    "method": "get",
                    "id": it.get("id"),
                    "cache_key": ck,
                    "type": "unit",
                    "size": "sm",
                    "_sid": sid,
                }
                r = await http.get(url, params=params)
                ct = r.headers.get("content-type", "")
                head = r.content[:120]
                print(f"  GET thumb sm   : status={r.status_code} content-type={ct!r} "
                      f"bytes={len(r.content)}")
                if ct.startswith("application/json"):
                    print(f"    JSON error → {head!r}")
                else:
                    print(f"    image head  → {head[:16]!r}...")
            else:
                print("  (cache_key 없음 → 썸네일 요청 자체 불가)")
            print()

        await dsm.logout(sid)


if __name__ == "__main__":
    asyncio.run(main())
