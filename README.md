# Jenkins Podman Image

Jenkins LTS를 JDK 25에서 실행하는 OCI 이미지와 폐쇄망 배포 패키지입니다.

- Jenkins **2.580.2 LTS**, JDK **25**, 이미지 이름 **jenkins-25**
- **jenkins:jenkins** 사용자, rootless Podman 기반
- 이미지와 플러그인 설치 분리, 설정·Job·Agent·사용자 정보 영속 저장
- 폐쇄망 실행과 선택적인 HTTPS 지원

## 이미지 빌드

인터넷이 가능한 환경에 Podman과 Python 3.9 이상을 준비합니다. 아래 명령은 ARM Mac에서 x86_64 Linux 서버용 이미지를 빌드하는 기준입니다. 프로젝트 폴더에서 실행합니다.

Mac의 Podman VM이 꺼져 있다면 먼저 시작합니다.

```sh
podman machine start
```

```sh
podman build --platform linux/amd64 --format oci -f Containerfile -t localhost/jenkins-25:2.580.2-3-amd64 .
podman image inspect --format '{{.Os}}/{{.Architecture}}' localhost/jenkins-25:2.580.2-3-amd64
```

플랫폼 출력은 `linux/amd64`여야 합니다. Jenkins/JDK 버전은 `Containerfile`의 FROM 태그와 digest를 변경하고, 새 이미지 태그로 구분합니다. 플러그인 추가에는 이미지 재빌드가 필요하지 않습니다.

## 배포 파일 생성

빌드한 로컬 이미지를 지정합니다. 이 명령이 이미지 저장과 배포 tar 생성을 수행합니다.

```sh
python3 scripts/package-deploy.py --image localhost/jenkins-25:2.580.2-3-amd64
```

생성되는 두 파일을 함께 내부망 서버에 반입합니다.

```text
dist/jenkins-podman-jdk25.tar
dist/jenkins-podman-jdk25.tar.sha256
```

패키지에는 이미지, Compose 설정, `env.conf.example`, 빈 데이터·플러그인·SSL 폴더와 운영 안내 `README.txt`가 포함됩니다. 운영 데이터와 개인 인증서/키는 포함하지 않습니다. 내부망에서의 이미지 로드, 기동·종료, 설정 방법은 압축을 푼 뒤 `README.txt`를 따릅니다.

운영 안내 원본은 [deployment/README.offline.txt.in](deployment/README.offline.txt.in), 검증 결과는 [docs/VALIDATION.md](docs/VALIDATION.md)에 있습니다.

---

이 프로젝트는 OpenAI Codex를 활용하여 개발되었습니다.
