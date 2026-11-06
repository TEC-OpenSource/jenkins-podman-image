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
| 패키지 제외 | 운영 env/.env·데이터·플러그인·SSL 비밀 제외. 빈 데이터/플러그인 폴더와 SSL 설정 예제만 포함 |
| 자동 검사 | 플러그인 준비·패키징·수동 초기화 단위 검사 20개 통과. git diff --check 및 Git 제외 규칙 확인 |

시험 환경은 Podman 6.1.4, podman-compose 1.5.0, ARM Mac 위 rootless Linux VM입니다. 기존 운영 데이터는 사용하지 않았습니다. ARM에서의 에뮬레이션 성공을 실제 x86 운영 서버의 인수시험 완료로 간주하지 않습니다.

남은 운영 검증:

- 실제 x86 서버의 Jenkins 기동, 재부팅/linger, SELinux, DNS/방화벽 및 실제 도메인 인증서
- 서로 다른 Jenkins Core 버전 사이의 데이터 마이그레이션 및 롤백
- 개별 업무 플러그인의 Core/API 호환성과 실제 인증·동기화·권한 정책
- 실제 Credentials, 세션/Token과 외부 업무 시스템 연동

이전 구축 방식의 문서, 시험 데이터 및 오래된 아티팩트는 정리 과정에서 Git 저장소 밖 로컬 보관 위치로 이동했습니다. 현재 운영 데이터 폴더와 최신 amd64 이미지·배포 tar는 유지했습니다.

## 초기 외부 접속 설정 변경

HTTP/HTTPS의 기본 호스트 바인딩을 `0.0.0.0`으로 변경했습니다. Compose 1.5.0의 config에서 신규 설정의 `0.0.0.0:8080`/`8443`, 기존 `.env`의 명시적 `127.0.0.1` 우선 적용, 바인딩 변경 후에도 기존 홈/플러그인 경로 유지가 확인됐습니다. 단위 검사 14개와 git diff --check도 통과했습니다. 실제 운영 서버의 외부 접근과 방화벽은 별도 확인이 필요합니다.

현재 Compose에는 build 항목이 없어 --no-build 생략 시에도 이미지 빌드를 하지 않습니다. 바인딩 수정은 이미지 재빌드가 아니라 기존 `.env` 수정과 컨테이너 재생성으로 반영합니다. 예전에 생성한 배포 tar는 자동 변경되지 않으며, 새 설정을 패키지로 반입하려면 package-deploy.py를 다시 실행해야 합니다.

## 폐쇄망 조회와 env/초기화 변경

이미지 `localhost/jenkins-25:2.580.2-2-amd64`를 실제 빌드했습니다. ID는 `1afc3a551e9bb9d4484422285357f8fdf733c29d5b1f0487cf51bd1db7aa2721`입니다. 기존 업무 플러그인 소스와 인증/인가 로직은 변경하지 않았습니다.

- `--network none`으로 새 홈을 사용해 기동했습니다. 최초 Update Center 조회가 로컬 공식 서명 목록으로 완료됐으며 연결 실패/SEVERE 없이 fully up을 확인했습니다. Maven 자동 설치용 메타데이터가 없다는 경고는 남습니다. 도구 자동 다운로드는 이번 시험 범위가 아닙니다.
- 시험 홈에서 초기 설정 완료 API를 호출한 후 플러그인 기본/Installed/Available/Advanced 화면 모두 HTTP 200, 설치 플러그인 0개, 익명 API 403을 확인했습니다. 실제 브라우저의 전체 Setup Wizard 조작과 업무 플러그인 설치는 별도 검증입니다.
- 시험 Job/Agent/사용자를 만들고 컨테이너를 삭제·재생성한 뒤 config.xml과 Job/Agent/사용자 XML 총 5개 SHA-256이 같았습니다. 재생성 후에도 네 플러그인 화면은 200, 컨테이너는 Running/OOMKilled=false였습니다.
- 숨김 없는 `env.example`과 명시적 `--env-file env`를 적용했습니다. Compose 1.5.0에서 HTTP/HTTPS 구성과 지정된 기존 `/data/...` 홈/플러그인 경로 유지가 확인됐습니다. 컨테이너에서 실제 JVM 초기 힙 1,073,741,824바이트/최대 힙 4,294,967,296바이트를 확인했습니다.
- 수동 초기화를 실제 시험 컨테이너에 실행했습니다. 기존 5개 설정 파일이 백업에 그대로 남고 홈/플러그인 폴더는 비워졌으며 시험 env/ssl 파일은 유지됐습니다. 다시 실행하면 새 초기 암호, 미완료 Setup Wizard, Job/Agent/플러그인 0개, 서명 검증 활성 상태였습니다. 권장 플러그인 목록 API는 빈 목록으로 응답했습니다.
- 새 배포 tar의 외부/전체 내부 체크섬, `env.example` 이름, 들여쓰기 없는 README.txt 명령, HTTP/HTTPS Compose config를 검사했습니다. 수동 초기화 도구와 기존 홈용 Update Center XML도 포함됩니다. 기존 이미지에는 로컬 목록 설정이 없으면 패키징이 실패하도록 검사했습니다.

운영 서버의 ExitCode 143/SIGTERM은 이 시험에서 플러그인 화면 접근으로 재현되지 않았습니다. 운영 서버에서 누가 종료 신호를 보냈는지는 확인되지 않았으며, Podman events와 systemd 등 서비스 관리자 로그 확인이 남아 있습니다. Setup Wizard의 인터넷 연결 검사나 수동 다운로드 요청까지 성공했다고 간주하지 않습니다. 기존 홈의 외부 Update Site URL은 자동으로 덮어쓰지 않으므로 README.txt의 수동 변경 절차를 적용해야 합니다.

기존 `.env`는 값을 보존해 `env`로 이름을 바꿉니다. 기존 env의 이미지 태그와 JAVA_OPTS는 자동 변경되지 않습니다. 일반 재시작에는 초기화 도구를 실행하지 않습니다.
