FROM mcr.microsoft.com/azure-functions/python:4-python3.11

ARG VCS_REF=unknown
LABEL org.opencontainers.image.source="https://github.com/Wiiki0807/badminton-console" \
      org.opencontainers.image.revision="${VCS_REF}"

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir \
    --target="${AzureWebJobsScriptRoot}/.python_packages/lib/site-packages" \
    -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

COPY . "${AzureWebJobsScriptRoot}"

EXPOSE 80
