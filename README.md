# DEPI-Data-Engineering-Graduation-Project

DEPI Data Engineering Graduation Project.

## Getting Started

### Docker Compose Setup

1. Clone the repository.
2. Create your environment file:

   ```bash
   cp .env.example .env
   ```

3. Start the services:

   ```bash
   docker compose up -d
   ```

4. Check the running containers:

   ```bash
   docker compose ps
   ```

### Local Development Setup

Install the development dependencies:

```bash
python -m pip install -r requirements-dev.txt
```

Run the tests:

```bash
pytest
```


## Run locally

Requirements: Docker Desktop and Git.

bash
git clone https://github.com/Ali-Ahmed-Farag/DEPI-Data-Engineering-Graduation-Project.git
cd DEPI-Data-Engineering-Graduation-Project
cp .env.example .env
docker compose up -d --build


Wait about 2 minutes, then check docker compose ps. All services should be running (airflow-init exits with code 0, which is normal).

| Service | URL |
|---|---|
| Airflow | http://localhost:8080 |
| API (docs) | http://localhost:8000/docs |
| Grafana | http://localhost:3000 |
| Postgres | localhost:5432 |

Logins come from .env. The database schema is created automatically on first start. Grafana loads the dashboards from grafana/dashboards/ in the "Pipeline Monitoring" folder.

To stop: docker compose down. To reset all data: docker compose down -v.
