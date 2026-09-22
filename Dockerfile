# serp-drift: standard-library Python, one process, one volume.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 SERP_DRIFT_DIR=/workspace
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY serp_drift ./serp_drift
RUN pip install --no-cache-dir . && useradd --create-home --uid 1000 serp && mkdir -p /workspace && chown serp /workspace
USER serp
VOLUME ["/workspace"]
EXPOSE 8765
# The token protects the UI when the port is published; set SERP_DRIFT_TOKEN in compose or the environment.
CMD ["serp-drift", "serve", "--host", "0.0.0.0", "--port", "8765"]
