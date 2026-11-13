#!/usr/bin/env python3
"""보관(archive) 브랜치에서 6개월(KEEP_DAYS=180)이 지난 낙찰 파일을 달마다 압축 파일 하나로 묶어 GitHub 릴리스에 올리고,
올리기에 성공한 경우에만 archive 브랜치에서 지운다. (올리기에 실패하면 아무것도 지우지 않는다.)

- 한 달이 통째로 기준일(오늘 - KEEP_DAYS)보다 오래됐을 때 그 달을 묶는다. (그래서 실제로는 6~7개월 보관)
- 릴리스 이름: archive-YYYY-MM (제목 "2026-11월"), 파일 하나: MarketPrices-YYYY-MM.tar.gz (전체 시장)
- 필요한 환경: ARCHIVE_DIR(archive 브랜치 폴더), gh 명령과 GH_TOKEN
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile

KST = datetime.timezone(datetime.timedelta(hours=9))
KEEP_DAYS = int(os.environ.get("KEEP_DAYS", "180"))
ARCHIVE_DIR = os.environ.get("ARCHIVE_DIR", "").strip()


def log(*a):
    print(*a, flush=True)


def gh_upload(tag, path):
    """릴리스(없으면 만들고)에 파일을 올린다. 성공하면 True."""
    ok = subprocess.run(["gh", "release", "view", tag], capture_output=True).returncode == 0
    if not ok:
        r = subprocess.run(["gh", "release", "create", tag, "--title", "%s월 낙찰 내역" % tag.replace("archive-", ""),
                            "--notes", "오래된 낙찰 내역 보관 파일입니다. 내려받아 보관하세요."],
                           capture_output=True, text=True)
        if r.returncode != 0:
            log("  릴리스 만들기 실패:", r.stderr.strip()[:300])
            return False
    r = subprocess.run(["gh", "release", "upload", tag, path, "--clobber"], capture_output=True, text=True)
    if r.returncode != 0:
        log("  릴리스 올리기 실패:", r.stderr.strip()[:300])
        return False
    return True


def month_end(ym):
    y, m = int(ym[:4]), int(ym[5:7])
    nxt = datetime.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - datetime.timedelta(days=1)


def main(upload=gh_upload):
    if not ARCHIVE_DIR or not os.path.isdir(os.path.join(ARCHIVE_DIR, "lots")):
        log("보관할 낙찰 파일이 없습니다.")
        return 0
    today = datetime.datetime.now(KST).date()
    cutoff = today - datetime.timedelta(days=KEEP_DAYS)
    lots = os.path.join(ARCHIVE_DIR, "lots")
    months = {}                       # {YYYY-MM: {시장: [날짜,...]}}
    for mid in sorted(os.listdir(lots)):
        for d in sorted(os.listdir(os.path.join(lots, mid))):
            months.setdefault(d[:7], {}).setdefault(mid, []).append(d)
    done = 0
    for ym, markets in sorted(months.items()):
        if month_end(ym) > cutoff:
            continue                  # 아직 기준일보다 새로운 날이 섞여 있다
        tag, name = "archive-" + ym, "MarketPrices-%s.tar.gz" % ym
        work = tempfile.mkdtemp()
        tmp = os.path.join(work, name)
        with tarfile.open(tmp, "w:gz") as tar:
            for mid, days in markets.items():
                for d in days:
                    tar.add(os.path.join(lots, mid, d), arcname="%s/lots/%s/%s" % (ym, mid, d))
                idx = os.path.join(ARCHIVE_DIR, "index", mid + ".json")
                if os.path.exists(idx):
                    j = json.load(open(idx, encoding="utf-8"))
                    part = {"dates": {d: j.get("dates", {}).get(d, []) for d in days}, "corps": j.get("corps", {})}
                    p = os.path.join(work, mid + ".json")
                    json.dump(part, open(p, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
                    tar.add(p, arcname="%s/index/%s.json" % (ym, mid))
        log("%s월: 시장 %d곳, %.1fMB 올리는 중" % (ym, len(markets), os.path.getsize(tmp) / 1e6))
        if not upload(tag, tmp):
            log("  올리기에 실패해서 지우지 않습니다.")
            shutil.rmtree(work, ignore_errors=True)
            continue
        shutil.rmtree(work, ignore_errors=True)
        for mid, days in markets.items():
            for d in days:
                shutil.rmtree(os.path.join(lots, mid, d), ignore_errors=True)
            idx = os.path.join(ARCHIVE_DIR, "index", mid + ".json")
            if os.path.exists(idx):
                j = json.load(open(idx, encoding="utf-8"))
                for d in days:
                    j.get("dates", {}).pop(d, None)
                with open(idx, "w", encoding="utf-8") as fh:
                    json.dump(j, fh, ensure_ascii=False, separators=(",", ":"))
        done += 1
    log("묶어서 올린 달: %d건" % done)
    return 0


if __name__ == "__main__":
    sys.exit(main())
