FROM python:3.12-slim

WORKDIR /srv/operario
COPY services/entrypoint/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY services/entrypoint/ ./services/entrypoint/
COPY packages/ ./packages/
ENV PYTHONPATH=/srv/operario

# OPENROUTER_API_KEY y TEAM_TOKEN se inyectan como variables de entorno. Nunca en el repo.
EXPOSE 8000
CMD ["uvicorn", "services.entrypoint.app:app", "--host", "0.0.0.0", "--port", "8000"]
