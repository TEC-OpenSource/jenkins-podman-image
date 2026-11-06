# Verified 2026-11-05: Jenkins 2.580.2 LTS, Linux multi-architecture JDK 25 image.
FROM docker.io/jenkins/jenkins:2.580.2-lts-jdk25@sha256:415ab90d4e3b25148f7191bc04f455a20817d6c4c3b0a98f6c6b0da4877f7081
# No plugin binaries. Use a local, signed catalog instead of an Internet update site.
COPY --chown=jenkins:jenkins deployment/offline/ /opt/jenkins-offline/
COPY --chown=jenkins:jenkins deployment/offline/hudson.model.UpdateCenter.xml /usr/share/jenkins/ref/hudson.model.UpdateCenter.xml
COPY --chown=jenkins:jenkins deployment/init.groovy.d/20-initial-setup-routing.groovy /usr/share/jenkins/ref/init.groovy.d/20-initial-setup-routing.groovy.override
ENV JAVA_OPTS="-Xms1g -Xmx4g -Djava.awt.headless=true -Duser.timezone=Asia/Seoul" \
    JENKINS_JAVA_OPTS="-Dhudson.model.UpdateCenter.updateCenterUrl=file:/opt/jenkins-offline/ -Dhudson.model.UpdateCenter.never=true -Djenkins.telemetry.Telemetry.disabled=true -Dhudson.model.UsageStatistics.disabled=true" \
    JENKINS_SETUP_ROUTING_VERSION="1"
# The official image already provides jenkins:jenkins (UID/GID 1000).
# Keep the official entrypoint and the existing agent/security configuration.
USER jenkins:jenkins
