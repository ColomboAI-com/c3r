# Qualification candidate only; image scan and GPU qualification are separate gates.
FROM vllm/vllm-openai@sha256:98adb2311118263a453ec0acd5d4b72bda3db26cecc0fe8ffc94b9ab03c951f9
USER root
LABEL org.opencontainers.image.source="https://github.com/vllm-project/vllm" \
      org.opencontainers.image.revision="ac68c3087215e0a4f3cdfa218508c6aada57235d" \
      com.colomboai.c3r.qualification="pending"
RUN apt-get update && apt-get upgrade -y \
    && apt-get install -y --no-install-recommends libc6-dev python3.12-dev \
    && apt-get purge -y python3-msgpack python3-setuptools python3-urllib3 \
    && rm -rf /var/lib/apt/lists/* \
    && python3 -m pip uninstall --break-system-packages -y opentelemetry-exporter-otlp-common
COPY check_upstream_dependencies.py /opt/c3r/check_upstream_dependencies.py
COPY compiler_probe.c /opt/c3r/compiler_probe.c
# Triton compiles CUDA helpers at runtime. Removing development headers can make
# a vulnerability scan clean while breaking the actual model startup.
RUN gcc -fsyntax-only -I/usr/include/python3.12 \
    -I/usr/local/lib/python3.12/dist-packages/triton/backends/nvidia/include \
    /opt/c3r/compiler_probe.c
RUN python3 /opt/c3r/check_upstream_dependencies.py \
    && python3 -m pip uninstall --break-system-packages -y pip
ENV HOME=/runtime \
    HF_HUB_OFFLINE=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    VLLM_NO_USAGE_STATS=1 \
    DO_NOT_TRACK=1 \
    VLLM_USE_V2_MODEL_RUNNER=1 \
    PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True \
    VLLM_ENGINE_READY_TIMEOUT_S=3600
USER 1003:1004
ENTRYPOINT ["python3", "-m", "vllm.entrypoints.openai.api_server"]
