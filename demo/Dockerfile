FROM python:3.12-slim
ARG SERVICE
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/demo
WORKDIR /demo
RUN addgroup --system demo && adduser --system --ingroup demo demo
COPY demo/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
COPY demo/shared ./shared
COPY demo/${SERVICE} ./service
USER demo
CMD ["uvicorn", "service.main:app", "--host", "0.0.0.0"]

