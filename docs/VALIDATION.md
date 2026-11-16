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
| 자동 검사 | 플러그인 준비·패키징·수동 초기화 단위 검사 21개 통과. 초기 설정 HTTP 회귀 검사는 별도 실행하여 통과 |

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

## 초기 로그인 이동과 env.conf 변경

이미지 `localhost/jenkins-25:2.580.2-3-amd64`를 빌드하고 배포 tar를 다시 생성했습니다. ID는 `d434b26dc451a5e2dbbaebfa5e88024a30724e0b9b82198df87b8c11a2cc55c3`입니다. 설정 파일은 `env.conf`, 예제는 `env.conf.example`이며 이전 env/.env의 값과 데이터 경로를 유지하여 이름만 변경합니다.

- 기존 이미지에서 `/login?from=/manage/appearance/`로 초기 암호를 입력하면 Appearance 화면으로 이동하고 초기 설정 컨테이너가 없는 응답이 반환되는 것을 재현했습니다. Jenkins Core는 로그인 전의 from 주소를 사용하고 초기 설정 강제 처리는 기본 주소에만 적용합니다.
- 초기 설정이 끝나기 전 관리 화면의 브라우저 GET 요청을 `/setupWizard/`로 보내는 필터를 추가했습니다. 초기화 Groovy는 요청 필터를 등록하며 인증 Realm/AuthorizationStrategy, 사용자/Job/Agent XML과 설치 완료 플래그를 수정하지 않습니다. 설치 완료 후에는 기존 요청을 그대로 통과시킵니다.
- 실제 브라우저에서 Appearance 복귀 주소로 로그인한 뒤 새로고침 없이 초기 설정 화면에 진입했습니다. 플러그인 0개 설치 → 관리자 생성 화면 → 시험용 기본 admin 유지 → URL 저장 → Dashboard → 관리/Appearance 접근과 새로고침까지 확인했습니다. 새 관리자 계정 생성 자체는 이번 브라우저 시험에서 수행하지 않았습니다.
- HTTP 회귀 검사에서 기본 주소/관리/Appearance 로그인, 일반 API와 비 HTML 요청 유지, 익명 API 403을 확인했습니다. 초기 설정 완료 전·후와 컨테이너 재생성 후에 각각 실행했습니다. `/jenkins` 하위 경로를 쓰는 별도 새 홈에서도 통과했습니다. 시험 컨테이너는 외부 통신이 없는 Podman 내부 네트워크를 사용했습니다.
- 컨테이너 재생성 전후 설정/사용자/설치 완료 기록 4개 파일의 SHA-256이 같았습니다. 운영 데이터와 업무 플러그인 소스는 사용하거나 변경하지 않았습니다.
- Compose 1.5.0에서 `--env-file env.conf`로 HTTP/HTTPS 설정이 해석됐습니다. 새 tar의 예제 파일명, 명령어 들여쓰기, 운영 설정 제외와 외부/전체 내부 체크섬을 확인했고 실제 OCI load 후 ID와 linux/amd64 플랫폼이 일치했습니다.

일반 단위 검사 실행은 21개 통과, 실행 환경이 필요한 HTTP 검사 1개 건너뜀입니다. HTTP 검사는 별도로 아래 환경변수를 지정해 실행했습니다. 완료 이후 검사는 `JENKINS_SETUP_TEST_COMPLETE=1`도 지정합니다. 새로 만든 시험 Jenkins에만 사용합니다.

```sh
JENKINS_SETUP_TEST_URL=http://127.0.0.1:18090 \
JENKINS_SETUP_TEST_PASSWORD_FILE=reports/setup-redirect-after/jenkins_home/secrets/initialAdminPassword \
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -p test_setup_routing.py -v
```

플러그인 선택 화면에서 기존 Core 번들의 scrollspy 관련 `a.isWindow is not a function` 콘솔 오류도 관찰됐으나 플러그인 0개 선택과 초기 설정 완료는 진행됐습니다. 이 콘솔 오류의 Core 프런트엔드 호환성 확인과 실제 x86 운영 서버의 인수시험은 남아 있습니다.

## env.conf 설정과 자동 복구 (2026-11-07)

Compose의 `env_file`, HTTPS 실행 예시와 Quadlet의 `EnvironmentFile`을 env.conf 기준으로 맞췄습니다. Quadlet용 최소 예제도 `environments/env.conf.example`로 변경했습니다. 이미지/호스트 경로/포트의 Compose 치환에는 계속 `--env-file env.conf`를 사용합니다.

- Jenkins/JDK 이미지는 기존 `2.580.2-3-amd64`를 사용하며 재빌드하지 않았습니다. 응답 검사 스크립트는 배포 폴더에서 읽기 전용으로 연결하고, 사용자용 복구 서비스/타이머를 배포 tar에 포함했습니다.
- 실제 Compose 1.5.0으로 새 시험 홈을 기동해 30초 간격/10초 제한/3회 실패/5분 시작 유예 설정과 HTTP healthy 상태를 확인했습니다. 초기화 중 연결 실패는 시작 유예 처리됐습니다.
- 시험 컨테이너 내부에서 PID 1에 종료 신호를 보내 실제 Jenkins 종료를 유도했습니다. `unless-stopped` 정책으로 다시 시작됐고 RestartCount가 증가했습니다. 시험 설정/Job/Agent/사용자/암호화 키 6개 파일의 SHA-256은 같았습니다.
- 시험 ID와 reports/healing-run 전용 마운트를 확인한 뒤 healthcheck 실패를 주입했습니다. VM의 사용자용 systemd 타이머가 unhealthy 컨테이너를 재시작했고 다시 healthy가 됐습니다. 비슷한 이름의 별도 컨테이너는 재시작되지 않았습니다. 타이머의 정상 컨테이너 제외와 수동 중지 상태 유지도 확인했습니다.
- oneshot 복구 명령이 끝날 때 새 conmon/Jenkins 프로세스를 정리하지 않도록 `KillMode=process`를 적용했습니다. 실행 중 상태를 명시적으로 필터링하며, 이전 명령 완료 후 30초에 다시 검사합니다. 서비스 종료 결과 success/inactive와 후속 타이머 실행을 확인했습니다.
- 시험 인증서와 별도 Podman Secret으로 동일 데이터를 HTTPS로 재생성했습니다. HTTPS probe가 healthy였고 같은 6개 파일의 내용이 유지됐습니다. TLS probe의 인증서 검증 생략은 자격 증명을 보내지 않는 컨테이너 내부 loopback 요청에만 적용됩니다.
- Quadlet은 실제 generator의 user/dryrun 모드에서 env.conf 경로, HealthOnFailure=kill, Restart=always 변환을 확인했습니다. Quadlet 서비스를 실제로 실행해 장애 복구하는 시험은 수행하지 않았습니다.
- 건강 검사 단위 검사 4개가 통과했습니다. 함께 실행한 현재 전체 검사는 40개 통과, 별도 실행 환경이 필요한 초기 로그인 HTTP 검사 1개 건너뜀입니다. 실제 서버의 로그아웃/linger/재부팅 복구와 배포판별 사용자 podman-restart.service 지원은 별도 확인이 필요합니다.

운영 데이터는 사용하지 않았습니다. Podman 소켓/privileged 권한, 인증 정책, 업무 플러그인 소스는 이번 복구 기능에서 변경하지 않았습니다. Podman/호스트 자체가 동작하지 않는 상황의 복구를 컨테이너 재시작 기능으로 보장하지 않습니다.

동작 기준은 [Podman 재시작 및 필터](https://docs.podman.io/en/stable/markdown/podman-restart.1.html), [Podman 실행/재시작 정책](https://docs.podman.io/en/stable/markdown/podman-run.1.html), [systemd 타이머](https://www.freedesktop.org/software/systemd/man/259/systemd.timer.html)를 참고했습니다.

## 최초 관리자 등록 후 5분 종료 점검 (2026-11-09)

실제 배포 tar의 Compose/응답 검사/복구 서비스·타이머와 파일 권한이 현재 소스와 같은지 확인했습니다. 운영 서버와 이름·포트·데이터가 다른 새 시험 컨테이너를 만들고 기본 admin을 건너뛰는 대신 Setup Wizard API로 새 관리자 계정을 실제 등록했습니다. 플러그인 0개 설치와 URL 설정을 마친 후 배포본과 같은 복구 타이머를 활성화했습니다. 시험용 컨테이너/서비스 이름만 변경했습니다.

- 관리자 등록 후 452초 동안 30초 간격으로 16회 관찰했습니다. 컨테이너 기동 기준으로는 약 9분이 지났습니다.
- 모든 표본이 running/healthy였고, 컨테이너 ID와 StartedAt이 유지됐으며 RestartCount는 0, OOMKilled는 false였습니다.
- 초기화 완료 후 컨테이너 로그에 Stopping Jenkins/Jenkins stopped/Shutdown hook 등의 종료 메시지가 없었습니다. 복구 서비스는 success/inactive, 타이머는 active 상태였습니다.
- 관리자·보안 설정과 암호화 키 파일 내용도 유지됐습니다. 운영 데이터는 사용하지 않았습니다.
- 정상 가동 중에도 State.ExitCode는 0으로 표시됐습니다. ExitCode=0만으로 종료 여부나 종료 원인을 판정할 수 없습니다.

이 시험에서는 최초 관리자 등록 5분 후 자동 종료가 재현되지 않았습니다. 코드의 5m은 컨테이너 기동 후 응답 검사 실패를 유예하는 시간이며 관리자 등록 기준의 종료 예약이 아닙니다. 유예 종료 뒤 실제 응답 검사 실패가 누적되면 복구 타이머/Quadlet이 재시작을 유발할 수 있습니다. Quadlet의 TimeoutStartSec=300은 서비스 시작 완료 제한이며 가동 시간 제한이 아닙니다.

시험은 ARM Mac의 rootless Podman 6.1.4 VM에서 amd64 이미지를 실행한 결과입니다. VM 사용자 linger는 활성 상태였습니다. 실제 운영 서버의 종료 원인을 확인한 결과는 아니며, 운영 서버의 실행/종료 상태와 health 기록, 서비스 관리자 로그가 없으므로 해당 원인은 미확인입니다. 동작 설정을 임의로 바꾸거나 복구 기능을 비활성화하지 않았습니다.
