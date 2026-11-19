FROM apache/airflow:2.10.5-python3.11

USER root
COPY pyproject.toml README.md /opt/kzjobs/
COPY src /opt/kzjobs/src
COPY data /opt/kzjobs/data
RUN chown -R airflow /opt/kzjobs

USER airflow
RUN pip install --no-cache-dir -e /opt/kzjobs
