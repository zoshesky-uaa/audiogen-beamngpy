FROM python:3.11-slim
EXPOSE 25252/tcp
EXPOSE 4713/tcp

RUN apt-get update \
  && apt-get install -y --no-install-recommends git libsndfile1 pulseaudio-utils \
  && apt-get clean \
  && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

WORKDIR /app
ARG REPO=https://github.com/zoshesky-uaa/audiogen-beamngpy
ARG BRANCH=main

RUN git clone --depth 1 --branch ${BRANCH} ${REPO} /app || true

# Use the requirements.txt from the build context (overwriting any in the repo)
# so we don't attempt to pip-install standard-library names like 'threading'.
COPY requirements.txt /app/requirements.txt
RUN if [ -f /app/requirements.txt ]; then \
      pip install --no-cache-dir -r /app/requirements.txt ; \
    else \
      echo "No requirements.txt found; skipping pip install" ; \
    fi

ENV PULSE_SERVER=tcp:host.docker.internal:4713
ENV BEAMNG_HOST=host.docker.internal
ENV BEAMNG_PORT=25252

CMD ["python","/app/main.py"]