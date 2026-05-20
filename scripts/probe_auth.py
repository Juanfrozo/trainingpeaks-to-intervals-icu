"""One-off auth smoke test against TP + intervals.icu APIs."""

import asyncio
import os
import sys

import httpx
from dotenv import load_dotenv


async def probe_tp(cookie: str) -> None:
    print("[TP] Exchanging cookie for OAuth token...")
    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.get(
            "https://tpapi.trainingpeaks.com/users/v3/token",
            headers={
                "Cookie": f"Production_tpAuth={cookie}",
                "Accept": "application/json",
            },
        )
        print(f"[TP]   token endpoint -> {r.status_code}")
        if r.status_code != 200:
            print(f"[TP]   body: {r.text[:300]}")
            raise SystemExit("TP token exchange failed")
        token = r.json()["token"]["access_token"]
        print(f"[TP]   got access_token (len={len(token)})")

        print("[TP] Fetching /users/v3/user ...")
        u = await client.get(
            "https://tpapi.trainingpeaks.com/users/v3/user",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        print(f"[TP]   user endpoint -> {u.status_code}")
        if u.status_code != 200:
            print(f"[TP]   body: {u.text[:300]}")
            raise SystemExit("TP user fetch failed")
        data = u.json().get("user", u.json())
        person_id = data.get("personId")
        athletes = data.get("athletes", [])
        print(
            f"[TP]   personId={person_id}, athletes={len(athletes)}, "
            f"first_name={data.get('firstName')!r}"
        )


async def probe_icu(api_key: str, athlete_id: str) -> None:
    print(f"[icu] Fetching athlete {athlete_id}...")
    auth = httpx.BasicAuth("API_KEY", api_key)
    async with httpx.AsyncClient(timeout=30.0, auth=auth) as client:
        r = await client.get(f"https://intervals.icu/api/v1/athlete/{athlete_id}")
        print(f"[icu]   athlete endpoint -> {r.status_code}")
        if r.status_code != 200:
            print(f"[icu]   body: {r.text[:300]}")
            raise SystemExit("icu auth failed")
        d = r.json()
        print(f"[icu]   name={d.get('name')!r}, ftp={d.get('icu_ftp')}, sex={d.get('sex')}")


async def main() -> None:
    load_dotenv()
    cookie = os.environ.get("TP_AUTH_COOKIE")
    api_key = os.environ.get("ICU_API_KEY")
    athlete = os.environ.get("ICU_ATHLETE_ID")
    if not (cookie and api_key and athlete):
        print("missing env vars", file=sys.stderr)
        raise SystemExit(1)
    await probe_tp(cookie)
    await probe_icu(api_key, athlete)
    print("\nALL GOOD.")


if __name__ == "__main__":
    asyncio.run(main())
