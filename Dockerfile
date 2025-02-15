# Generated by https://smithery.ai. See: https://smithery.ai/docs/config#dockerfile
# Use the official Python image as the base image
FROM python:3.12-slim AS builder

# Set the working directory
WORKDIR /app

# Copy the necessary files
COPY pyproject.toml /app/
COPY README.md /app/
COPY src /app/src

# Install the project's dependencies
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir hatchling \
    && hatchling build

# Final stage
FROM python:3.12-slim

# Set the working directory
WORKDIR /app

# Copy the build output from the builder stage
COPY --from=builder /app /app

# Install the package
RUN pip install --no-cache-dir /app

EXPOSE 11599

# Set the entry point
ENTRYPOINT ["python", "-m", "mcp_bear"]
