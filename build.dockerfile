FROM python:3.14-slim
EXPOSE 25252/tcp
EXPOSE 4713/tcp

RUN apt-get update \
  && apt-get install -y --no-install-recommends git libsndfile1 pulseaudio-utils libportaudio2 portaudio19-dev netcat-openbsd procps \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /app
ARG REPO=https://github.com/zoshesky-uaa/audiogen-beamngpy
ARG BRANCH=master

RUN git clone --depth 1 --branch ${BRANCH} ${REPO} /app || true

# Install Python requirements from the cloned repo (or the build-context file)
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

ENV PULSE_SERVER=tcp:host.docker.internal:4713
ENV BEAMNG_HOST=host.docker.internal
ENV BEAMNG_PORT=25252
ENV MPLCONFIGDIR=/tmp/matplotlib
ENV PYTHONUNBUFFERED=1

# Use unbuffered python so logs stream to Docker logs immediately
CMD ["python","-u","/app/main.py"]