# 문서 목차

처음 보면 위에서부터 읽는다.

| 문서 | 무엇 | 누가 보면 좋은지 |
|---|---|---|
| [app_flow.md](app_flow.md) | 앱 전체 흐름: 로그인 → 분석 → 보관함 → 투표, 데이터 표, 만드는 순서 | 모두 |
| [backend.md](backend.md) | 서버: API 주소 전체, 사건 상태, 구조, 띄우는 법, 안드로이드에서 붙는 주소 | 앱(B), 서버(A) |
| [app_io.md](app_io.md) | 분석 결과(`app.json`)의 모양: 상태, 질문, 판정, 쟁점 | 앱(B) |
| [code_guide.md](code_guide.md) | 코드가 어떤 순서로 불리는지 (분석 단계 + 6절 서버, JWT·설정값) | 코드 고칠 사람 |
| [A_pipeline.md](A_pipeline.md) | A 분석 파이프라인: 단계, 기준값, 평가 결과, 폴더 구조, 새 영상 추가 | A |
| [facts_plan.md](facts_plan.md) | A가 채우는 사실 계획, 수정요소 영상 측정, 사실별 출처 표(7절) | A·B |
| [facts_fields.md](facts_fields.md) | `facts.json` 필드 하나하나의 뜻과 한계 | A·B |

## archive/

지금은 기준이 아니지만 기록으로 남긴 것.

| 문서 | 무엇 |
|---|---|
| [archive/planning.md](archive/planning.md) | 첫 기획서 (10-20). 앱 흐름은 지금 `app_flow.md`가 기준 |
| [archive/schema_v0.3.md](archive/schema_v0.3.md) | scene.json·facts.json 첫 초안. scene.json을 손으로 쓸 때 형식 참고용 |
| [archive/experiments_1028.md](archive/experiments_1028.md) | 10-28 실험: 모서리 민감도, 선진입, 수정요소 측정 |
