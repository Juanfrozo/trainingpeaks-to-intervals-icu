"""Inspect real TP planned workouts and icu events to understand shapes."""

import asyncio
import json
import os
from datetime import date, timedelta

import httpx
from dotenv import load_dotenv


async def tp_token(client: httpx.AsyncClient, cookie: str) -> str:
    r = await client.get(
        "https://tpapi.trainingpeaks.com/users/v3/token",
        headers={"Cookie": f"Production_tpAuth={cookie}"},
    )
    r.raise_for_status()
    return r.json()["token"]["access_token"]


async def tp_athlete_id(client: httpx.AsyncClient, token: str) -> int:
    r = await client.get(
        "https://tpapi.trainingpeaks.com/users/v3/user",
        headers={"Authorization": f"Bearer {token}"},
    )
    r.raise_for_status()
    user = r.json().get("user", r.json())
    return user.get("personId")


async def main() -> None:
    load_dotenv()
    cookie = os.environ["TP_AUTH_COOKIE"]
    api_key = os.environ["ICU_API_KEY"]
    athlete = os.environ["ICU_ATHLETE_ID"]

    start = date.today()
    end = start + timedelta(days=14)

    async with httpx.AsyncClient(timeout=30.0) as c:
        token = await tp_token(c, cookie)
        aid = await tp_athlete_id(c, token)
        print(f"TP athlete id = {aid}")

        url = (
            f"https://tpapi.trainingpeaks.com/fitness/v6/athletes/{aid}"
            f"/workouts/{start.isoformat()}/{end.isoformat()}"
        )
        r = await c.get(url, headers={"Authorization": f"Bearer {token}"})
        print(f"TP workouts {start}..{end} -> {r.status_code}")
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict) and "workouts" in data:
            wks = data["workouts"]
        else:
            wks = data
        print(f"TP workouts count: {len(wks)}")

        if wks:
            print("\n--- TP first workout (raw keys) ---")
            print(sorted(wks[0].keys()))
            print("\n--- TP first workout (compact) ---")
            sample = {
                k: wks[0].get(k)
                for k in (
                    "workoutId",
                    "workoutDay",
                    "title",
                    "description",
                    "workoutTypeValueId",
                    "totalTimePlanned",
                    "totalTime",
                    "distancePlanned",
                    "distance",
                    "tssPlanned",
                    "tss",
                    "completed",
                    "structure",
                    "startTimePlanned",
                )
            }
            print(json.dumps(sample, indent=2, default=str)[:2000])

            wid = wks[0]["workoutId"]
            details_url = (
                f"https://tpapi.trainingpeaks.com/fitness/v6/athletes/{aid}"
                f"/workouts/{wid}/details"
            )
            d = await c.get(details_url, headers={"Authorization": f"Bearer {token}"})
            print(f"\nTP details endpoint -> {d.status_code}")
            if d.status_code == 200:
                dj = d.json()
                print(f"detail keys: {sorted(dj.keys()) if isinstance(dj, dict) else type(dj)}")
                if isinstance(dj, dict) and "structure" in dj:
                    print("structure preview:")
                    print(json.dumps(dj["structure"], indent=2, default=str)[:1500])

        # Look at icu events in the same window
        auth = httpx.BasicAuth("API_KEY", api_key)
        async with httpx.AsyncClient(timeout=30.0, auth=auth) as ic:
            params = {
                "oldest": start.isoformat(),
                "newest": end.isoformat(),
            }
            r = await ic.get(
                f"https://intervals.icu/api/v1/athlete/{athlete}/events", params=params
            )
            print(f"\nicu events {start}..{end} -> {r.status_code}")
            r.raise_for_status()
            events = r.json()
            print(f"icu events count: {len(events)}")
            if events:
                print("--- icu first event keys ---")
                print(sorted(events[0].keys()))
                print("\n--- first 2 events (compact) ---")
                for e in events[:2]:
                    print(
                        json.dumps(
                            {
                                k: e.get(k)
                                for k in (
                                    "id",
                                    "start_date_local",
                                    "type",
                                    "category",
                                    "name",
                                    "description",
                                    "external_id",
                                    "moving_time",
                                    "atl",
                                )
                            },
                            indent=2,
                            default=str,
                        )
                    )


if __name__ == "__main__":
    asyncio.run(main())
