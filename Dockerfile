# retvana retirement planner - Streamlit app
# python:3.13-slim pinned by its multi-arch index digest; Dependabot proposes updates.
FROM python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # inside the container Streamlit must listen on all interfaces; compose publishes
    # the port on the host's localhost only
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    # the plan lives in the mounted host data directory, never in the image
    RETVANA_DATA_DIR=/data
WORKDIR /app
# install the package (not editable) from pyproject.toml with its pinned dependencies
COPY pyproject.toml ./
COPY src ./src
RUN pip install . && rm -rf /app/src /app/pyproject.toml /app/build
RUN useradd --create-home --uid 1000 retvana \
    && mkdir -p /data && chown retvana:retvana /data
COPY --chown=retvana:retvana .streamlit ./.streamlit
COPY --chown=retvana:retvana app.py .
USER retvana
EXPOSE 8501
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=4).read()==b'ok' else 1)"
CMD ["streamlit", "run", "app.py"]
