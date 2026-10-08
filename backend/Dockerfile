FROM python:3.11-slim AS builder

RUN pip install poetry==1.8.1

RUN poetry config virtualenvs.create false

WORKDIR /code

COPY ./pyproject.toml ./README.md ./poetry.lock* ./


RUN poetry install --no-interaction --no-ansi --no-root --without dev

# Generate the offline preference-elicitation vignettes.
#
# This is deterministic computation over a configuration file that is committed,
# taking ~30s. It is generated here rather than committed so the output cannot
# drift from the parameters that produced it, and so a clean clone builds without
# a prior CI run — previously this directory was neither tracked nor ignored, and
# the documented manual build could not work.
COPY ./app/agent/preference_elicitation_agent/offline_optimization ./offline_optimization
RUN cd offline_optimization \
    && python run_offline_optimization.py \
         --output-dir /offline_output \
         --config preference_parameters.json

## Second stage to build the final image with a smaller image size

# Using alpine image to reduce the image size further
# Alternatively, you can use python:3.11-slim with a slightly larger image size
FROM python:3.11-slim

# Copy the dependencies from the builder image
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin/uvicorn /usr/local/bin/uvicorn

WORKDIR /code

COPY ./app ./app
COPY ./features ./features
COPY ./common_libs ./common_libs
COPY --from=builder /offline_output ./offline_output

EXPOSE 8080

CMD exec uvicorn app.server:app --host 0.0.0.0 --port 8080
