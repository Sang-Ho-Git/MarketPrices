#!/usr/bin/env python3
"""보관(archive) 브랜치에서 3개월이 지난 낙찰 파일을 월별 압축 파일로 묶어 GitHub 릴리스에 올리고,
올리기에 성공한 경우에만 archive 브랜치에서 지운다. (올리기에 실패하면 아무것도 지우지 않는다.)

- 한 달이 통째로 기준일(오늘 - KEEP_DAYS)보다 오래됐을 때 그 달을 묶는다. (그래서 실제로는 3~4개월 보관)
- 릴리스 이름: archive-YYYY-MM, 파일 이름: lots-<시장>-YYYY-MM.tar.gz
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
KEEP_DAYS = int(os.environ.get("KEEP_DAYS", "90"))
ARCHIVE_DIR = os.environ.get("ARCHIVE_DIR", "").strip()


def log(*a):
    print(*a, flush=True)


def gh_upload(tag, path):
    """릴리스(없으면 만들고)에 파일을 올린다. 성공하면 True."""
    ok = subprocess.run(["gh", "release", "view", tag], capture_output=True).returncode == 0
    if not ok:
        r = subprocess.run(["gh", "release", "create", tag, "--title", tag,
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
    done = 0
    for mid in sorted(os.listdir(lots)):
        mdir = os.path.join(lots, mid)
        months = {}
        for d in sorted(os.listdir(mdir)):
            months.setdefault(d[:7], []).append(d)
        for ym, days in sorted(months.items()):
            if month_end(ym) > cutoff:
                continue            # 아직 3개월이 안 지난 날이 섞여 있다
            tag, name = "archive-" + ym, "lots-%s-%s.tar.gz" % (mid, ym)
            tmp = os.path.join(tempfile.mkdtemp(), name)
            with tarfile.open(tmp, "w:gz") as tar:
                for d in days:
                    tar.add(os.path.join(mdir, d), arcname="lots/%s/%s" % (mid, d))
                idx = os.path.join(ARCHIVE_DIR, "index", mid + ".json")
                if os.path.exists(idx):
                    tar.add(idx, arcname="index/%s.json" % mid)
            size = os.path.getsize(tmp) / 1e6
            log("%s %s: %d일, %.1fMB 올리는 중" % (mid, ym, len(days), size))
            if not upload(tag, tmp):
                log("  올리기에 실패해서 지우지 않습니다.")
                os.remove(tmp)
                continue
            os.remove(tmp)
            for d in days:
                shutil.rmtree(os.path.join(mdir, d), ignore_errors=True)
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
