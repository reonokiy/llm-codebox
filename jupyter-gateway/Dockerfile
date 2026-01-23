FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir jupyter_kernel_gateway ipykernel

EXPOSE 9888

CMD ["jupyter", "kernelgateway", "--KernelGatewayApp.api=kernel_gateway.jupyter_websocket", "--ip=0.0.0.0", "--port=9888"]
