# 도매시장 경락가

휴대폰에서 보는 전국 공영도매시장 경락가 페이지입니다. 공공데이터포털의
[전국 공영도매시장 실시간 경매정보](https://www.data.go.kr/data/15141808/openapi.do) API를 사용합니다.

## 구성
- `index.html` 화면 전체 (시장 선택 → 품목 시세 → 산지·법인·낙찰 내역). 주소 끝 `#garak`, `#anyang` 처럼 시장별로 열립니다.
- `scripts/fetch.py` API에서 데이터를 받아 `data/*.json` 으로 저장합니다.
- `scripts/markets.json` 수집할 시장(`active`)과 시장 이름 매칭 글자(`match`)를 적습니다.
- `.github/workflows/update.yml` 3시간마다 `fetch.py` 를 실행하고 바뀐 데이터를 저장합니다.

## 처음 한 번
1. Settings → Secrets and variables → Actions 에 `DATA_GO_KR_KEY` (인증키) 등록
2. Settings → Pages → Branch `main` / `(root)` 로 켜기
3. Actions → update-data → Run workflow 로 처음 실행

## 시장 추가
`scripts/markets.json` 의 `active` 에 시장 id 를 추가하면 다음 갱신부터 수집합니다.
도매시장 코드는 처음 실행 때 `data/markets_discovered.json` 에 저장됩니다.
