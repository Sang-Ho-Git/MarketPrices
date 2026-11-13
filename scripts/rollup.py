#!/usr/bin/env python3
"""달마다 낙찰 내역을 압축 파일 하나로 묶어 GitHub 릴리스에 올리는 백업과, 오래된 날짜 정리를 한다.

1) 백업: 한 달이 끝나고 이틀이 지나면(야간 경매는 다음 날 정산되므로) 그 달 전체를
   MarketPrices-YYYY-MM.tar.gz 하나로 묶어 릴리스 archive-YYYY-MM (제목 "2026-11월") 에 올린다.
   archive 브랜치와 main 의 data/lots 에 있는 그달 파일을 모두 넣는다. 지우지는 않는다.
2) 정리: 180일(KEEP_DAYS)이 지난 달은, 릴리스에 파일이 올라가 있는 것을 확인한 뒤에만 archive 브랜치에서 지운다.
   (릴리스 확인이 안 되면 아무것도 지우지 않는다.)
- 필요한 환경: ARCHIVE_DIR(archive 브랜치 폴더), gh 명령과 GH_TOKEN, 저장소 루트에서 실행(data/lots 읽기)
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
MAIN_LOTS = os.environ.get("MAIN_LOTS", "data/lots")


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


def gh_has_asset(tag, name):
    r = subprocess.run(["gh", "release", "view", tag, "--json", "assets"], capture_output=True, text=True)
    if r.returncode != 0:
        return False
    try:
        return any(a.get("name") == name for a in json.loads(r.stdout).get("assets", []))
    except ValueError:
        return False


def collect(root):
    """root/<시장>/<날짜> 폴더를 훑어 {YYYY-MM: {시장: {날짜: 경로}}} 로 돌려준다."""
    out = {}
    if not os.path.isdir(root):
        return out
    for mid in sorted(os.listdir(root)):
        mdir = os.path.join(root, mid)
        if not os.path.isdir(mdir):
            continue
        for d in sorted(os.listdir(mdir)):
            out.setdefault(d[:7], {}).setdefault(mid, {})[d] = os.path.join(mdir, d)
    return out


def corp_names(mid):
    names = {}
    for path in (os.path.join(ARCHIVE_DIR, "index", mid + ".json"), os.path.join("data", mid + ".json")):
        if os.path.exists(path):
            try:
                names.update(json.load(open(path, encoding="utf-8")).get("corps", {}))
            except ValueError:
                pass
    return names


def backup_month(ym, parts, upload):
    tag, name = "archive-" + ym, "MarketPrices-%s.tar.gz" % ym
    work = tempfile.mkdtemp()
    tmp = os.path.join(work, name)
    with tarfile.open(tmp, "w:gz") as tar:
        for mid, days in parts.items():
            for d, path in sorted(days.items()):
                tar.add(path, arcname="%s/lots/%s/%s" % (ym, mid, d))
            names = corp_names(mid)
            p = os.path.join(work, mid + ".json")
            json.dump({"dates": sorted(days), "corps": names}, open(p, "w", encoding="utf-8"),
                      ensure_ascii=False, separators=(",", ":"))
            tar.add(p, arcname="%s/index/%s.json" % (ym, mid))
    log("%s월 백업: 시장 %d곳, %.1fMB 올리는 중" % (ym, len(parts), os.path.getsize(tmp) / 1e6))
    ok = upload(tag, tmp)
    shutil.rmtree(work, ignore_errors=True)
    return ok


def main(upload=gh_upload, has_asset=gh_has_asset):
    today = datetime.datetime.now(KST).date()
    backed = pruned = 0
    # 1) 지난 달 백업
    months = {}
    for src in (collect(os.path.join(ARCHIVE_DIR, "lots")) if ARCHIVE_DIR else {}, collect(MAIN_LOTS)):
        for ym, mk in src.items():
            for mid, days in mk.items():
                months.setdefault(ym, {}).setdefault(mid, {}).update(days)
    for ym, parts in sorted(months.items()):
        if month_end(ym) + datetime.timedelta(days=2) > today:
            continue                      # 아직 한 달이 끝나지 않았거나 마지막 날 정산 전이다
        if has_asset("archive-" + ym, "MarketPrices-%s.tar.gz" % ym):
            continue                      # 이미 올렸다
        if backup_month(ym, parts, upload):
            backed += 1
        else:
            log("  올리기에 실패했습니다. 다음 갱신 때 다시 시도합니다.")
    # 2) 오래된 날짜 정리: 릴리스에 있는 것을 확인한 뒤에만 archive 브랜치에서 지운다
    if ARCHIVE_DIR and os.path.isdir(os.path.join(ARCHIVE_DIR, "lots")):
        cutoff = today - datetime.timedelta(days=KEEP_DAYS)
        lots = os.path.join(ARCHIVE_DIR, "lots")
        for ym, mk in sorted(collect(lots).items()):
            if month_end(ym) > cutoff:
                continue
            if not has_asset("archive-" + ym, "MarketPrices-%s.tar.gz" % ym):
                log("%s월: 릴리스에 백업이 없어 지우지 않습니다." % ym)
                continue
            for mid, days in mk.items():
                for d, path in days.items():
                    shutil.rmtree(path, ignore_errors=True)
                idx = os.path.join(ARCHIVE_DIR, "index", mid + ".json")
                if os.path.exists(idx):
                    j = json.load(open(idx, encoding="utf-8"))
                    for d in days:
                        j.get("dates", {}).pop(d, None)
                    with open(idx, "w", encoding="utf-8") as fh:
                        json.dump(j, fh, ensure_ascii=False, separators=(",", ":"))
            pruned += 1
    log("백업한 달: %d건, 정리한 달: %d건" % (backed, pruned))
    return 0


if __name__ == "__main__":
    sys.exit(main())
