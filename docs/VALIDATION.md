# 검증 요약

2026-11-06 기준입니다. 이 저장소의 현재 구성은 순수 Jenkins 이미지, 외부 플러그인 폴더, 선택적 HTTPS, 폐쇄망 배포 패키지입니다.

| 항목 | 확인한 결과 |
| --- | --- |
| 기본 이미지 | Jenkins 2.580.2 LTS / JDK 25, jenkins:jenkins UID/GID 1000 |
| 순수 기동 | 추가 플러그인 0개로 기동. 네트워크 없는 컨테이너도 fully up, 익명 API 403 |
| 폴더 플러그인 설치 | 컨테이너 down 후 실제 locale HPI 추가, 동일 이미지 up 후 active 확인 |
| 영속성 | 플러그인 추가·HTTPS 전환 전후 설정, 시험 Job, Agent, 사용자 XML SHA-256 동일 |
| HTTPS | PKCS12 시험 인증서와 Podman Secret으로 HTTPS 접속 200, HTTP listener 비활성 확인. ssl 경로 변경 후 Compose 치환 검사 |
| amd64 빌드 | ARM Mac에서 --platform linux/amd64 빌드 성공. inspect에서 linux/amd64, 에뮬레이션에서 x86_64/JDK 25 실행 확인 |
| 배포 패키지 | 실제 tar 압축 해제, 외부/내부 체크섬, HTTP/HTTPS Compose config, 추출 이미지 load 및 ID/플랫폼 확인 |
| 패키지 제외 | 운영 .env·데이터·플러그인·SSL 비밀 제외. 빈 데이터/플러그인 폴더와 SSL 설정 예제만 포함 |
| 자동 검사 | 플러그인 준비·패키징 단위 검사 14개 통과. git diff --check 및 Git 제외 규칙 확인 |

시험 환경은 Podman 6.1.4, podman-compose 1.5.0, ARM Mac 위 rootless Linux VM입니다. 기존 운영 데이터는 사용하지 않았습니다. ARM에서의 에뮬레이션 성공을 실제 x86 운영 서버의 인수시험 완료로 간주하지 않습니다.

남은 운영 검증:

- 실제 x86 서버의 Jenkins 기동, 재부팅/linger, SELinux, DNS/방화벽 및 실제 도메인 인증서
- 서로 다른 Jenkins Core 버전 사이의 데이터 마이그레이션 및 롤백
- 개별 업무 플러그인의 Core/API 호환성과 실제 인증·동기화·권한 정책
- 실제 Credentials, 세션/Token과 외부 업무 시스템 연동

이전 구축 방식의 문서, 시험 데이터 및 오래된 아티팩트는 정리 과정에서 Git 저장소 밖 로컬 보관 위치로 이동했습니다. 현재 운영 데이터 폴더와 최신 amd64 이미지·배포 tar는 유지했습니다.
