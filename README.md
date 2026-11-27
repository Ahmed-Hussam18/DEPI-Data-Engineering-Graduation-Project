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
