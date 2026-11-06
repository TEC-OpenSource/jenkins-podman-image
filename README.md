# Jenkins Podman Image

Jenkins LTS를 JDK 25에서 실행하는 순수 OCI 이미지와 폐쇄망 배포 패키지입니다.

- Jenkins **2.580.2 LTS**, JDK **25**, 이미지 이름 **jenkins-25**
- 컨테이너 사용자 **jenkins:jenkins** (UID/GID 1000), rootless Podman 기준
- 이미지 빌드와 플러그인 설치 분리, 운영 서버의 자동 Pull/Build 없음
- 설정·Job·Agent·사용자·Credentials와 플러그인을 호스트에 영속 저장
- 선택적인 HTTPS, 인증서와 비밀번호는 이미지/Git 외부에서 관리

## 저장소 구성

```text
Containerfile                    # Core/JDK만 포함
podman-compose.yml               # 기본 HTTP 실행
podman-compose.https.yml         # 선택적 HTTPS 확장
.env.example                    # 비밀 없는 실행 설정 예제
scripts/package-deploy.py        # 배포 tar 생성
deployment/README.offline.txt.in # 패키지 안 README.txt의 원본
deployment/https.properties.example
scripts/bundle.py               # 선택적인 외부 플러그인 준비
deployment/ValidatePlugins.java  # 플러그인 Core/의존성 검사
plugins.txt / plugins.lock.json
custom-plugins/                 # 외부 준비용 로컬 HPI/JPI 입력
quadlet/ / environments/        # 선택적인 systemd 실행 대안
tests/ / docs/VALIDATION.md
```

실행 시 사용하는 `jenkins_home/`, `plugins/`, `ssl/`은 Compose 파일 옆에 만듭니다. 운영 데이터와 비밀, 바이너리, `build/`, `archives/`, `dist/`, `reports/`는 Git에서 제외합니다. 빈 실행 폴더는 Git에 올라가지 않으며 배포 패키지가 생성합니다.

## ARM Mac에서 x86_64 서버용 빌드

빌드 환경에 Podman과 Python 3.9 이상을 준비합니다. Mac에서는 Podman VM이 실행 중이어야 합니다.

```sh
# 프로젝트 폴더에서 실행, VM이 꺼져 있을 때만 start
podman machine start
podman build --platform linux/amd64 --format oci -f Containerfile \
  -t localhost/jenkins-25:2.580.2-1-amd64 .
podman image inspect --format '{{.Os}}/{{.Architecture}}' \
  localhost/jenkins-25:2.580.2-1-amd64
```

출력은 `linux/amd64`여야 합니다. `--platform`을 생략하면 ARM용 이미지가 만들어질 수 있습니다. 현재 Containerfile은 `RUN` 없이 FROM/ENV/USER만 사용합니다. ARM Mac에서 amd64 바이너리를 실제 실행할 때에는 VM의 에뮬레이션 지원이 필요합니다. [Podman 빌드 문서](https://docs.podman.io/en/stable/markdown/podman-build.1.html)를 참조하십시오.

Jenkins/JDK 변경은 FROM 태그와 확인한 digest를 직접 변경하고 별도 버전 태그로 빌드합니다. 플러그인 추가에는 이미지 재빌드가 필요하지 않습니다.

## 폐쇄망 배포 패키지 생성

**이미 빌드한 로컬 이미지**를 지정합니다. 스크립트는 빌드·Pull·컨테이너 기동을 수행하지 않습니다.

```sh
python3 scripts/package-deploy.py \
  --image localhost/jenkins-25:2.580.2-1-amd64
```

생성 파일:

```text
dist/jenkins-podman-jdk25.tar
dist/jenkins-podman-jdk25.tar.sha256
```

이미지를 생략하면 `.env.example`의 태그를 사용합니다. `--output-dir`로 출력 위치를 바꿀 수 있습니다. 기본 대상은 `linux/amd64`이며 JDK 번호는 Containerfile에서 읽습니다. 운영 .env, 데이터, 플러그인, 개인 인증서/키는 패키지에 넣지 않습니다.

tar를 풀면 다음 파일과 폴더가 생성됩니다.

```text
jenkins-podman-jdk25/
├── .env.example
├── podman-compose.yml
├── podman-compose-https.yml
├── README.txt
├── IMAGE.txt / SHA256SUMS
├── archives/       # OCI 이미지와 체크섬
├── jenkins_home/   # 빈 영속 데이터 폴더
├── plugins/        # 빈 플러그인 폴더
└── ssl/            # 비밀 없는 HTTPS 설정 예제
```

패키지 안 HTTPS 파일명은 `podman-compose-https.yml`입니다. 저장소에서 사용하는 `podman-compose.https.yml`와 내용은 같습니다.

## 폐쇄망 서버에서 실행

서버에 Podman과 podman-compose 1.5.0 및 실행 의존성을 미리 설치합니다. 모든 명령은 같은 일반 OS 계정으로 실행합니다. 기존 운영 폴더 위에 새 패키지를 덮어 풀지 마십시오.

```sh
sha256sum -c jenkins-podman-jdk25.tar.sha256
tar -xf jenkins-podman-jdk25.tar
cd jenkins-podman-jdk25
sha256sum -c SHA256SUMS
cat README.txt
```

안의 `README.txt`에 이미지 load, 초기 설정, 접속, 플러그인 추가, HTTPS, 기존 데이터 연결과 백업 절차가 있습니다. 신규 서버의 기본 기동은 다음과 같습니다.

```sh
podman load --input archives/jenkins-25-amd64.oci.tar
test -f .env || cp .env.example .env
chmod 600 .env
podman-compose -f podman-compose.yml up --no-build -d
podman-compose -f podman-compose.yml logs -f
```

기본 HTTP는 서버의 `127.0.0.1:8080`입니다. 외부 PC에서는 `ssh -L 18080:127.0.0.1:8080 계정@서버` 후 `http://127.0.0.1:18080`에 접속합니다. 최초 관리자 암호는 다음 명령으로 확인합니다. 폐쇄망의 Setup Wizard에서는 추가 플러그인 설치를 건너뜁니다.

```sh
podman-compose exec jenkins cat /var/jenkins_home/secrets/initialAdminPassword
```

## 데이터 보존과 플러그인 추가

`JENKINS_HOME_DIR` 기본값은 `./jenkins_home`, `JENKINS_PLUGINS_DIR`는 `./plugins`입니다. 상대 경로는 Compose 파일을 기준으로 합니다. 같은 두 경로를 유지하면 down/up 및 컨테이너 재생성 후에도 데이터가 남습니다. 기존 홈을 사용한다면 새 빈 폴더로 바꾸지 말고 `.env`에 기존 실제 경로를 지정합니다. 기존 홈 안에 플러그인이 있다면 그 폴더를 그대로 `JENKINS_PLUGINS_DIR`에 연결합니다.

```sh
podman-compose -f podman-compose.yml down
# 홈과 plugins를 백업한 뒤 실제 plugins 경로에 승인된 HPI/JPI와 필수 의존성을 복사
podman-compose -f podman-compose.yml up --no-build -d
```

같은 ID의 HPI/JPI를 중복으로 두지 않습니다. 교체·제거는 중지와 백업 후 해당 ID의 아카이브, 압축 해제 디렉터리, 관련 표식만 명시적으로 분리합니다. 사용자·Job·Agent·Credentials·설정 XML은 함께 지우지 않습니다. Realm이나 다른 플러그인이 의존하는 플러그인은 유지해야 합니다. 새 플러그인의 업무 로직과 다른 Core 버전의 데이터 호환성은 별도 검증합니다.

외부 인터넷 환경에서 공식 플러그인 의존성을 준비하려면 `plugins.txt`에 `ID:정확한버전`, `custom-plugins/`에 승인된 로컬 아티팩트를 넣습니다.

```sh
python3 scripts/bundle.py resolve
python3 scripts/bundle.py export
# build/plugin-bundle/ 및 build/plugins.sha256을 별도 반입
```

`deployment/ValidatePlugins.java`는 전체 후보의 manifest/Core/필수 의존성을 사전 검사하는 선택적 도구입니다. 실행 중인 Jenkins에 자동 설치하지 않습니다.

## HTTPS와 재시작

`ssl/jenkins.p12`에 인증서를 준비하고 `https.properties.example`의 keystore 암호를 로컬에서 채웁니다. Podman Secret 등록 후 기본 Compose와 HTTPS 확장을 함께 실행합니다. 자세한 명령과 인증서 변환 방법은 배포 패키지의 `README.txt`를 따르십시오. 이미지 재빌드는 필요하지 않습니다. 기존 HTTPS Secret의 keystore 경로는 `/var/jenkins_ssl/jenkins.p12`여야 합니다.

Compose는 `restart: unless-stopped`를 사용합니다. Linux 재부팅 자동 복구는 배포 계정의 사용자 서비스/linger/Podman 구성을 확인해야 합니다. Quadlet 대안은 `quadlet/jenkins.container`의 두 경로를 실제 절대 경로로 바꾸어 사용하며 Compose와 동시에 실행하지 않습니다. 백업·롤백은 이미지와 전체 홈·플러그인을 함께 관리합니다.

## 검증과 Git 관리

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
git diff --check
git status --short --untracked-files=all
```

실제 확인한 범위와 남은 항목은 [검증 요약](docs/VALIDATION.md)에 정리했습니다. 예제 파일에 실제 암호/Token을 쓰지 마십시오. `.gitignore`는 이미 추적 중인 파일을 자동으로 해제하지 않습니다. 이미지와 배포 tar는 GitHub 소스에 커밋하지 않고 별도 반입 경로로 전달합니다.

---

이 프로젝트는 OpenAI Codex를 활용하여 개발되었습니다.
