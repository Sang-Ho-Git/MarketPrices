# 도매시장 경락가

휴대폰에서 보는 전국 공영도매시장 경락가 페이지입니다. 공공데이터포털의
[전국 공영도매시장 실시간 경매정보](https://www.data.go.kr/data/15141808/openapi.do) API를 사용합니다.

## 구성
- `index.html` 화면 전체 (시장 선택 → 품목 시세 → 산지·법인·낙찰 내역). 주소 끝 `#garak`, `#anyang` 처럼 시장별로 열립니다.
- `scripts/fetch.py` API에서 데이터를 받아 `data/*.json` 으로 저장합니다.
- `scripts/markets.json` 수집할 시장(`active`)과 시장 이름 매칭 글자(`match`)를 적습니다.
- `.github/workflows/update.yml` 매일 한국시간 07:00, 19:00 에 `fetch.py` 를 실행하고 바뀐 데이터를 저장합니다.
- `archive` 브랜치 14일이 지난 낙찰 파일을 옮겨 두는 곳입니다. 화면에서 오래된 날짜를 고르면 여기서 불러옵니다.
- 3개월이 지난 달은 `scripts/rollup.py` 가 월별 압축 파일(`lots-시장-YYYY-MM.tar.gz`)로 묶어 저장소의 Releases(`archive-YYYY-MM`)에 올립니다. 올리기에 성공한 경우에만 `archive` 브랜치에서 지웁니다. 내 컴퓨터에는 Releases 페이지에서 내려받아 보관하세요.

## 처음 한 번
1. Settings → Secrets and variables → Actions 에 `DATA_GO_KR_KEY` (인증키) 등록
2. Settings → Pages → Branch `main` / `(root)` 로 켜기
3. Actions → update-data → Run workflow 로 처음 실행

## 시장 추가
`scripts/markets.json` 의 `active` 에 시장 id 를 추가하면 다음 갱신부터 수집합니다.
도매시장 코드는 처음 실행 때 `data/markets_discovered.json` 에 저장됩니다.
